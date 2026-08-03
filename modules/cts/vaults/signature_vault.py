"""
SignatureVault — two-tier store for cheque signature embeddings.

Tier 1 (hot):  Redis Cluster  — sub-millisecond lookup during clearing window.
               Key:  sig:{bank_id}:{hmac_sha256(bank_id:account_number)}
               Value: Redis list of packed float32 embeddings (2048 bytes each).

Tier 2 (durable): YugabyteDB cts.signature_embeddings
               Source of truth.  Survives Redis restart.  VaultSyncWorkflow
               warms Redis from here — no re-embedding from CBS required.

Read path:
  1. In-memory process cache (per-request cache-aside, invalidated on write)
  2. Redis  → unpack float32 bytes → return
  3. YugabyteDB → backfill Redis → return
  4. Miss everywhere → HUMAN_REVIEW (NEVER AUTO_RETURN)

Write path (store_embeddings):
  1. Upsert to YugabyteDB  (durable first)
  2. Write packed bytes to Redis
  3. Invalidate local cache

Key format: sig:{bank_id}:{hmac_sha256(bank_id:account_number)}
Raw account numbers NEVER appear as Redis keys or in the local cache.

Vault miss / Redis error / DB error ALWAYS routes to HUMAN_REVIEW.
AUTO_RETURN is never a valid outcome from this vault.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Optional

import structlog

from shared.ai.signature_embedding import pack_embedding, unpack_embedding

log = structlog.get_logger()


@dataclass(frozen=True)
class VaultResult:
    outcome: str                       # "FOUND" | "HUMAN_REVIEW"
    embeddings: list[list[float]]      # 512-dim vectors; empty on miss
    miss_reason: Optional[str] = None  # "VAULT_MISS" | "VAULT_ERROR" | None


class SignatureVault:
    def __init__(self, bank_id: str, pepper: str, db_pool=None) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._redis = None
        self._db_pool = db_pool   # asyncpg pool; None in bare local dev / some tests
        self._ready = False
        self._cache: dict[str, list[list[float]]] = {}

    def connect(self, redis_client=None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis  # type: ignore[import]
            self._redis = redis.Redis()
        self._ready = True

    def _make_key(self, account_number: str) -> str:
        digest = hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"sig:{self._bank_id}:{digest}"

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "SignatureVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def get_signatures(self, account_number: str, bank_id: str) -> VaultResult:
        self._assert_ready()
        key = self._make_key(account_number)

        # 1. Process-local cache
        if key in self._cache:
            return VaultResult(outcome="FOUND", embeddings=self._cache[key])

        # 2. Redis
        try:
            raw_list = self._redis.lrange(key, 0, -1)
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
            self._cache[key] = embeddings
            return VaultResult(outcome="FOUND", embeddings=embeddings)

        # 3. YugabyteDB fallback (when db_pool is wired)
        if self._db_pool is not None:
            try:
                embeddings = await self._load_from_db(account_number, key)
            except Exception as exc:
                log.warning(
                    "signature_vault.db_error",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                    error=str(exc),
                )
                return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_ERROR")

            if embeddings:
                self._backfill_redis(key, embeddings)
                self._cache[key] = embeddings
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

    async def _load_from_db(self, account_number: str, key: str) -> list[list[float]]:
        account_hash = key.split(":")[-1]
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT embedding
                FROM cts.signature_embeddings
                WHERE bank_id = $1 AND account_hash = $2
                ORDER BY specimen_index
                """,
                self._bank_id,
                account_hash,
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
            log.warning("signature_vault.redis_backfill_failed", key=key[:30], error=str(exc))

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def store_embeddings(
        self,
        account_number: str,
        embeddings: list[list[float]],
        source: str = "CBS",
    ) -> None:
        """
        Persist embeddings durably (YugabyteDB first, then Redis).
        Invalidates the local process cache.

        Args:
            account_number: raw account number (hashed internally, never stored)
            embeddings:     list of 512-dim float32 vectors (up to 3 specimens)
            source:         'CBS' or 'CBS_FALLBACK'
        """
        self._assert_ready()
        key = self._make_key(account_number)
        account_hash = key.split(":")[-1]

        self._cache.pop(key, None)

        # 1. YugabyteDB upsert (durable)
        if self._db_pool is not None:
            try:
                async with self._db_pool.acquire() as conn:
                    async with conn.transaction():
                        for idx, emb in enumerate(embeddings):
                            await conn.execute(
                                """
                                INSERT INTO cts.signature_embeddings
                                    (bank_id, account_hash, specimen_index, embedding, source)
                                VALUES ($1, $2, $3, $4, $5)
                                ON CONFLICT (bank_id, account_hash, specimen_index)
                                DO UPDATE SET
                                    embedding  = EXCLUDED.embedding,
                                    source     = EXCLUDED.source,
                                    updated_at = now()
                                """,
                                self._bank_id,
                                account_hash,
                                idx,
                                pack_embedding(emb),
                                source,
                            )
            except Exception as exc:
                log.error(
                    "signature_vault.db_store_failed",
                    account_last4=account_number[-4:],
                    bank_id=self._bank_id,
                    error=str(exc),
                )
                raise

        # 2. Redis write
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
                bank_id=self._bank_id,
                error=str(exc),
            )
