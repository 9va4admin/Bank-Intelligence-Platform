"""
SignatureVault — per-signatory two-tier store for cheque signature embeddings.

Tier 1 (hot):  Redis Cluster — sub-millisecond lookup during clearing window.
               Key: sig:{bank_id}:{hmac_sha256(bank_id:account_number)}:{signatory_id}
               Value: Redis list of packed float32 embeddings (2048 bytes each).
               One key per signatory — specimens for different signatories never mixed.

Tier 2 (durable): YugabyteDB cts.signature_embeddings
               Indexed by (bank_id, account_hash, signatory_id, specimen_index).
               Source of truth. Survives Redis restart.
               VaultSyncWorkflow warms Redis from here — no re-embedding from CBS.

Mandate rules: cts.account_signatories
               ANY_ONE       — any one signatory match satisfies (retail default)
               ALL_REQUIRED  — every registered signatory must match (joint accounts)
               QUORUM_N      — N signatories must match (corporate)

Primary read path (new code must use this):
  get_specimens_by_signatory(account, bank_id)
    → dict[signatory_id, list[list[float]]]  — empty dict on complete miss
  get_mandate_rule(account, bank_id) → str

Write path:
  store_embeddings(account, embeddings, signatory_id, source)

Backward-compat read path (used by older callers):
  get_signatures(account, bank_id) → VaultResult
    Aggregates all signatories as a flat list.
    Preserves VAULT_ERROR distinction for Redis failures on the PRIMARY key.

Vault miss / error ALWAYS routes to HUMAN_REVIEW. Never AUTO_RETURN.
Raw account numbers NEVER appear in Redis keys, cache keys, or DB columns.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

import structlog

from shared.ai.signature_embedding import pack_embedding, unpack_embedding

log = structlog.get_logger()

_DEFAULT_MANDATE = "ANY_ONE"


@dataclass(frozen=True)
class VaultResult:
    outcome: str                       # "FOUND" | "HUMAN_REVIEW"
    embeddings: list[list[float]]      # flat list of 512-dim vectors; empty on miss
    miss_reason: Optional[str] = None  # "VAULT_MISS" | "VAULT_ERROR" | None


class SignatureVault:
    def __init__(self, bank_id: str, pepper: str, db_pool=None) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._redis = None
        self._db_pool = db_pool
        self._ready = False
        # Cache keyed by sig:{bank_id}:{hmac}:{signatory_id}
        self._cache: dict[str, list[list[float]]] = {}
        # Mandate rule cache keyed by account_hash
        self._mandate_cache: dict[str, str] = {}

    def connect(self, redis_client=None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis  # type: ignore[import]
            self._redis = redis.Redis()
        self._ready = True

    # ------------------------------------------------------------------
    # Key / hash helpers
    # ------------------------------------------------------------------

    def _account_hash(self, account_number: str) -> str:
        """HMAC-SHA256 of account number — never stored raw anywhere."""
        return hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _make_key(self, account_number: str, signatory_id: str = "PRIMARY") -> str:
        """Redis key: sig:{bank_id}:{hmac}:{signatory_id}"""
        return f"sig:{self._bank_id}:{self._account_hash(account_number)}:{signatory_id}"

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "SignatureVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    # ------------------------------------------------------------------
    # Primary read path — per-signatory (use this in all new code)
    # ------------------------------------------------------------------

    async def get_specimens_by_signatory(
        self, account_number: str, bank_id: str
    ) -> dict[str, list[list[float]]]:
        """
        Return all specimens grouped by signatory_id.

        Priority per signatory: process cache → Redis → YugabyteDB.
        Redis errors for individual signatories are logged and skipped
        (the signatory is absent from the result rather than crashing).

        Returns empty dict if no signatories found at all — callers treat
        this as a vault miss and trigger CBS fallback or HUMAN_REVIEW.
        Never raises.
        """
        self._assert_ready()
        acct_hash = self._account_hash(account_number)

        signatory_ids = await self._load_signatory_ids(acct_hash)
        if not signatory_ids:
            # Single-signatory fallback: try PRIMARY (covers pre-migration data
            # and accounts that haven't been enrolled into account_signatories yet)
            signatory_ids = ["PRIMARY"]

        result: dict[str, list[list[float]]] = {}

        for sig_id in signatory_ids:
            key = self._make_key(account_number, sig_id)

            # 1. Process-local cache
            if key in self._cache:
                result[sig_id] = self._cache[key]
                continue

            # 2. Redis
            try:
                raw_list = self._redis.lrange(key, 0, -1)
            except Exception as exc:
                log.warning(
                    "signature_vault.redis_error",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                    signatory_id=sig_id,
                    error=str(exc),
                )
                continue  # skip this signatory; others may still succeed

            if raw_list:
                embeddings = [unpack_embedding(b) for b in raw_list]
                self._cache[key] = embeddings
                result[sig_id] = embeddings
                continue

            # 3. YugabyteDB fallback
            if self._db_pool is not None:
                try:
                    embeddings = await self._load_signatory_from_db(acct_hash, sig_id)
                except Exception as exc:
                    log.warning(
                        "signature_vault.db_error",
                        account_last4=account_number[-4:],
                        signatory_id=sig_id,
                        error=str(exc),
                    )
                    continue

                if embeddings:
                    self._backfill_redis(key, embeddings)
                    self._cache[key] = embeddings
                    result[sig_id] = embeddings
                    log.info(
                        "signature_vault.db_hit_redis_backfilled",
                        account_last4=account_number[-4:],
                        bank_id=bank_id,
                        signatory_id=sig_id,
                        specimen_count=len(embeddings),
                    )

        return result

    async def get_mandate_rule(self, account_number: str, bank_id: str) -> str:
        """
        Return the mandate rule for the account from cts.account_signatories.

        Falls back to ANY_ONE when:
          - no DB pool (dev / test without DB)
          - account not yet enrolled in account_signatories (pre-migration)
          - DB error
        """
        acct_hash = self._account_hash(account_number)

        if acct_hash in self._mandate_cache:
            return self._mandate_cache[acct_hash]

        if self._db_pool is None:
            return _DEFAULT_MANDATE

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT mandate_rule, quorum_n
                    FROM cts.account_signatories
                    WHERE bank_id = $1 AND account_hash = $2 AND is_active = TRUE
                    LIMIT 1
                    """,
                    self._bank_id,
                    acct_hash,
                )
        except Exception as exc:
            log.warning(
                "signature_vault.mandate_fetch_error",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            return _DEFAULT_MANDATE

        if row is None:
            return _DEFAULT_MANDATE

        rule = row["mandate_rule"]
        if rule in ("ANY_ONE", "ALL_REQUIRED"):
            resolved = rule
        else:
            # QUORUM_N_OF_M stored in DB → simplified to QUORUM_{n}
            n = row["quorum_n"] or 1
            resolved = f"QUORUM_{n}"

        self._mandate_cache[acct_hash] = resolved
        return resolved

    # ------------------------------------------------------------------
    # Backward-compat read (aggregates all signatories as flat list)
    # ------------------------------------------------------------------

    async def get_signatures(self, account_number: str, bank_id: str) -> VaultResult:
        """
        Backward-compat method — aggregates all signatory specimens as a flat list.

        Prefer get_specimens_by_signatory() for all new code.

        Preserves the VAULT_ERROR / VAULT_MISS distinction for the PRIMARY
        signatory key so existing monitoring and test assertions remain valid.
        """
        self._assert_ready()

        # --- Primary key check (preserves VAULT_ERROR for Redis failures) ---
        primary_key = self._make_key(account_number, "PRIMARY")

        if primary_key in self._cache:
            return VaultResult(outcome="FOUND", embeddings=self._cache[primary_key])

        try:
            raw_list = self._redis.lrange(primary_key, 0, -1)
        except Exception as exc:
            log.warning(
                "signature_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_ERROR")

        if raw_list:
            embeddings = [unpack_embedding(b) for b in raw_list]
            self._cache[primary_key] = embeddings
            # Also try to get other signatories and aggregate
            try:
                all_specimens = await self.get_specimens_by_signatory(account_number, bank_id)
                all_embs = [emb for embs in all_specimens.values() for emb in embs]
                return VaultResult(outcome="FOUND", embeddings=all_embs if all_embs else embeddings)
            except Exception:
                return VaultResult(outcome="FOUND", embeddings=embeddings)

        # --- No data in Redis PRIMARY key — try full per-signatory path ---
        acct_hash = self._account_hash(account_number)
        if self._db_pool is not None:
            try:
                embeddings = await self._load_signatory_from_db(acct_hash, "PRIMARY")
            except Exception as exc:
                log.warning(
                    "signature_vault.db_error",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                    error=str(exc),
                )
                return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_ERROR")

            if embeddings:
                self._backfill_redis(primary_key, embeddings)
                self._cache[primary_key] = embeddings
                log.info(
                    "signature_vault.db_hit_redis_backfilled",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                    specimen_count=len(embeddings),
                )
                return VaultResult(outcome="FOUND", embeddings=embeddings)

        log.info(
            "signature_vault.miss",
            account_last4=account_number[-4:],
            bank_id=bank_id,
        )
        return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_MISS")

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def store_embeddings(
        self,
        account_number: str,
        embeddings: list[list[float]],
        signatory_id: str = "PRIMARY",
        source: str = "CBS",
    ) -> None:
        """
        Persist embeddings for one signatory — YugabyteDB first, then Redis.

        Args:
            account_number: raw account number (hashed internally, never stored)
            embeddings:     list of 512-dim float32 vectors (specimens for this signatory)
            signatory_id:   which signatory these specimens belong to
            source:         'CBS' or 'CBS_FALLBACK'
        """
        self._assert_ready()
        key = self._make_key(account_number, signatory_id)
        acct_hash = self._account_hash(account_number)

        self._cache.pop(key, None)

        if self._db_pool is not None:
            try:
                async with self._db_pool.acquire() as conn:
                    async with conn.transaction():
                        for idx, emb in enumerate(embeddings):
                            await conn.execute(
                                """
                                INSERT INTO cts.signature_embeddings
                                    (bank_id, account_hash, signatory_id, specimen_index,
                                     embedding, source)
                                VALUES ($1, $2, $3, $4, $5, $6)
                                ON CONFLICT (bank_id, account_hash, signatory_id, specimen_index)
                                DO UPDATE SET
                                    embedding  = EXCLUDED.embedding,
                                    source     = EXCLUDED.source,
                                    updated_at = now()
                                """,
                                self._bank_id,
                                acct_hash,
                                signatory_id,
                                idx,
                                pack_embedding(emb),
                                source,
                            )
            except Exception as exc:
                log.error(
                    "signature_vault.db_store_failed",
                    account_last4=account_number[-4:],
                    signatory_id=signatory_id,
                    bank_id=self._bank_id,
                    error=str(exc),
                )
                raise

        try:
            pipe = self._redis.pipeline()
            pipe.delete(key)
            for emb in embeddings:
                pipe.rpush(key, pack_embedding(emb))
            pipe.execute()
        except Exception as exc:
            log.warning(
                "signature_vault.redis_store_failed",
                account_last4=account_number[-4:],
                signatory_id=signatory_id,
                bank_id=self._bank_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_signatory_ids(self, account_hash: str) -> list[str]:
        """Load active signatory_ids from cts.account_signatories. Empty list if none."""
        if self._db_pool is None:
            return []
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT signatory_id FROM cts.account_signatories
                    WHERE bank_id = $1 AND account_hash = $2 AND is_active = TRUE
                    ORDER BY created_at
                    """,
                    self._bank_id,
                    account_hash,
                )
            return [r["signatory_id"] for r in rows]
        except Exception as exc:
            log.warning("signature_vault.signatory_ids_fetch_error", error=str(exc))
            return []

    async def _load_signatory_from_db(
        self, account_hash: str, signatory_id: str
    ) -> list[list[float]]:
        """Load all specimens for one signatory from YugabyteDB, ordered by specimen_index."""
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT embedding FROM cts.signature_embeddings
                WHERE bank_id = $1 AND account_hash = $2 AND signatory_id = $3
                ORDER BY specimen_index
                """,
                self._bank_id,
                account_hash,
                signatory_id,
            )
        return [unpack_embedding(bytes(row["embedding"])) for row in rows]

    def _backfill_redis(self, key: str, embeddings: list[list[float]]) -> None:
        try:
            pipe = self._redis.pipeline()
            pipe.delete(key)
            for emb in embeddings:
                pipe.rpush(key, pack_embedding(emb))
            pipe.execute()
        except Exception as exc:
            log.warning("signature_vault.redis_backfill_failed", key=key[:60], error=str(exc))
