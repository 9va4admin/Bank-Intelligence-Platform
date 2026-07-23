"""Tests for VaultSyncWorkflow and its five activities."""
import asyncio
import hashlib
import hmac
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.cts.workflows.vault_sync_workflow import (
    VaultSyncInput,
    VaultSyncWorkflow,
    VaultSyncResult,
    SignatureRecord,
    PPSRecord,
    load_signatures_from_cbs,
    embed_and_store_signatures,
    load_pps_from_cbs,
    warm_redis_vault,
    warm_redis_from_db,
    verify_vault_integrity,
    _hmac_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BANK_ID = "test-bank"
PEPPER = "test-pepper-xyz"
SYNC_DATE = "2026-06-18"
_DIM = 512


def _expected_key(prefix: str, account: str, suffix: str = "") -> str:
    digest = _hmac_key(PEPPER, BANK_ID, account)
    key = f"{prefix}:{BANK_ID}:{digest}"
    if suffix:
        key += f":{suffix}"
    return key


def _make_input():
    return VaultSyncInput(bank_id=BANK_ID, pepper=PEPPER, sync_date=SYNC_DATE)


def _unit_vec(dim: int = _DIM, axis: int = 0) -> list[float]:
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def _mock_embed_model(return_vector: list[float] = None) -> AsyncMock:
    model = AsyncMock()
    model.embed = AsyncMock(return_value=return_vector or _unit_vec())
    return model


def _mock_vault() -> AsyncMock:
    vault = AsyncMock()
    vault.store_embeddings = AsyncMock()
    return vault


def _make_redis() -> MagicMock:
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.execute.return_value = None
    redis.llen.return_value = 1
    return redis


def _make_cbs(accounts=3) -> AsyncMock:
    cbs = AsyncMock()
    cbs.list_signature_specimens.return_value = [
        {"account_number": f"ACC{i:03d}", "specimens": [b"s"]}
        for i in range(accounts)
    ]
    cbs.list_positive_pay_records.return_value = [
        {"account_number": f"ACC{i:03d}", "cheque_series_start": "100001",
         "amount": 1000.0, "payee": "Payee"}
        for i in range(accounts)
    ]
    return cbs


# ---------------------------------------------------------------------------
# VaultSyncInput
# ---------------------------------------------------------------------------

class TestVaultSyncInput:
    def test_requires_bank_id(self):
        with pytest.raises(Exception):
            VaultSyncInput(pepper=PEPPER, sync_date=SYNC_DATE)

    def test_requires_pepper(self):
        with pytest.raises(Exception):
            VaultSyncInput(bank_id=BANK_ID, sync_date=SYNC_DATE)

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.bank_id = "other"

    def test_workflow_id_is_deterministic(self):
        wf = VaultSyncWorkflow()
        assert wf.workflow_id(BANK_ID, SYNC_DATE) == f"cts-vaultsync-{BANK_ID}-{SYNC_DATE}"

    def test_workflow_id_includes_date_for_daily_idempotency(self):
        wf = VaultSyncWorkflow()
        id1 = wf.workflow_id(BANK_ID, "2026-06-18")
        id2 = wf.workflow_id(BANK_ID, "2026-06-19")
        assert id1 != id2


# ---------------------------------------------------------------------------
# load_signatures_from_cbs
# ---------------------------------------------------------------------------

class TestLoadSignaturesFromCBS:
    @pytest.mark.asyncio
    async def test_returns_signature_records(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": [b"sig_bytes"]},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 1
        assert records[0].account_number == "ACC001"

    @pytest.mark.asyncio
    async def test_skips_invalid_records_missing_account(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "", "specimens": [b"s"]},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_skips_records_with_no_specimens(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": []},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_cbs_unavailable_raises(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.side_effect = Exception("CBS down")
        with pytest.raises(Exception, match="CBS down"):
            await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)

    @pytest.mark.asyncio
    async def test_multiple_records(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": f"ACC{i:03d}", "specimens": [b"s"]}
            for i in range(5)
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 5


# ---------------------------------------------------------------------------
# embed_and_store_signatures (NEW)
# ---------------------------------------------------------------------------

class TestEmbedAndStoreSignatures:
    def _records(self, n: int = 3) -> list[SignatureRecord]:
        return [
            SignatureRecord(account_number=f"ACC{i:03d}", specimens=[b"s1", b"s2"])
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_embeds_all_specimens(self):
        vault = _mock_vault()
        model = _mock_embed_model()
        records = self._records(2)
        await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        # 2 accounts × 2 specimens = 4 embed calls
        assert model.embed.await_count == 4

    @pytest.mark.asyncio
    async def test_calls_store_embeddings_per_account(self):
        vault = _mock_vault()
        model = _mock_embed_model()
        records = self._records(3)
        result = await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        assert vault.store_embeddings.await_count == 3
        assert result["embedded"] == 3

    @pytest.mark.asyncio
    async def test_store_source_is_cbs(self):
        vault = _mock_vault()
        model = _mock_embed_model()
        records = [SignatureRecord(account_number="ACC001", specimens=[b"s"])]
        await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        _, call_kwargs = vault.store_embeddings.call_args
        assert call_kwargs.get("source") == "CBS" or vault.store_embeddings.call_args[0][2] == "CBS"

    @pytest.mark.asyncio
    async def test_skips_account_if_all_specimens_fail(self):
        vault = _mock_vault()
        model = AsyncMock()
        model.embed = AsyncMock(side_effect=Exception("model unavailable"))
        records = [SignatureRecord(account_number="ACC001", specimens=[b"s"])]
        result = await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        vault.store_embeddings.assert_not_awaited()
        assert result["failed"] == 1
        assert result["embedded"] == 0

    @pytest.mark.asyncio
    async def test_partial_failure_when_store_fails(self):
        vault = AsyncMock()
        vault.store_embeddings = AsyncMock(side_effect=Exception("DB down"))
        model = _mock_embed_model()
        records = [SignatureRecord(account_number="ACC001", specimens=[b"s"])]
        result = await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_skips_when_no_model(self):
        vault = _mock_vault()
        records = self._records(2)
        result = await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=None)
        vault.store_embeddings.assert_not_awaited()
        assert result["failed"] == 2

    @pytest.mark.asyncio
    async def test_skips_when_no_vault(self):
        model = _mock_embed_model()
        records = self._records(2)
        result = await embed_and_store_signatures(BANK_ID, records, vault=None, embedding_model=model)
        assert result["failed"] == 2

    @pytest.mark.asyncio
    async def test_empty_records_returns_zeros(self):
        result = await embed_and_store_signatures(BANK_ID, [], vault=_mock_vault(),
                                                  embedding_model=_mock_embed_model())
        assert result == {"embedded": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_partial_specimen_embed_partial_success(self):
        """First specimen fails embed, second succeeds → still stores with 1 vector."""
        vault = _mock_vault()
        model = AsyncMock()
        call_count = {"n": 0}

        async def _embed(raw, bank_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("GPU OOM")
            return _unit_vec()

        model.embed = AsyncMock(side_effect=_embed)
        records = [SignatureRecord(account_number="ACC001", specimens=[b"s1", b"s2"])]
        result = await embed_and_store_signatures(BANK_ID, records, vault=vault, embedding_model=model)
        vault.store_embeddings.assert_awaited_once()
        assert result["embedded"] == 1


# ---------------------------------------------------------------------------
# load_pps_from_cbs
# ---------------------------------------------------------------------------

class TestLoadPPSFromCBS:
    @pytest.mark.asyncio
    async def test_returns_pps_records(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001", "cheque_series_start": "100001",
             "amount": 50000.0, "payee": "Test Payee"},
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 1
        assert records[0].amount == 50000.0

    @pytest.mark.asyncio
    async def test_skips_incomplete_records(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001"},
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_cbs_unavailable_raises(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.side_effect = Exception("CBS timeout")
        with pytest.raises(Exception):
            await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)

    @pytest.mark.asyncio
    async def test_ttl_seconds_optional(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001", "cheque_series_start": "100001",
             "amount": 1000.0, "payee": "Payee", "ttl_seconds": 86400},
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records[0].ttl_seconds == 86400


# ---------------------------------------------------------------------------
# warm_redis_vault (PPS only)
# ---------------------------------------------------------------------------

class TestWarmRedisVault:
    @pytest.mark.asyncio
    async def test_writes_pps_keys(self):
        redis = _make_redis()
        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=50000.0, payee="Test"
        )]
        result = await warm_redis_vault(BANK_ID, PEPPER, pps_records, redis_client=redis)
        assert result["pps_records"] == 1

    @pytest.mark.asyncio
    async def test_pps_uses_hmac_key(self):
        redis = _make_redis()
        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=1.0, payee="P"
        )]
        await warm_redis_vault(BANK_ID, PEPPER, pps_records, redis_client=redis)
        pipe = redis.pipeline.return_value
        # hset was called with the correct key format
        assert pipe.hset.called
        call_key = pipe.hset.call_args[0][0]
        expected_digest = _hmac_key(PEPPER, BANK_ID, "ACC001")
        assert f"pps:{BANK_ID}:{expected_digest}:100001" == call_key

    @pytest.mark.asyncio
    async def test_returns_pps_count(self):
        redis = _make_redis()
        pps_records = [
            PPSRecord(account_number=f"ACC{i}", cheque_series_start="100",
                      amount=1.0, payee="P")
            for i in range(3)
        ]
        result = await warm_redis_vault(BANK_ID, PEPPER, pps_records, redis_client=redis)
        assert result["pps_records"] == 3

    @pytest.mark.asyncio
    async def test_pps_ttl_sets_expiry(self):
        redis = _make_redis()
        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=1.0, payee="P", ttl_seconds=3600
        )]
        await warm_redis_vault(BANK_ID, PEPPER, pps_records, redis_client=redis)
        assert redis.pipeline.return_value.expire.called

    @pytest.mark.asyncio
    async def test_no_pps_ttl_does_not_expire(self):
        redis = _make_redis()
        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=1.0, payee="P"
        )]
        await warm_redis_vault(BANK_ID, PEPPER, pps_records, redis_client=redis)
        redis.pipeline.return_value.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_pps_no_pipeline(self):
        redis = _make_redis()
        result = await warm_redis_vault(BANK_ID, PEPPER, [], redis_client=redis)
        assert result["pps_records"] == 0
        redis.pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# warm_redis_from_db (cold-restart recovery)
# ---------------------------------------------------------------------------

class TestWarmRedisFromDb:
    @pytest.mark.asyncio
    async def test_reads_db_and_writes_redis(self):
        from shared.ai.signature_embedding import pack_embedding
        v = [1.0] + [0.0] * 511
        packed = pack_embedding(v)

        db_pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"account_hash": "abc123", "specimen_index": 0, "embedding": packed},
        ])
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        redis = _make_redis()
        result = await warm_redis_from_db(BANK_ID, db_pool=db_pool, redis_client=redis)

        assert result["accounts"] == 1
        pipe = redis.pipeline.return_value
        assert pipe.delete.called
        assert pipe.rpush.called
        pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_groups_by_account_hash(self):
        from shared.ai.signature_embedding import pack_embedding
        v = [0.5] * 512
        packed = pack_embedding(v)

        db_pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"account_hash": "hash_A", "specimen_index": 0, "embedding": packed},
            {"account_hash": "hash_A", "specimen_index": 1, "embedding": packed},
            {"account_hash": "hash_B", "specimen_index": 0, "embedding": packed},
        ])
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        redis = _make_redis()
        result = await warm_redis_from_db(BANK_ID, db_pool=db_pool, redis_client=redis)

        assert result["accounts"] == 2
        pipe = redis.pipeline.return_value
        assert pipe.rpush.call_count == 3   # 2 for hash_A + 1 for hash_B

    @pytest.mark.asyncio
    async def test_skips_when_no_db_pool(self):
        redis = _make_redis()
        result = await warm_redis_from_db(BANK_ID, db_pool=None, redis_client=redis)
        assert result["accounts"] == 0
        redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_redis(self):
        db_pool = MagicMock()
        result = await warm_redis_from_db(BANK_ID, db_pool=db_pool, redis_client=None)
        assert result["accounts"] == 0


# ---------------------------------------------------------------------------
# verify_vault_integrity
# ---------------------------------------------------------------------------

class TestVerifyVaultIntegrity:
    @pytest.mark.asyncio
    async def test_passes_when_all_keys_present(self):
        redis = MagicMock()
        redis.llen.return_value = 2
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001", "ACC002"], redis_client=redis)
        assert passed is True

    @pytest.mark.asyncio
    async def test_fails_when_key_missing(self):
        redis = MagicMock()
        redis.llen.return_value = 0
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001"], redis_client=redis)
        assert passed is False

    @pytest.mark.asyncio
    async def test_fails_on_redis_error(self):
        redis = MagicMock()
        redis.llen.side_effect = Exception("Redis timeout")
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001"], redis_client=redis)
        assert passed is False

    @pytest.mark.asyncio
    async def test_empty_sample_passes(self):
        redis = MagicMock()
        passed = await verify_vault_integrity(BANK_ID, PEPPER, [], redis_client=redis)
        assert passed is True


# ---------------------------------------------------------------------------
# VaultSyncWorkflow.run_with_mocks (5-step orchestration)
# ---------------------------------------------------------------------------

class TestVaultSyncWorkflowOrchestration:
    @pytest.mark.asyncio
    async def test_sync_complete_outcome(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(),
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=["ACC000"],
        )
        assert result.outcome == "SYNC_COMPLETE"

    @pytest.mark.asyncio
    async def test_counts_signatures_loaded(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(accounts=5),
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=[],
        )
        assert result.signatures_loaded == 5

    @pytest.mark.asyncio
    async def test_counts_signatures_embedded(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(accounts=3),
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=[],
        )
        assert result.signatures_embedded == 3

    @pytest.mark.asyncio
    async def test_embedded_zero_when_no_model(self):
        """No embedding_model → embed step skips → signatures_embedded stays 0."""
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(accounts=2),
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=None,
            sample_accounts=[],
        )
        assert result.signatures_loaded == 2
        assert result.signatures_embedded == 0

    @pytest.mark.asyncio
    async def test_counts_pps_records(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(accounts=3),
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=[],
        )
        assert result.pps_records_loaded == 3

    @pytest.mark.asyncio
    async def test_integrity_check_passed(self):
        redis = _make_redis()
        redis.llen.return_value = 1
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(),
            redis_client=redis,
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=["ACC000"],
        )
        assert result.integrity_check_passed is True

    @pytest.mark.asyncio
    async def test_partial_failure_when_signature_load_fails(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.side_effect = Exception("CBS down")
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=cbs,
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
        )
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.signatures_loaded == 0

    @pytest.mark.asyncio
    async def test_partial_failure_when_pps_load_fails(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": [b"s"]}
        ]
        cbs.list_positive_pay_records.side_effect = Exception("PPS timeout")
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=cbs,
            redis_client=_make_redis(),
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
        )
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.pps_records_loaded == 0

    @pytest.mark.asyncio
    async def test_integrity_check_in_result(self):
        redis = _make_redis()
        redis.llen.return_value = 0   # all keys missing → integrity fails
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=_make_cbs(accounts=1),
            redis_client=redis,
            vault=_mock_vault(),
            embedding_model=_mock_embed_model(),
            sample_accounts=["ACC000"],
        )
        assert result.integrity_check_passed is False


# ---------------------------------------------------------------------------
# SignatureRecord Temporal round-trip
# ---------------------------------------------------------------------------

class TestSignatureRecordTemporalRoundTrip:
    def test_specimens_round_trip_through_default_payload_converter(self):
        from temporalio.converter import default

        conv = default().payload_converter
        records = [SignatureRecord(account_number="ACC001", specimens=[b"s1", b"s2"])]
        payloads = conv.to_payloads([records])
        restored = conv.from_payloads(payloads, [list[SignatureRecord]])
        assert restored[0][0].specimens == [b"s1", b"s2"]

    def test_direct_construction_unaffected(self):
        record = SignatureRecord(account_number="ACC001", specimens=[b"raw_bytes"])
        assert record.specimens == [b"raw_bytes"]
        assert isinstance(record.specimens[0], bytes)


# ---------------------------------------------------------------------------
# VaultSyncWorkflow real Temporal run (5 activities)
# ---------------------------------------------------------------------------

import uuid
from temporalio import activity as _activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


@_activity.defn(name="load_signatures_from_cbs")
async def _fake_load_signatures(bank_id: str) -> list[SignatureRecord]:
    return [SignatureRecord(account_number="ACC001", specimens=[b"s1"])]


@_activity.defn(name="embed_and_store_signatures")
async def _fake_embed_and_store(bank_id: str, signature_records: list[SignatureRecord]) -> dict:
    return {"embedded": len(signature_records), "failed": 0}


@_activity.defn(name="load_pps_from_cbs")
async def _fake_load_pps(bank_id: str) -> list[PPSRecord]:
    return [PPSRecord(account_number="ACC001", cheque_series_start="100001",
                      amount=500.0, payee="Payee")]


@_activity.defn(name="warm_redis_vault")
async def _fake_warm_redis(bank_id, pepper, pps_records) -> dict:
    return {"pps_records": len(pps_records)}


@_activity.defn(name="verify_vault_integrity")
async def _fake_verify_integrity(bank_id, pepper, sample_accounts) -> bool:
    return True


@_activity.defn(name="load_signatures_from_cbs")
async def _fake_load_signatures_fails(bank_id: str) -> list[SignatureRecord]:
    raise RuntimeError("CBS genuinely unreachable")


class TestVaultSyncWorkflowRealRun:
    @pytest.mark.asyncio
    async def test_real_run_dispatches_all_five_activities(self):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[VaultSyncWorkflow],
                activities=[
                    _fake_load_signatures, _fake_embed_and_store, _fake_load_pps,
                    _fake_warm_redis, _fake_verify_integrity,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    VaultSyncWorkflow.run,
                    _make_input(),
                    id=f"cts-vaultsync-{BANK_ID}-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "SYNC_COMPLETE"
        assert result.signatures_loaded == 1
        assert result.signatures_embedded == 1
        assert result.pps_records_loaded == 1
        assert result.integrity_check_passed is True

    @pytest.mark.asyncio
    async def test_real_run_partial_failure_when_signature_activity_raises(self):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[VaultSyncWorkflow],
                activities=[
                    _fake_load_signatures_fails, _fake_embed_and_store, _fake_load_pps,
                    _fake_warm_redis, _fake_verify_integrity,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    VaultSyncWorkflow.run,
                    _make_input(),
                    id=f"cts-vaultsync-{BANK_ID}-realfail-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "PARTIAL_FAILURE"


# ---------------------------------------------------------------------------
# register_vault_sync_schedule
# ---------------------------------------------------------------------------

class TestRegisterVaultSyncSchedule:
    @pytest.mark.asyncio
    async def test_fetches_pepper_before_creating_schedule(self):
        from modules.cts.workflows.vault_sync_workflow import register_vault_sync_schedule

        mock_temporal_client = MagicMock()
        mock_temporal_client.create_schedule = AsyncMock(return_value=None)

        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="scheduled-pepper-xyz"),
        ) as mock_get_secret:
            await register_vault_sync_schedule(mock_temporal_client, BANK_ID)

        mock_get_secret.assert_awaited_once_with("pii_hash_pepper")
        mock_temporal_client.create_schedule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_schedule_action_input_has_real_pepper(self):
        from modules.cts.workflows.vault_sync_workflow import register_vault_sync_schedule

        mock_temporal_client = MagicMock()
        mock_temporal_client.create_schedule = AsyncMock(return_value=None)

        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="scheduled-pepper-xyz"),
        ):
            await register_vault_sync_schedule(mock_temporal_client, BANK_ID)

        schedule = mock_temporal_client.create_schedule.call_args.args[1]
        vault_sync_input = schedule.action.args[0]
        assert vault_sync_input.pepper == "scheduled-pepper-xyz"
        assert vault_sync_input.bank_id == BANK_ID
        assert vault_sync_input.triggered_by == "SCHEDULED"

    @pytest.mark.asyncio
    async def test_propagates_when_pepper_unavailable(self):
        from modules.cts.workflows.vault_sync_workflow import register_vault_sync_schedule

        mock_temporal_client = MagicMock()
        mock_temporal_client.create_schedule = AsyncMock(return_value=None)

        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(side_effect=Exception("Vault unreachable")),
        ):
            with pytest.raises(Exception, match="Vault unreachable"):
                await register_vault_sync_schedule(mock_temporal_client, BANK_ID)

        mock_temporal_client.create_schedule.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_exists_error_is_swallowed(self):
        from modules.cts.workflows.vault_sync_workflow import register_vault_sync_schedule

        mock_temporal_client = MagicMock()
        mock_temporal_client.create_schedule = AsyncMock(
            side_effect=Exception("Schedule already exists")
        )

        with patch(
            "shared.config.config_service.config_service.get_secret",
            new=AsyncMock(return_value="scheduled-pepper-xyz"),
        ):
            await register_vault_sync_schedule(mock_temporal_client, BANK_ID)  # must not raise
