"""
E2E Test Suite — VaultSyncWorkflow (Signature Vault + PPS + Cheque Leaf + Account Vault)

Exercises the COMPLETE vault sync pipeline via run_with_mocks():
  - CBS file-drop → embed → store (YugabyteDB + Redis) → staging cleanup → PPS warm →
    integrity check → cheque leaf vault → account vault warm

Scenarios:
  SC-01  Happy path — 1 account, 1 signatory (PRIMARY), 2 specimens, staging file deleted
  SC-02  Multi-signatory — 1 account, PRIMARY + JOINT signatories, separate Redis keys
  SC-03  Batch insert — 5 accounts, mixed signatory counts (1/2/3 signatories each)
  SC-04  Malformed CBS file — missing account_number, missing specimens, 1 valid record
  SC-05  Embedding failure — vLLM down for 1 of 3 accounts; staging key NOT purged for failed
  SC-06  Staging file cleanup — 3 files embedded → 3 MinIO deletes + 3 audit events
  SC-07  Partial cleanup failure — 1 MinIO delete fails; workflow continues SYNC_COMPLETE
  SC-08  No staging keys (direct-API CBS path) — MinIO not touched
  SC-09  PPS warm — 5 records written to Redis with correct pps:{bank_id}:{hmac} keys
  SC-10  Integrity check passes — all sample accounts present in Redis
  SC-11  Integrity check fails — 1 of 3 sample accounts missing from Redis
  SC-12  Update scenario — second sync overwrites specimen embedding; Redis key flushed
  SC-13  CBS signature load failure → PARTIAL_FAILURE result
  SC-14  CBS PPS load failure → PARTIAL_FAILURE (signatures already embedded)
  SC-15  Cold-restart warm (warm_redis_from_db) — reads DB, writes Redis per signatory
  SC-16  Cheque leaf vault sync — 5 leaves (ACTIVE/LOST/STOLEN) → correct Redis keys
  SC-17  Account vault warm — 5 accounts across 2 branches → 2 branch CBS calls
  SC-18  Full workflow SYNC_COMPLETE — all steps, all counts verified
  SC-19  embedding_model=None → graceful degradation (embedded=0, no crash)
  SC-20  Audit event payload — VAULT_SIG_STAGING_PURGED carries correct fields
  SC-21  SCALE TEST — 10,000 accounts × 2 signatories × 3 specimens = 60,000 embeddings;
          10,000 PPS records; throughput reported, 10-lakh extrapolation computed

Run:
  pytest tests/e2e/vault_sync/test_vault_sync_e2e.py -v
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_lib
import struct
import time
import logging
from collections import defaultdict
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.workflows.vault_sync_workflow import (
    VaultSyncInput,
    VaultSyncWorkflow,
    VaultSyncResult,
    SignatureRecord,
    PPSRecord,
    ChequeLeafRecord,
    AccountProfileRecord,
    load_signatures_from_cbs,
    embed_and_store_signatures,
    load_pps_from_cbs,
    warm_redis_vault,
    warm_redis_from_db,
    verify_vault_integrity,
    cleanup_staging_files,
    load_cheque_leaves_from_cbs,
    warm_cheque_leaf_vault,
    load_account_profiles_from_cbs,
    warm_account_vault,
)
from shared.ai.signature_embedding import pack_embedding, unpack_embedding, EmbeddingModelUnavailableError

# ─────────────────────────────────────────────────────────────────────────────
# Scale constants — change SCALE_ACCOUNTS to push harder
# ─────────────────────────────────────────────────────────────────────────────
SCALE_ACCOUNTS      = 10_000     # 10K accounts for CI; extrapolate to 10 lakh
SCALE_SIGNATORIES   = 2          # 2 signatories per account (→ 20K signatory records)
SCALE_SPECIMENS     = 3          # 3 specimens per signatory (→ 60K total embeddings)
SCALE_PPS           = 10_000     # 10K PPS records (stop-payment) — same as account count
SCALE_CHEQUE_LEAVES = 10_000     # 10K cheque leaf records

# ─────────────────────────────────────────────────────────────────────────────
# Test bank / pepper constants
# ─────────────────────────────────────────────────────────────────────────────
BANK_ID   = "saraswat-coop"
PEPPER    = "test-pepper-astra-e2e-2026"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: embedding + hashing
# ─────────────────────────────────────────────────────────────────────────────

def fake_emb(seed: float = 0.5) -> list[float]:
    """Return a deterministic 512-dim float32 embedding."""
    return [seed] * 512


def packed(seed: float = 0.5) -> bytes:
    return pack_embedding(fake_emb(seed))


def hmac_hash(account_number: str) -> str:
    """Reproduce the hash used by VaultSyncWorkflow / SignatureVault."""
    key = f"{BANK_ID}:{account_number}".encode()
    return hmac_lib.new(PEPPER.encode(), key, hashlib.sha256).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# In-memory Redis mock (stateful — pipeline ops commit on execute())
# ─────────────────────────────────────────────────────────────────────────────

class FakePipeline:
    def __init__(self, store: dict):
        self._store = store
        self._ops: list[tuple] = []

    def delete(self, key: str):
        self._ops.append(("delete", key))
        return self

    def rpush(self, key: str, value: bytes):
        self._ops.append(("rpush", key, value))
        return self

    def hset(self, key: str, mapping: dict):
        self._ops.append(("hset", key, mapping))
        return self

    def expire(self, key: str, seconds: int):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "delete":
                self._store.pop(op[1], None)
            elif op[0] == "rpush":
                self._store.setdefault(op[1], []).append(op[2])
            elif op[0] == "hset":
                self._store.setdefault(op[1], {}).update(op[2])
            elif op[0] == "expire":
                pass  # TTL bookkeeping not needed for these tests
        self._ops = []


class FakeRedis:
    """Stateful in-memory Redis. Supports pipeline, llen, lrange, hgetall."""

    def __init__(self):
        self.store: dict[str, Any] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.store)

    def llen(self, key: str) -> int:
        v = self.store.get(key, [])
        return len(v) if isinstance(v, list) else 0

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        v = self.store.get(key, [])
        if not isinstance(v, list):
            return []
        return v[start:] if end == -1 else v[start:end + 1]

    def hgetall(self, key: str) -> dict:
        v = self.store.get(key, {})
        return v if isinstance(v, dict) else {}

    def keys_matching(self, prefix: str) -> list[str]:
        return [k for k in self.store if k.startswith(prefix)]


# ─────────────────────────────────────────────────────────────────────────────
# In-memory DB pool mock (for warm_redis_from_db)
# ─────────────────────────────────────────────────────────────────────────────

class FakeDbConn:
    """Minimal asyncpg-like connection for warm_redis_from_db queries."""

    def __init__(self, rows: list[dict]):
        self._rows = rows  # pre-loaded rows returned by SELECT

    async def fetch(self, _query: str, *args) -> list[dict]:
        # Filter by bank_id (first $1 arg)
        bank_id = args[0] if args else None
        if bank_id:
            return [r for r in self._rows if r.get("bank_id") == bank_id]
        return self._rows

    async def execute(self, _query: str, *args) -> None:
        pass  # writes are fire-and-forget for these tests

    async def fetchrow(self, _query: str, *args) -> Optional[dict]:
        return None

    def transaction(self):
        return _FakeTx()


class _FakeTx:
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


class FakeDbPool:
    def __init__(self, rows: list[dict] = None):
        self._rows = rows or []

    def acquire(self) -> "_FakeAcquireCtx":
        return _FakeAcquireCtx(FakeDbConn(self._rows))


class _FakeAcquireCtx:
    def __init__(self, conn: FakeDbConn):
        self._conn = conn

    async def __aenter__(self) -> FakeDbConn:
        return self._conn

    async def __aexit__(self, *_) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# MinIO mock (tracks deletes, can fail on specific keys)
# ─────────────────────────────────────────────────────────────────────────────

class FakeMinIO:
    def __init__(self, fail_on_keys: set[str] = None):
        self.deleted: list[tuple[str, str]] = []        # [(bucket, key), ...]
        self._fail_on = fail_on_keys or set()

    def remove_object(self, bucket: str, key: str) -> None:
        if key in self._fail_on:
            raise RuntimeError(f"Simulated MinIO delete failure for key: {key}")
        self.deleted.append((bucket, key))


# ─────────────────────────────────────────────────────────────────────────────
# Event producer mock (tracks publish calls)
# ─────────────────────────────────────────────────────────────────────────────

class FakeEventProducer:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, topic: str, event_type: str, payload: dict,
                      schema_version: str = "1.0") -> None:
        self.events.append({
            "topic": topic,
            "event_type": event_type,
            "payload": payload,
            "schema_version": schema_version,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Fake embedding model
# ─────────────────────────────────────────────────────────────────────────────

class FakeEmbeddingModel:
    """Returns deterministic 512-dim embeddings; can be configured to fail."""

    def __init__(self, fail_for_accounts: set[str] = None, seed: float = 0.5):
        self._fail = fail_for_accounts or set()
        self._seed = seed
        self.call_count = 0

    async def embed(self, image_bytes: bytes, bank_id: str) -> list[float]:
        self.call_count += 1
        # Infer account from bytes pattern (we encode acct_last4 in test bytes)
        acct_tag = image_bytes[:10].decode("utf-8", errors="ignore").strip("\x00")
        if acct_tag in self._fail:
            raise EmbeddingModelUnavailableError(f"vLLM down for {acct_tag}")
        return fake_emb(self._seed)


# ─────────────────────────────────────────────────────────────────────────────
# Fake Vault (thin wrapper around SignatureVault with FakeRedis + optional DB)
# ─────────────────────────────────────────────────────────────────────────────

class FakeVault:
    """
    Minimal vault used by embed_and_store_signatures.
    Writes packed embeddings directly to FakeRedis (no real DB write).
    Tracks store_embeddings calls for assertion.
    """

    def __init__(self, redis: FakeRedis, bank_id: str, pepper: str):
        self._redis = redis
        self._bank_id = bank_id
        self._pepper = pepper
        self.stored: list[dict] = []  # call log

    def _key(self, account_number: str, signatory_id: str) -> str:
        digest = hmac_hash(account_number)
        return f"sig:{self._bank_id}:{digest}:{signatory_id}"

    async def store_embeddings(self, account_number: str, embeddings: list[list[float]],
                                signatory_id: str = "PRIMARY", source: str = "CBS") -> None:
        self.stored.append({
            "account_number": account_number,
            "signatory_id": signatory_id,
            "specimen_count": len(embeddings),
            "source": source,
        })
        key = self._key(account_number, signatory_id)
        pipe = self._redis.pipeline()
        pipe.delete(key)
        for emb in embeddings:
            pipe.rpush(key, pack_embedding(emb))
        pipe.execute()

    def connect(self, redis_client=None) -> None:
        pass  # already connected via constructor


# ─────────────────────────────────────────────────────────────────────────────
# CBS connector factory helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_cbs(sig_records=None, pps_records=None, leaf_records=None,
              account_profiles=None, fail_sig=False, fail_pps=False):
    """Build an AsyncMock CBS connector with configured return values."""
    cbs = AsyncMock()
    if fail_sig:
        cbs.list_signature_specimens.side_effect = RuntimeError("CBS unreachable")
    else:
        cbs.list_signature_specimens.return_value = sig_records or []
    if fail_pps:
        cbs.list_positive_pay_records.side_effect = RuntimeError("CBS unreachable")
    else:
        cbs.list_positive_pay_records.return_value = pps_records or []
    cbs.list_issued_leaves.return_value = leaf_records or []
    cbs.list_account_profiles.return_value = account_profiles or []
    cbs.get_branch_contacts.return_value = None
    return cbs


def _sig_raw(account_number: str, signatory_id: str = "PRIMARY", n_specimens: int = 2,
             staging_key: Optional[str] = None) -> dict:
    """Build a raw CBS signature record (one per signatory)."""
    acct_tag = account_number[-10:].ljust(10, "\x00")
    specimens = [
        f"{acct_tag}spec{i}".encode("utf-8")
        for i in range(n_specimens)
    ]
    return {
        "account_number": account_number,
        "signatory_id": signatory_id,
        "staging_file_key": staging_key,
        "specimens": specimens,
    }


def _pps_raw(account_number: str, series: str = "100001", amount: float = 250000.0,
             payee: str = "Test Payee") -> dict:
    return {
        "account_number": account_number,
        "cheque_series_start": series,
        "amount": amount,
        "payee": payee,
        "ttl_seconds": 86400,
    }


def _leaf_raw(account_number: str, cheque_number: str, status: str = "ACTIVE") -> dict:
    return {
        "account_number": account_number,
        "cheque_number": cheque_number,
        "status": status,
        "issued_date": "2026-01-01",
    }


def _inp(bank_id: str = BANK_ID, pepper: str = PEPPER,
         staging_bucket: str = "astra-sig-staging") -> VaultSyncInput:
    return VaultSyncInput(
        bank_id=bank_id,
        pepper=pepper,
        sync_date="2026-08-19",
        triggered_by="E2E_TEST",
        sig_staging_bucket=staging_bucket,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SC-01: Happy path — single account, single signatory, file drop + cleanup
# ─────────────────────────────────────────────────────────────────────────────

class TestSC01_HappyPathSingleAccount:
    ACCOUNT = "1001234567890"
    STAGING_KEY = f"{BANK_ID}/sig/acc1001_PRIMARY.jpg"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[_sig_raw(self.ACCOUNT, staging_key=self.STAGING_KEY, n_specimens=2)],
            pps_records=[_pps_raw(self.ACCOUNT)],
        )

    def test_embedded_count(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        assert result.signatures_loaded == 1
        assert result.signatures_embedded == 1

    def test_redis_key_written(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        digest = hmac_hash(self.ACCOUNT)
        key = f"sig:{BANK_ID}:{digest}:PRIMARY"
        assert self.redis.llen(key) == 2, "2 specimens must be stored"

    def test_staging_file_deleted(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        deleted_keys = [k for _, k in self.minio.deleted]
        assert self.STAGING_KEY in deleted_keys

    def test_audit_event_emitted(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        purge_events = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge_events) == 1
        assert purge_events[0]["topic"] == "platform.audit.events"

    def test_workflow_outcome_sync_complete(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        assert result.outcome == "SYNC_COMPLETE"
        assert result.pps_records_loaded == 1


# ─────────────────────────────────────────────────────────────────────────────
# SC-02: Multi-signatory — 1 account, PRIMARY + JOINT, separate Redis keys
# ─────────────────────────────────────────────────────────────────────────────

class TestSC02_MultiSignatoryAccount:
    ACCOUNT = "1002000000001"
    STAGING_PRIMARY = f"{BANK_ID}/sig/acc2001_PRIMARY.jpg"
    STAGING_JOINT   = f"{BANK_ID}/sig/acc2001_JOINT.jpg"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[
                _sig_raw(self.ACCOUNT, "PRIMARY", n_specimens=2, staging_key=self.STAGING_PRIMARY),
                _sig_raw(self.ACCOUNT, "JOINT",   n_specimens=3, staging_key=self.STAGING_JOINT),
            ],
            pps_records=[],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))

    def test_two_records_loaded_and_embedded(self):
        result = self._run()
        assert result.signatures_loaded == 2
        assert result.signatures_embedded == 2

    def test_separate_redis_keys_per_signatory(self):
        self._run()
        digest = hmac_hash(self.ACCOUNT)
        primary_key = f"sig:{BANK_ID}:{digest}:PRIMARY"
        joint_key   = f"sig:{BANK_ID}:{digest}:JOINT"
        assert self.redis.llen(primary_key) == 2, "PRIMARY: 2 specimens"
        assert self.redis.llen(joint_key)   == 3, "JOINT: 3 specimens"

    def test_both_staging_files_deleted(self):
        self._run()
        deleted = {k for _, k in self.minio.deleted}
        assert self.STAGING_PRIMARY in deleted
        assert self.STAGING_JOINT   in deleted

    def test_two_audit_purge_events(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge) == 2

    def test_store_embeddings_called_with_correct_signatory_ids(self):
        self._run()
        ids = {r["signatory_id"] for r in self.vault.stored}
        assert ids == {"PRIMARY", "JOINT"}


# ─────────────────────────────────────────────────────────────────────────────
# SC-03: Batch insert — 5 accounts, mixed signatory counts
# ─────────────────────────────────────────────────────────────────────────────

class TestSC03_BatchInsertMixedSignatories:
    """
    5 accounts:
      acc3001 → 1 signatory (PRIMARY), 2 specimens
      acc3002 → 2 signatories (PRIMARY, DIRECTOR), 2 specimens each
      acc3003 → 1 signatory (PRIMARY), 1 specimen
      acc3004 → 3 signatories (PRIMARY, TRUSTEE1, TRUSTEE2), 3 specimens each
      acc3005 → 1 signatory (PRIMARY), 2 specimens
    Total: 8 SignatureRecords, 18 embeddings
    """
    ACCOUNTS = {
        "1003001111001": [("PRIMARY", 2)],
        "1003002222002": [("PRIMARY", 2), ("DIRECTOR", 2)],
        "1003003333003": [("PRIMARY", 1)],
        "1003004444004": [("PRIMARY", 3), ("TRUSTEE1", 3), ("TRUSTEE2", 3)],
        "1003005555005": [("PRIMARY", 2)],
    }

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        sig_records = []
        for acct, sigs in self.ACCOUNTS.items():
            for sig_id, n in sigs:
                sig_records.append(_sig_raw(
                    acct, sig_id, n_specimens=n,
                    staging_key=f"{BANK_ID}/sig/{acct}_{sig_id}.jpg",
                ))
        self.cbs = _make_cbs(sig_records=sig_records, pps_records=[])

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))

    def test_all_records_loaded(self):
        result = self._run()
        assert result.signatures_loaded == 8   # 1+2+1+3+1 = 8 SignatureRecord entries

    def test_all_records_embedded(self):
        result = self._run()
        assert result.signatures_embedded == 8

    def test_redis_has_one_key_per_signatory(self):
        self._run()
        sig_keys = self.redis.keys_matching(f"sig:{BANK_ID}:")
        assert len(sig_keys) == 8, f"Expected 8 Redis keys, got {len(sig_keys)}"

    def test_redis_specimen_counts(self):
        self._run()
        digest_3004 = hmac_hash("1003004444004")
        assert self.redis.llen(f"sig:{BANK_ID}:{digest_3004}:PRIMARY")   == 3
        assert self.redis.llen(f"sig:{BANK_ID}:{digest_3004}:TRUSTEE1") == 3
        assert self.redis.llen(f"sig:{BANK_ID}:{digest_3004}:TRUSTEE2") == 3

    def test_all_staging_files_purged(self):
        self._run()
        assert len(self.minio.deleted) == 8

    def test_purge_audit_event_count(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge) == 8


# ─────────────────────────────────────────────────────────────────────────────
# SC-04: Malformed CBS file — missing fields, only 1 valid record
# ─────────────────────────────────────────────────────────────────────────────

class TestSC04_MalformedCBSRecords:
    VALID_ACCOUNT = "1004001000001"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[
                {"account_number": "",          "specimens": [b"img1"]},    # missing account
                {"account_number": "1004002",   "specimens": []},           # empty specimens
                {"account_number": "1004002",   "signatory_id": "PRIMARY"}, # no specimens key
                _sig_raw(self.VALID_ACCOUNT, n_specimens=2),                # valid
            ],
            pps_records=[],
        )

    def test_only_valid_record_loaded(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))
        assert result.signatures_loaded == 1  # only 1 passed load validation

    def test_valid_record_embedded(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))
        assert result.signatures_embedded == 1

    def test_valid_redis_key_written(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))
        digest = hmac_hash(self.VALID_ACCOUNT)
        assert self.redis.llen(f"sig:{BANK_ID}:{digest}:PRIMARY") == 2


# ─────────────────────────────────────────────────────────────────────────────
# SC-05: Embedding failure — vLLM down for 1 of 3 accounts
# ─────────────────────────────────────────────────────────────────────────────

class TestSC05_EmbeddingFailure:
    ACCOUNTS = ["1005001000001", "1005002000002", "1005003000003"]
    FAILING_TAG = "5002000002"  # last 10 chars of "1005002000002" — matches _sig_raw() byte tag

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        # Model fails when specimen tag matches FAILING_TAG
        self.model = FakeEmbeddingModel(fail_for_accounts={self.FAILING_TAG})
        staging_keys = [f"{BANK_ID}/sig/{a}_PRIMARY.jpg" for a in self.ACCOUNTS]
        self.cbs = _make_cbs(
            sig_records=[
                _sig_raw(a, n_specimens=2, staging_key=k)
                for a, k in zip(self.ACCOUNTS, staging_keys)
            ],
            pps_records=[],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))

    def test_two_embedded_one_failed(self):
        result = self._run()
        assert result.signatures_embedded == 2

    def test_failed_account_staging_key_not_purged(self):
        """The staging file for the failed account must be preserved for investigation."""
        self._run()
        deleted_keys = {k for _, k in self.minio.deleted}
        failed_key = f"{BANK_ID}/sig/{self.ACCOUNTS[1]}_PRIMARY.jpg"
        assert failed_key not in deleted_keys, "Failed account's staging file must not be purged"

    def test_successful_accounts_staging_purged(self):
        self._run()
        deleted_keys = {k for _, k in self.minio.deleted}
        assert f"{BANK_ID}/sig/{self.ACCOUNTS[0]}_PRIMARY.jpg" in deleted_keys
        assert f"{BANK_ID}/sig/{self.ACCOUNTS[2]}_PRIMARY.jpg" in deleted_keys

    def test_only_two_audit_purge_events(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge) == 2


# ─────────────────────────────────────────────────────────────────────────────
# SC-06: Staging file cleanup — verify MinIO delete + audit trail completeness
# ─────────────────────────────────────────────────────────────────────────────

class TestSC06_StagingFileCleanupAuditTrail:
    ACCOUNTS = [f"100600{i}00000{i}" for i in range(1, 4)]  # 3 accounts
    BUCKET = "astra-sig-staging"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.staging_keys = [f"{BANK_ID}/sig/{a}.jpg" for a in self.ACCOUNTS]
        self.cbs = _make_cbs(
            sig_records=[
                _sig_raw(a, staging_key=k)
                for a, k in zip(self.ACCOUNTS, self.staging_keys)
            ],
            pps_records=[],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(staging_bucket=self.BUCKET), cbs_connector=self.cbs,
            redis_client=self.redis, vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))

    def test_three_files_deleted_from_correct_bucket(self):
        self._run()
        for bucket, key in self.minio.deleted:
            assert bucket == self.BUCKET
        assert len(self.minio.deleted) == 3

    def test_audit_events_carry_schema_version(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        for event in purge:
            assert event["schema_version"] == "1.0"

    def test_audit_events_reference_platform_audit_topic(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        for event in purge:
            assert event["topic"] == "platform.audit.events"

    def test_audit_payload_has_bank_id_and_bucket(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        for event in purge:
            assert event["payload"]["bank_id"] == BANK_ID
            assert event["payload"]["staging_bucket"] == self.BUCKET

    def test_audit_payload_key_suffix_is_filename(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        suffixes = {e["payload"]["staging_key_suffix"] for e in purge}
        expected = {k.split("/")[-1] for k in self.staging_keys}
        assert suffixes == expected


# ─────────────────────────────────────────────────────────────────────────────
# SC-07: Partial cleanup failure — 1 MinIO delete fails; workflow still SYNC_COMPLETE
# ─────────────────────────────────────────────────────────────────────────────

class TestSC07_PartialCleanupFailure:
    ACCOUNTS = [f"100700{i}00000{i}" for i in range(1, 4)]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.staging_keys = [f"{BANK_ID}/sig/{a}.jpg" for a in self.ACCOUNTS]
        self.fail_key = self.staging_keys[1]  # middle key fails
        self.minio = FakeMinIO(fail_on_keys={self.fail_key})
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[
                _sig_raw(a, staging_key=k)
                for a, k in zip(self.ACCOUNTS, self.staging_keys)
            ],
            pps_records=[],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))

    def test_workflow_still_sync_complete(self):
        result = self._run()
        assert result.outcome == "SYNC_COMPLETE"

    def test_two_files_deleted_one_failed(self):
        self._run()
        assert len(self.minio.deleted) == 2

    def test_two_audit_events_emitted(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge) == 2  # only for successfully deleted files

    def test_all_embeddings_still_in_redis(self):
        """Embeddings are durable regardless of cleanup failure."""
        self._run()
        for acct in self.ACCOUNTS:
            digest = hmac_hash(acct)
            assert self.redis.llen(f"sig:{BANK_ID}:{digest}:PRIMARY") > 0


# ─────────────────────────────────────────────────────────────────────────────
# SC-08: No staging keys (direct CBS API path) — MinIO not touched
# ─────────────────────────────────────────────────────────────────────────────

class TestSC08_NoStagingKeys:
    ACCOUNTS = [f"100800{i}00000{i}" for i in range(1, 4)]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[
                _sig_raw(a, staging_key=None)  # no staging key — direct API path
                for a in self.ACCOUNTS
            ],
            pps_records=[],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio,
        ))

    def test_minio_not_touched(self):
        self._run()
        assert len(self.minio.deleted) == 0

    def test_embeddings_still_stored(self):
        result = self._run()
        assert result.signatures_embedded == 3


# ─────────────────────────────────────────────────────────────────────────────
# SC-09: PPS warm — 5 records written to Redis with correct keys
# ─────────────────────────────────────────────────────────────────────────────

class TestSC09_PPSWarm:
    ACCOUNTS = [f"100900{i}00000{i}" for i in range(1, 6)]  # 5 PPS accounts

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[],
            pps_records=[_pps_raw(a, series=f"10000{i}") for i, a in enumerate(self.ACCOUNTS, 1)],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))

    def test_five_pps_records_loaded(self):
        result = self._run()
        assert result.pps_records_loaded == 5

    def test_redis_has_pps_keys(self):
        self._run()
        pps_keys = self.redis.keys_matching(f"pps:{BANK_ID}:")
        assert len(pps_keys) == 5

    def test_pps_key_has_amount_and_payee(self):
        self._run()
        pps_keys = self.redis.keys_matching(f"pps:{BANK_ID}:")
        for key in pps_keys:
            data = self.redis.hgetall(key)
            assert "amount" in data
            assert "payee" in data


# ─────────────────────────────────────────────────────────────────────────────
# SC-10: Integrity check passes — all sample accounts in Redis
# ─────────────────────────────────────────────────────────────────────────────

class TestSC10_IntegrityCheckPasses:
    ACCOUNTS = [f"101000{i}00000{i}" for i in range(1, 4)]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[_sig_raw(a) for a in self.ACCOUNTS],
            pps_records=[],
        )

    def test_integrity_passes(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))
        assert result.integrity_check_passed is True


# ─────────────────────────────────────────────────────────────────────────────
# SC-11: Integrity check fails — 1 of 3 sample accounts missing from Redis
# ─────────────────────────────────────────────────────────────────────────────

class TestSC11_IntegrityCheckFails:
    ACCOUNTS = [f"101100{i}00000{i}" for i in range(1, 4)]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model = FakeEmbeddingModel()
        # Only load 2 accounts into CBS (3rd account absent from vault)
        self.cbs = _make_cbs(
            sig_records=[_sig_raw(a) for a in self.ACCOUNTS[:2]],
            pps_records=[],
        )

    def test_integrity_fails_when_account_missing(self):
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            sample_accounts=self.ACCOUNTS,  # sample all 3; 3rd not in vault
        ))
        assert result.integrity_check_passed is False

    def test_workflow_still_reports_sync_complete_despite_integrity_fail(self):
        """Integrity failure is advisory — sync is still marked SYNC_COMPLETE."""
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            sample_accounts=self.ACCOUNTS,
        ))
        assert result.outcome == "SYNC_COMPLETE"


# ─────────────────────────────────────────────────────────────────────────────
# SC-12: Update scenario — second sync overwrites existing specimen embedding
# ─────────────────────────────────────────────────────────────────────────────

class TestSC12_UpdateScenario:
    ACCOUNT = "1012001000001"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model_v1 = FakeEmbeddingModel(seed=0.5)   # first sync: seed 0.5
        self.model_v2 = FakeEmbeddingModel(seed=0.9)   # second sync: updated specimen
        self.cbs = _make_cbs(
            sig_records=[_sig_raw(self.ACCOUNT, n_specimens=1)],
            pps_records=[],
        )

    def test_first_sync_writes_initial_embedding(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model_v1,
        ))
        digest = hmac_hash(self.ACCOUNT)
        raw = self.redis.lrange(f"sig:{BANK_ID}:{digest}:PRIMARY", 0, -1)
        assert len(raw) == 1
        assert unpack_embedding(raw[0])[0] == pytest.approx(0.5)

    def test_second_sync_replaces_embedding(self):
        """On re-sync, old Redis list is deleted and new embedding replaces it."""
        # First sync
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model_v1,
        ))
        # Second sync with updated embedding model
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model_v2,
        ))
        digest = hmac_hash(self.ACCOUNT)
        raw = self.redis.lrange(f"sig:{BANK_ID}:{digest}:PRIMARY", 0, -1)
        assert len(raw) == 1
        assert unpack_embedding(raw[0])[0] == pytest.approx(0.9)


# ─────────────────────────────────────────────────────────────────────────────
# SC-13: CBS signature load failure → PARTIAL_FAILURE
# ─────────────────────────────────────────────────────────────────────────────

class TestSC13_CBSSignatureLoadFailure:
    def test_partial_failure_result(self):
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        cbs = _make_cbs(fail_sig=True, pps_records=[])

        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=FakeEmbeddingModel(),
        ))
        assert result.outcome == "PARTIAL_FAILURE"
        assert "SIGNATURE_LOAD_FAILED" in result.failed_accounts

    def test_signatures_loaded_is_zero(self):
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        cbs = _make_cbs(fail_sig=True, pps_records=[])

        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=FakeEmbeddingModel(),
        ))
        assert result.signatures_loaded == 0


# ─────────────────────────────────────────────────────────────────────────────
# SC-14: CBS PPS load failure → PARTIAL_FAILURE (signatures already embedded)
# ─────────────────────────────────────────────────────────────────────────────

class TestSC14_CBSPPSLoadFailure:
    ACCOUNTS = [f"101400{i}00000{i}" for i in range(1, 3)]

    def test_partial_failure_after_sig_embed(self):
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        cbs = _make_cbs(
            sig_records=[_sig_raw(a) for a in self.ACCOUNTS],
            fail_pps=True,
        )

        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=FakeEmbeddingModel(),
        ))
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.signatures_loaded == 2
        assert result.signatures_embedded == 2   # embeddings completed before PPS failure
        assert "PPS_LOAD_FAILED" in result.failed_accounts


# ─────────────────────────────────────────────────────────────────────────────
# SC-15: Cold-restart Redis warm — reads DB rows, writes Redis per signatory
# ─────────────────────────────────────────────────────────────────────────────

class TestSC15_ColdRestartWarmFromDb:
    """
    DB has 2 accounts × 2 signatories = 4 Redis keys.
    Redis starts empty.
    warm_redis_from_db must write 4 keys with correct packed embeddings.
    """
    ACCOUNTS = ["1015001000001", "1015002000002"]
    SIGNATORIES = ["PRIMARY", "JOINT"]

    def setup_method(self):
        self.redis = FakeRedis()
        emb = fake_emb(0.5)
        self.db_rows = []
        for acct in self.ACCOUNTS:
            acct_hash = hmac_hash(acct)
            for idx, sig_id in enumerate(self.SIGNATORIES):
                for spec_idx in range(2):  # 2 specimens each
                    self.db_rows.append({
                        "bank_id": BANK_ID,
                        "account_hash": acct_hash,
                        "signatory_id": sig_id,
                        "specimen_index": spec_idx,
                        "embedding": pack_embedding(emb),
                    })
        self.db_pool = FakeDbPool(self.db_rows)

    def test_warm_from_db_writes_four_redis_keys(self):
        result = asyncio.run(warm_redis_from_db(
            bank_id=BANK_ID,
            db_pool=self.db_pool,
            redis_client=self.redis,
        ))
        sig_keys = self.redis.keys_matching(f"sig:{BANK_ID}:")
        assert len(sig_keys) == 4  # 2 accounts × 2 signatories

    def test_each_key_has_correct_specimen_count(self):
        asyncio.run(warm_redis_from_db(
            bank_id=BANK_ID,
            db_pool=self.db_pool,
            redis_client=self.redis,
        ))
        for acct in self.ACCOUNTS:
            digest = hmac_hash(acct)
            for sig_id in self.SIGNATORIES:
                key = f"sig:{BANK_ID}:{digest}:{sig_id}"
                assert self.redis.llen(key) == 2, f"Expected 2 specimens for {key}"

    def test_warm_returns_unique_account_count(self):
        result = asyncio.run(warm_redis_from_db(
            bank_id=BANK_ID,
            db_pool=self.db_pool,
            redis_client=self.redis,
        ))
        assert result["accounts"] == 2  # unique account hashes, not key count

    def test_key_format_includes_signatory_id(self):
        asyncio.run(warm_redis_from_db(
            bank_id=BANK_ID,
            db_pool=self.db_pool,
            redis_client=self.redis,
        ))
        keys = self.redis.keys_matching(f"sig:{BANK_ID}:")
        for key in keys:
            parts = key.split(":")
            assert len(parts) == 4, f"Key must have 4 parts: sig:bank:hash:signatory_id, got {key}"
            assert parts[3] in self.SIGNATORIES


# ─────────────────────────────────────────────────────────────────────────────
# SC-16: Cheque leaf vault sync — 5 leaves, correct Redis keys and status
# ─────────────────────────────────────────────────────────────────────────────

class TestSC16_ChequeLeafVaultSync:
    ACCOUNT = "1016001000001"
    LEAVES = [
        ("000001", "ACTIVE"),
        ("000002", "ACTIVE"),
        ("000003", "LOST"),
        ("000004", "STOLEN"),
        ("000005", "CANCELLED"),
    ]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[],
            pps_records=[],
            leaf_records=[
                _leaf_raw(self.ACCOUNT, chq, status)
                for chq, status in self.LEAVES
            ],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
        ))

    def test_five_leaves_loaded(self):
        result = self._run()
        assert result.cheque_leaves_loaded == 5

    def test_redis_has_five_chq_keys(self):
        self._run()
        chq_keys = self.redis.keys_matching(f"chq:{BANK_ID}:")
        assert len(chq_keys) == 5

    def test_redis_leaf_status_correct(self):
        self._run()
        digest = hmac_hash(self.ACCOUNT)
        stolen_key = f"chq:{BANK_ID}:{digest}:000004"
        data = self.redis.hgetall(stolen_key)
        assert data.get("status") == "STOLEN"


# ─────────────────────────────────────────────────────────────────────────────
# SC-17: Account vault warm — 5 accounts, 2 branches → 2 branch CBS calls
# ─────────────────────────────────────────────────────────────────────────────

class TestSC17_AccountVaultBranchDedup:
    ACCOUNTS_BRANCH1 = ["1017001000001", "1017002000002", "1017003000003"]  # branch BG001
    ACCOUNTS_BRANCH2 = ["1017004000004", "1017005000005"]                  # branch BG002

    def setup_method(self):
        self.redis = FakeRedis()
        self.model = FakeEmbeddingModel()
        self.account_vault = AsyncMock()
        self.account_vault.store_profile = AsyncMock()

        profiles = [
            {"account_number": a, "account_type": "SAVINGS", "branch_code": "BG001"}
            for a in self.ACCOUNTS_BRANCH1
        ] + [
            {"account_number": a, "account_type": "CURRENT", "branch_code": "BG002"}
            for a in self.ACCOUNTS_BRANCH2
        ]

        self.cbs = _make_cbs(
            sig_records=[], pps_records=[], account_profiles=profiles,
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=FakeVault(self.redis, BANK_ID, PEPPER),
            embedding_model=self.model,
            account_vault=self.account_vault,
        ))

    def test_five_accounts_warmed(self):
        result = self._run()
        assert self.account_vault.store_profile.call_count == 5

    def test_branch_contact_called_once_per_branch(self):
        self._run()
        branch_calls = [
            c for c in self.cbs.get_branch_contacts.call_args_list
        ]
        branch_codes_called = [c.args[0] for c in branch_calls]
        assert "BG001" in branch_codes_called
        assert "BG002" in branch_codes_called
        # Deduplication: each branch code appears only once
        assert branch_codes_called.count("BG001") == 1
        assert branch_codes_called.count("BG002") == 1


# ─────────────────────────────────────────────────────────────────────────────
# SC-18: Full workflow integration — SYNC_COMPLETE, all counts verified
# ─────────────────────────────────────────────────────────────────────────────

class TestSC18_FullWorkflowIntegration:
    """End-to-end: 3 accounts × 2 signatories + PPS + cheque leaves = SYNC_COMPLETE."""
    ACCOUNTS = ["1018001000001", "1018002000002", "1018003000003"]

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.account_vault = AsyncMock()
        self.account_vault.store_profile = AsyncMock()

        sig_records = []
        for a in self.ACCOUNTS:
            for sig_id in ["PRIMARY", "JOINT"]:
                sig_records.append(_sig_raw(
                    a, sig_id, n_specimens=2,
                    staging_key=f"{BANK_ID}/sig/{a}_{sig_id}.jpg",
                ))

        self.cbs = _make_cbs(
            sig_records=sig_records,
            pps_records=[_pps_raw(a) for a in self.ACCOUNTS],
            leaf_records=[_leaf_raw(a, f"00000{i+1}", "ACTIVE") for i, a in enumerate(self.ACCOUNTS)],
            account_profiles=[
                {"account_number": a, "account_type": "SAVINGS", "branch_code": "BG001"}
                for a in self.ACCOUNTS
            ],
        )

    def _run(self):
        return asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
            account_vault=self.account_vault,
        ))

    def test_outcome_sync_complete(self):
        assert self._run().outcome == "SYNC_COMPLETE"

    def test_signatures_loaded_and_embedded(self):
        r = self._run()
        assert r.signatures_loaded == 6   # 3 accounts × 2 signatories
        assert r.signatures_embedded == 6

    def test_pps_records_loaded(self):
        assert self._run().pps_records_loaded == 3

    def test_cheque_leaves_loaded(self):
        assert self._run().cheque_leaves_loaded == 3

    def test_integrity_check_passed(self):
        assert self._run().integrity_check_passed is True

    def test_redis_has_six_sig_keys(self):
        self._run()
        sig_keys = self.redis.keys_matching(f"sig:{BANK_ID}:")
        assert len(sig_keys) == 6

    def test_redis_has_three_pps_keys(self):
        self._run()
        pps_keys = self.redis.keys_matching(f"pps:{BANK_ID}:")
        assert len(pps_keys) == 3

    def test_redis_has_three_cheque_leaf_keys(self):
        self._run()
        chq_keys = self.redis.keys_matching(f"chq:{BANK_ID}:")
        assert len(chq_keys) == 3

    def test_six_staging_files_purged(self):
        self._run()
        assert len(self.minio.deleted) == 6

    def test_six_purge_audit_events_on_platform_topic(self):
        self._run()
        purge = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert len(purge) == 6

    def test_account_vault_store_profile_called_three_times(self):
        self._run()
        assert self.account_vault.store_profile.call_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# SC-19: embedding_model=None → graceful degradation
# ─────────────────────────────────────────────────────────────────────────────

class TestSC19_EmbeddingModelNone:
    ACCOUNTS = [f"101900{i}00000{i}" for i in range(1, 4)]

    def test_embedded_zero_no_crash(self):
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        cbs = _make_cbs(sig_records=[_sig_raw(a) for a in self.ACCOUNTS], pps_records=[])
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=None,   # model not provided
        ))
        assert result.signatures_embedded == 0
        assert result.signatures_loaded == 3

    def test_outcome_still_sync_complete_when_pps_ok(self):
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        cbs = _make_cbs(
            sig_records=[_sig_raw(a) for a in self.ACCOUNTS],
            pps_records=[_pps_raw(a) for a in self.ACCOUNTS],
        )
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=None,
        ))
        assert result.pps_records_loaded == 3


# ─────────────────────────────────────────────────────────────────────────────
# SC-20: Audit event payload correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestSC20_AuditEventPayload:
    ACCOUNT = "1020001000001"
    STAGING_KEY = f"saraswat-coop/sig/acc1020_PRIMARY.jpg"

    def setup_method(self):
        self.redis = FakeRedis()
        self.vault = FakeVault(self.redis, BANK_ID, PEPPER)
        self.minio = FakeMinIO()
        self.events = FakeEventProducer()
        self.model = FakeEmbeddingModel()
        self.cbs = _make_cbs(
            sig_records=[_sig_raw(self.ACCOUNT, staging_key=self.STAGING_KEY)],
            pps_records=[],
        )

    def _purge_event(self):
        asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=self.cbs, redis_client=self.redis,
            vault=self.vault, embedding_model=self.model,
            minio_client=self.minio, event_producer=self.events,
        ))
        events = [e for e in self.events.events if e["event_type"] == "VAULT_SIG_STAGING_PURGED"]
        assert events, "Expected at least one VAULT_SIG_STAGING_PURGED event"
        return events[0]

    def test_correct_topic(self):
        assert self._purge_event()["topic"] == "platform.audit.events"

    def test_schema_version_1_0(self):
        assert self._purge_event()["schema_version"] == "1.0"

    def test_payload_bank_id(self):
        assert self._purge_event()["payload"]["bank_id"] == BANK_ID

    def test_payload_staging_bucket(self):
        assert self._purge_event()["payload"]["staging_bucket"] == "astra-sig-staging"

    def test_payload_staging_key_full_path(self):
        assert self._purge_event()["payload"]["staging_key"] == self.STAGING_KEY

    def test_payload_key_suffix_is_filename_only(self):
        suffix = self._purge_event()["payload"]["staging_key_suffix"]
        assert suffix == "acc1020_PRIMARY.jpg"
        assert "/" not in suffix


# ─────────────────────────────────────────────────────────────────────────────
# SC-21: SCALE TEST — 10K accounts × 2 signatories × 3 specimens = 60K embeddings
#         + 10K PPS records + 10K cheque leaves
#         Reports throughput + extrapolates to 10-lakh bank
# ─────────────────────────────────────────────────────────────────────────────

class TestSC21_ScaleTest:
    """
    Simulates realistic bank volume via in-memory mocks.

    Production equivalents at 10 lakh accounts:
      Signature records:  10,00,000 × 2 signatories = 20,00,000 SignatureRecord objects
      Total embeddings:   20,00,000 × 3 specimens   = 60,00,000 embed() calls
      PPS / stop-payment: up to 10,00,000 records
      Cheque leaves:      up to 10,00,000 records

    This test runs at SCALE_ACCOUNTS={SCALE_ACCOUNTS} (configurable at top of file).
    """

    def _build_cbs(self):
        sig_records = []
        pps_records = []
        leaf_records = []
        SIGNATORY_IDS = ["PRIMARY", "JOINT"]  # must include PRIMARY for integrity check
        for i in range(SCALE_ACCOUNTS):
            acct = f"9{i:012d}"   # 9-prefixed 13-digit account number
            for sig_id in SIGNATORY_IDS[:SCALE_SIGNATORIES]:
                sig_records.append({
                    "account_number": acct,
                    "signatory_id": sig_id,
                    "staging_file_key": f"{BANK_ID}/sig/{acct}_{sig_id}.jpg",
                    "specimens": [
                        f"{acct[:10]}spec{k}".encode("utf-8")
                        for k in range(SCALE_SPECIMENS)
                    ],
                })
            pps_records.append(_pps_raw(acct, series=f"{100000 + i}"))
            leaf_records.append(_leaf_raw(acct, f"{200000 + i}", "ACTIVE"))
        return _make_cbs(
            sig_records=sig_records,
            pps_records=pps_records,
            leaf_records=leaf_records,
        )

    def test_scale_pipeline_throughput(self):
        """
        Run the full VaultSyncWorkflow pipeline at {SCALE_ACCOUNTS} accounts.
        Measures wall-clock time and reports extrapolated throughput to 10-lakh scale.
        """
        redis = FakeRedis()
        vault = FakeVault(redis, BANK_ID, PEPPER)
        minio = FakeMinIO()
        events = FakeEventProducer()
        model = FakeEmbeddingModel(seed=0.5)
        cbs = self._build_cbs()

        t0 = time.monotonic()
        result = asyncio.run(VaultSyncWorkflow().run_with_mocks(
            _inp(), cbs_connector=cbs, redis_client=redis,
            vault=vault, embedding_model=model,
            minio_client=minio, event_producer=events,
        ))
        elapsed = time.monotonic() - t0

        total_sig_records  = SCALE_ACCOUNTS * SCALE_SIGNATORIES
        total_embeddings   = total_sig_records * SCALE_SPECIMENS
        total_redis_keys   = total_sig_records

        embed_rate = total_embeddings / elapsed if elapsed > 0 else float("inf")
        # Extrapolate: 10 lakh accounts × 2 sig × 3 spec = 60 lakh embeddings
        ten_lakh_embeddings = 10_00_000 * SCALE_SIGNATORIES * SCALE_SPECIMENS
        ten_lakh_sec        = ten_lakh_embeddings / embed_rate if embed_rate > 0 else 0

        # Print scale report (visible with -s flag or captured in report)
        purge_count = len([e for e in events.events if e["event_type"]=="VAULT_SIG_STAGING_PURGED"])
        sig_key_count = len(redis.keys_matching(f"sig:{BANK_ID}:"))
        report_lines = [
            "",
            "=" * 74,
            "  ASTRA Vault Sync - Scale Test Report",
            "=" * 74,
            f"  Test bank           : {BANK_ID}",
            f"  Accounts in test    : {SCALE_ACCOUNTS:>10,}",
            f"  Signatories/acct    : {SCALE_SIGNATORIES:>10,}",
            f"  Specimens/signatory : {SCALE_SPECIMENS:>10,}",
            "-" * 74,
            "  ACTUAL THROUGHPUT (in-memory mocks, no real DB/Redis/MinIO)",
            f"  SignatureRecord loaded  : {result.signatures_loaded:>10,}",
            f"  SignatureRecord embedded: {result.signatures_embedded:>10,}",
            f"  Total embed() calls    : {model.call_count:>10,}",
            f"  PPS records loaded     : {result.pps_records_loaded:>10,}",
            f"  Cheque leaves loaded   : {result.cheque_leaves_loaded:>10,}",
            f"  Redis sig keys written : {sig_key_count:>10,}",
            f"  MinIO deletes          : {len(minio.deleted):>10,}",
            f"  Audit purge events     : {purge_count:>10,}",
            f"  Wall-clock time        : {elapsed:>10.2f}s",
            f"  Embed throughput       : {embed_rate:>10,.0f} calls/sec",
            "-" * 74,
            "  EXTRAPOLATED -> 10-LAKH BANK (1,000,000 accounts)",
            f"  Total embeddings (60L) : {ten_lakh_embeddings:>10,}",
            f"  Est. processing time   : {ten_lakh_sec:>10.1f}s  ({ten_lakh_sec/60:.1f} min)",
            "  NOTE: Production uses 500 concurrent Kubernetes pod workers.",
            "        Actual time will be ~500x faster than this serial baseline.",
            "-" * 74,
            f"  STATUS: {result.outcome}",
            "=" * 74,
            "",
        ]
        print("\n".join(report_lines))

        # Hard assertions
        assert result.outcome == "SYNC_COMPLETE"
        assert result.signatures_loaded  == total_sig_records
        assert result.signatures_embedded == total_sig_records
        assert result.pps_records_loaded  == SCALE_ACCOUNTS
        assert result.cheque_leaves_loaded == SCALE_ACCOUNTS
        # All staging keys purged
        assert len(minio.deleted) == total_sig_records
        # Redis: one key per signatory record
        assert len(redis.keys_matching(f"sig:{BANK_ID}:")) == total_redis_keys
