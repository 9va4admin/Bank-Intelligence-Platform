"""
SignatoryRegistry — Redis cache + PostgreSQL source of truth for signatory embeddings.

Redis key:  msv:{bank_id}:{account_hash}:{signatory_id}
Redis value: Redis list, each item is numpy float32 tobytes() of one specimen embedding
Redis TTL:  none (refreshed on enrollment; evicted by allkeys-lru policy)

Write path: PostgreSQL first, then Redis (dual-write).
  - If PostgreSQL fails → raise immediately; Redis is NOT written.
  - If Redis fails after PostgreSQL → log warning; embedding is still durably stored.

Read path: Redis first → on miss or error → PostgreSQL → warm Redis → return.

ACCOUNT NUMBER IS NEVER STORED.
The `load` / `store` / `revoke` public methods accept `account_hash` (pre-hashed by caller).
The `_hash_account` async method and `_hash_account_sync` helper are provided for callers
that need to hash before calling (e.g. the Orchestrator which has the raw account_number).
"""
import hashlib
import hmac
import struct

import numpy as np
import structlog
from opentelemetry import trace

from modules.msv.mandates.models import SignatoryRecord

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.vault")

_EMBEDDING_DIM = 512
_FLOAT32_BYTES = 4
_SPECIMEN_BYTE_SIZE = _EMBEDDING_DIM * _FLOAT32_BYTES


def _embedding_to_bytes(emb: list[float]) -> bytes:
    return np.array(emb, dtype=np.float32).tobytes()


def _bytes_to_embedding(b: bytes) -> list[float]:
    return np.frombuffer(b, dtype=np.float32).tolist()


class SignatoryRegistry:
    """
    Redis-backed cache with PostgreSQL as source of truth.

    Args:
        redis_client:   async Redis client (redis.asyncio or compatible mock)
        db_pool:        asyncpg connection pool
        config_service: for fetching bank-specific PII hash pepper from Vault
    """

    def __init__(self, redis_client, db_pool, config_service) -> None:
        self._redis = redis_client
        self._db = db_pool
        self._cfg = config_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store(
        self,
        bank_id: str,
        account_hash: str,
        signatory_id: str,
        specimen_idx: int,
        embedding: list[float],
        operation_type: str,
    ) -> None:
        """
        Write one specimen embedding.

        PostgreSQL is written first (durable). Redis is updated after.
        Raises on PostgreSQL failure — caller must not proceed with Redis update.
        """
        with tracer.start_as_current_span("msv.vault.store") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("signatory_id", signatory_id)
            span.set_attribute("specimen_idx", specimen_idx)

            emb_bytes = _embedding_to_bytes(embedding)

            # PostgreSQL first — must succeed before Redis
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO msv.signatory_embeddings
                        (bank_id, account_hash, signatory_id, specimen_idx,
                         embedding, operation_type)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (bank_id, account_hash, signatory_id, specimen_idx)
                    DO UPDATE SET embedding = EXCLUDED.embedding,
                                  operation_type = EXCLUDED.operation_type,
                                  enrolled_at = NOW(),
                                  revoked_at = NULL
                    """,
                    bank_id,
                    account_hash,
                    signatory_id,
                    specimen_idx,
                    emb_bytes,
                    operation_type,
                )

            log.info(
                "msv.vault.stored_postgres",
                bank_id=bank_id,
                signatory_id=signatory_id,
                specimen_idx=specimen_idx,
            )

            # Redis update (best-effort)
            try:
                redis_key = self._redis_key(bank_id, account_hash, signatory_id)
                await self._redis.lpush(redis_key, emb_bytes)
                log.info(
                    "msv.vault.redis_updated",
                    bank_id=bank_id,
                    signatory_id=signatory_id,
                )
            except Exception as exc:
                log.warning(
                    "msv.vault.redis_write_failed",
                    bank_id=bank_id,
                    signatory_id=signatory_id,
                    error=str(exc),
                )

    async def load(
        self,
        bank_id: str,
        account_hash: str,
        signatory_id: str,
    ) -> list[list[float]]:
        """
        Return list of specimen embeddings for a signatory.

        Redis first; on miss or error → PostgreSQL → warm Redis → return.
        Returns empty list if not enrolled.
        """
        with tracer.start_as_current_span("msv.vault.load") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("signatory_id", signatory_id)

            redis_key = self._redis_key(bank_id, account_hash, signatory_id)

            # Try Redis first
            try:
                raw_items: list[bytes] = await self._redis.lrange(redis_key, 0, -1)
                if raw_items:
                    embeddings = [_bytes_to_embedding(b) for b in raw_items]
                    span.set_attribute("cache_hit", True)
                    span.set_attribute("specimen_count", len(embeddings))
                    return embeddings
            except Exception as exc:
                log.warning(
                    "msv.vault.redis_read_failed",
                    bank_id=bank_id,
                    signatory_id=signatory_id,
                    error=str(exc),
                )

            # PostgreSQL fallback
            span.set_attribute("cache_hit", False)
            embeddings = await self._load_from_postgres(bank_id, account_hash, signatory_id)

            # Warm Redis (best-effort)
            if embeddings:
                try:
                    emb_bytes_list = [_embedding_to_bytes(e) for e in embeddings]
                    await self._redis.lpush(redis_key, *emb_bytes_list)
                except Exception as exc:
                    log.warning(
                        "msv.vault.redis_warm_failed",
                        bank_id=bank_id,
                        signatory_id=signatory_id,
                        error=str(exc),
                    )

            span.set_attribute("specimen_count", len(embeddings))
            return embeddings

    async def load_all_signatories(
        self,
        bank_id: str,
        account_hash: str,
    ) -> list[SignatoryRecord]:
        """
        Return all SignatoryRecord for an account (from PostgreSQL manifest + embeddings).
        Warms Redis for each signatory loaded.
        """
        with tracer.start_as_current_span("msv.vault.load_all") as span:
            span.set_attribute("bank_id", bank_id)

            async with self._db.acquire() as conn:
                manifest_rows = await conn.fetch(
                    """
                    SELECT signatory_id, role, name_masked, specimen_count
                    FROM msv.signatory_manifest
                    WHERE bank_id = $1 AND account_hash = $2
                    """,
                    bank_id,
                    account_hash,
                )

            signatories: list[SignatoryRecord] = []
            for row in manifest_rows:
                sig_id = row["signatory_id"]
                embeddings = await self.load(bank_id, account_hash, sig_id)
                signatories.append(
                    SignatoryRecord(
                        signatory_id=sig_id,
                        role=row["role"],
                        name_masked=row["name_masked"],
                        specimen_count=row["specimen_count"],
                        embeddings=embeddings,
                    )
                )

            span.set_attribute("signatory_count", len(signatories))
            return signatories

    async def revoke(
        self,
        bank_id: str,
        account_hash: str,
        signatory_id: str,
    ) -> None:
        """
        Delete a signatory's embeddings from PostgreSQL and Redis.
        Used for revocation file processing.
        """
        with tracer.start_as_current_span("msv.vault.revoke") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("signatory_id", signatory_id)

            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE msv.signatory_embeddings
                    SET revoked_at = NOW()
                    WHERE bank_id = $1 AND account_hash = $2 AND signatory_id = $3
                    """,
                    bank_id,
                    account_hash,
                    signatory_id,
                )

            log.info(
                "msv.vault.revoked_postgres",
                bank_id=bank_id,
                signatory_id=signatory_id,
            )

            # Remove from Redis
            try:
                redis_key = self._redis_key(bank_id, account_hash, signatory_id)
                # Also scan for pattern to handle any related keys
                pattern = f"msv:{bank_id}:{account_hash}:{signatory_id}*"
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
                else:
                    await self._redis.delete(redis_key)
            except Exception as exc:
                log.warning(
                    "msv.vault.redis_revoke_failed",
                    bank_id=bank_id,
                    signatory_id=signatory_id,
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Hashing helpers
    # ------------------------------------------------------------------

    async def _hash_account(self, account_number: str, bank_id: str) -> str:
        """
        HMAC-SHA256 hash of account number with bank-specific pepper from Vault.
        Never call with raw account number in any key, log, or DB write.
        """
        pepper = await self._cfg.get_secret(f"banks.{bank_id}.pii_hash_pepper")
        return self._hash_account_sync(account_number, bank_id, pepper=pepper)

    def _hash_account_sync(
        self,
        account_number: str,
        bank_id: str,
        pepper: str = "",
    ) -> str:
        """
        Synchronous variant for tests that inject the pepper directly.
        In production code always call the async `_hash_account`.
        """
        return hmac.new(
            pepper.encode() if pepper else b"",
            f"{bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _redis_key(self, bank_id: str, account_hash: str, signatory_id: str) -> str:
        """Redis key format: msv:{bank_id}:{account_hash}:{signatory_id}"""
        return f"msv:{bank_id}:{account_hash}:{signatory_id}"

    async def _load_from_postgres(
        self,
        bank_id: str,
        account_hash: str,
        signatory_id: str,
    ) -> list[list[float]]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT specimen_idx, embedding
                FROM msv.signatory_embeddings
                WHERE bank_id = $1 AND account_hash = $2 AND signatory_id = $3
                  AND revoked_at IS NULL
                ORDER BY specimen_idx ASC
                """,
                bank_id,
                account_hash,
                signatory_id,
            )
        return [_bytes_to_embedding(row["embedding"]) for row in rows]
