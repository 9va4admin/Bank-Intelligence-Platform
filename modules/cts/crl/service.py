"""
CRL — Cheque Routing Layer Service.

Resolves IFSC (or MICR code) → Branch → ProcessingUnit. The result drives:
  - Which Temporal task queue to use: cts-processing-{bank_id}-{pu_id}
  - Which Kafka topic to publish inward cheques to: cts.inward.{bank_id}.{pu_id}
  - Which KEDA-scaled worker pool processes the cheque

Resolution order:
  1. Redis cache (key: crl:{ifsc_code}) — hot path, <1ms
  2. YugabyteDB join (branches ⋈ processing_units) — cache miss
  3. Cache the result in Redis with configurable TTL (default: 5 minutes)

Cache invalidation:
  - Admin remaps a branch to a different PU → Kafka cts.crl.invalidated event
  - handle_invalidation_event() busts the relevant cache keys
  - Kafka consumer in cts worker calls this on every invalidation event

MICR lookup:
  - resolve_micr() looks up IFSC from a Redis micr:{micr_code} secondary index
  - Falls back to DB fetchval for MICR → IFSC mapping if the secondary index misses
  - Then delegates to resolve_ifsc() for the main resolution

Design note: CRLService takes injected redis and db clients so it can be used both
inside Temporal activities (injected at worker startup) and in the gRPC server
(Phase 2). No global singletons.
"""
from __future__ import annotations

import json
import structlog
from dataclasses import asdict, dataclass
from typing import Any, Optional

log = structlog.get_logger()


# ── Cache key helper ──────────────────────────────────────────────────────────

def crl_cache_key(ifsc_code: str) -> str:
    return f"crl:{ifsc_code}"


def _micr_cache_key(micr_code: str) -> str:
    return f"crl_micr:{micr_code}"


# ── Value object ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BranchResolution:
    """Immutable result of a CRL lookup. Contains everything needed to route a cheque."""

    branch_id:            str
    bank_id:              str
    pu_id:                str
    ifsc_code:            str
    micr_code:            str
    clearing_zone:        str
    temporal_task_queue:  str   # cts-processing-{bank_id}-{pu_id}
    kafka_inward_topic:   str   # cts.inward.{bank_id}.{pu_id}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BranchResolution":
        return cls(
            branch_id=d["branch_id"],
            bank_id=d["bank_id"],
            pu_id=d["pu_id"],
            ifsc_code=d["ifsc_code"],
            micr_code=d["micr_code"],
            clearing_zone=d["clearing_zone"],
            temporal_task_queue=d["temporal_task_queue"],
            kafka_inward_topic=d["kafka_inward_topic"],
        )

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "BranchResolution":
        """Build from a YugabyteDB row that joins branches + processing_units."""
        bank_id  = row["bank_id"]
        pu_id    = row["pu_id"]
        return cls(
            branch_id=row["branch_id"],
            bank_id=bank_id,
            pu_id=pu_id,
            ifsc_code=row["branch_ifsc"],
            micr_code=row.get("micr_code", ""),
            clearing_zone=row["clearing_zone"],
            temporal_task_queue=row.get(
                "temporal_task_queue",
                f"cts-processing-{bank_id}-{pu_id}",
            ),
            kafka_inward_topic=row.get(
                "kafka_inward_topic",
                f"cts.inward.{bank_id}.{pu_id}",
            ),
        )


# ── Exception ─────────────────────────────────────────────────────────────────

class BranchNotFoundError(Exception):
    """Raised when the IFSC is not found in either Redis or YugabyteDB."""


# ── SQL ───────────────────────────────────────────────────────────────────────

_RESOLVE_IFSC_SQL = """
SELECT
    b.branch_id,
    b.bank_id,
    b.branch_ifsc,
    b.micr_code,
    p.pu_id,
    p.clearing_zone,
    p.temporal_task_queue,
    p.kafka_inward_topic
FROM cts.branches b
JOIN cts.processing_units p ON p.pu_id = b.pu_id
WHERE b.branch_ifsc = $1
  AND b.is_active = true
  AND p.is_active = true
LIMIT 1
"""

_RESOLVE_MICR_SQL = """
SELECT b.branch_ifsc
FROM cts.branches b
WHERE b.micr_code = $1
  AND b.is_active = true
LIMIT 1
"""


# ── Service ───────────────────────────────────────────────────────────────────

class CRLService:
    """
    Cheque Routing Layer — resolves IFSC/MICR → BranchResolution.

    Args:
        redis:             Async Redis client (aioredis or redis-py asyncio).
        db:                Async DB connection/pool (asyncpg).
        cache_ttl_seconds: How long to cache a resolution (default 5 min).
    """

    def __init__(self, *, redis: Any, db: Any, cache_ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._db = db
        self._ttl = cache_ttl_seconds

    # ── Public: resolve ───────────────────────────────────────────────────────

    async def resolve_ifsc(self, ifsc_code: str) -> BranchResolution:
        """
        Resolve IFSC code → BranchResolution.

        1. Redis cache hit → return immediately.
        2. Cache miss → query DB → cache result → return.
        3. DB miss → raise BranchNotFoundError.
        """
        key = crl_cache_key(ifsc_code)

        # 1. Cache hit
        cached = await self._redis.get(key)
        if cached is not None:
            return BranchResolution.from_dict(json.loads(cached))

        # 2. DB lookup
        row = await self._db.fetchrow(_RESOLVE_IFSC_SQL, ifsc_code)
        if row is None:
            raise BranchNotFoundError(
                f"No active branch found for IFSC {ifsc_code!r}. "
                f"Ensure the branch is registered in cts.branches and mapped to an active PU."
            )

        resolution = BranchResolution.from_db_row(dict(row))

        # 3. Populate cache
        await self._redis.set(key, json.dumps(resolution.to_dict()), ex=self._ttl)

        log.info(
            "crl.resolved",
            ifsc_code=ifsc_code,
            branch_id=resolution.branch_id,
            pu_id=resolution.pu_id,
            source="db",
        )
        return resolution

    async def resolve_micr(self, micr_code: str) -> BranchResolution:
        """
        Resolve MICR code → BranchResolution.

        Checks a secondary Redis index (crl_micr:{micr_code} → ifsc_code) first,
        falls back to DB lookup for the IFSC, then delegates to resolve_ifsc().
        """
        micr_key = _micr_cache_key(micr_code)

        # 1. MICR secondary index in Redis
        cached_ifsc = await self._redis.get(micr_key)
        if cached_ifsc is not None:
            return await self.resolve_ifsc(cached_ifsc)

        # 2. DB lookup: MICR → IFSC
        ifsc_code = await self._db.fetchval(_RESOLVE_MICR_SQL, micr_code)
        if ifsc_code is None:
            raise BranchNotFoundError(
                f"No active branch found for MICR code {micr_code!r}."
            )

        # Cache the MICR → IFSC mapping (same TTL)
        await self._redis.set(micr_key, ifsc_code, ex=self._ttl)

        return await self.resolve_ifsc(ifsc_code)

    # ── Public: invalidation ─────────────────────────────────────────────────

    async def invalidate(self, ifsc_code: str) -> None:
        """Delete the cache entry for one IFSC (called after branch→PU remapping)."""
        await self._redis.delete(crl_cache_key(ifsc_code))
        log.info("crl.cache_invalidated", ifsc_code=ifsc_code)

    async def invalidate_many(self, ifsc_codes: list[str]) -> None:
        """Delete cache entries for multiple IFSCs in one Redis call."""
        if not ifsc_codes:
            return
        keys = [crl_cache_key(c) for c in ifsc_codes]
        await self._redis.delete(*keys)
        log.info("crl.cache_invalidated_many", count=len(ifsc_codes))

    # ── Public: Kafka event handler ───────────────────────────────────────────

    async def handle_invalidation_event(self, payload: str) -> None:
        """
        Process a Kafka cts.crl.invalidated event.

        Expected payload JSON: {"ifsc_codes": ["SBIN0001234", ...]}
        Malformed payloads are logged and silently dropped (never crash the worker).
        """
        try:
            data = json.loads(payload)
            ifsc_codes: list[str] = data.get("ifsc_codes", [])
            if ifsc_codes:
                await self.invalidate_many(ifsc_codes)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning(
                "crl.invalidation_event_malformed",
                payload_preview=payload[:200],
                error=str(exc),
            )
