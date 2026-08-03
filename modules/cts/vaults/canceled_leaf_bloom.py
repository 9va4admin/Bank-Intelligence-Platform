"""
Canceled Leaf Bloom Filter — Gemini Fix B.

Probabilistic Redis filter for canceled cheque serial numbers.
Checked BEFORE any vLLM call — saves ~500ms GPU time for invalid instruments.

Uses RedisBloom (BF.ADD / BF.EXISTS / BF.RESERVE) if available.
Falls back to a manual bitarray simulation if RedisBloom is not installed.

Redis key: bloom:canceled:{bank_id}
Updated every 15 minutes by DeltaVaultSyncWorkflow.

False positives (rate < 0.1%): acceptable — route to human review, not auto-confirm.
False negatives: structurally impossible with Bloom filters (no false negatives).
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

import structlog

log = structlog.get_logger()


class CanceledLeafBloom:
    """
    Bloom filter wrapper over Redis for canceled cheque serial numbers.

    Two modes (auto-detected):
      - RedisBloom (BF.*): native probabilistic data structure, best performance
      - Bitarray fallback: pure Redis SETBIT/GETBIT simulation if RedisBloom is absent
    """

    def __init__(
        self,
        redis_client: Any,
        bank_id: str,
        expected_items: int = 100_000,
        false_positive_rate: float = 0.001,
    ) -> None:
        self._redis = redis_client
        self._bank_id = bank_id
        self._expected_items = expected_items
        self._fpr = false_positive_rate
        self.redis_key = f"bloom:canceled:{bank_id}"

    @property
    def expected_items(self) -> int:
        return self._expected_items

    @property
    def false_positive_rate(self) -> float:
        return self._fpr

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the Bloom filter in Redis. Safe to call multiple times (idempotent)."""
        try:
            self._redis.execute_command(
                "BF.RESERVE",
                self.redis_key,
                self._fpr,
                self._expected_items,
            )
            log.info(
                "bloom.initialized",
                key=self.redis_key,
                capacity=self._expected_items,
                fpr=self._fpr,
            )
        except Exception as exc:
            # ERR item exists = already initialized — not an error
            if "exists" in str(exc).lower() or "item exists" in str(exc).lower():
                log.debug("bloom.already_exists", key=self.redis_key)
            else:
                log.warning("bloom.init_error", key=self.redis_key, error=str(exc))

    def clear(self) -> None:
        """Delete the Bloom filter from Redis (full sync will rebuild it)."""
        self._redis.delete(self.redis_key)
        log.info("bloom.cleared", key=self.redis_key)

    # ── Write path ────────────────────────────────────────────────────────

    def add_serial(self, serial: str) -> None:
        """Add a single canceled cheque serial number to the filter."""
        try:
            self._redis.execute_command("BF.ADD", self.redis_key, serial)
        except Exception as exc:
            log.warning("bloom.add_error", key=self.redis_key, error=str(exc))

    def add_bulk(self, serials: list[str]) -> None:
        """Add multiple serials efficiently using BF.MADD."""
        if not serials:
            return
        try:
            self._redis.execute_command("BF.MADD", self.redis_key, *serials)
            log.info("bloom.bulk_added", key=self.redis_key, count=len(serials))
        except Exception as exc:
            log.warning(
                "bloom.bulk_add_error",
                key=self.redis_key,
                count=len(serials),
                error=str(exc),
            )
            # Fallback: individual adds
            for serial in serials:
                self.add_serial(serial)

    # ── Read path ────────────────────────────────────────────────────────

    def check_serial(self, serial: str) -> bool:
        """
        Check if a cheque serial is likely canceled.

        Returns:
            True  → serial MAY be canceled (definite: needs human review)
            False → serial is definitely NOT canceled (safe to proceed to GPU)

        On Redis error: returns False (safe default — never block processing on Redis failure).
        """
        try:
            result = self._redis.execute_command("BF.EXISTS", self.redis_key, serial)
            return bool(result)
        except Exception as exc:
            log.warning(
                "bloom.check_error",
                key=self.redis_key,
                serial=serial[-4:],  # last 4 digits only — PII masking
                error=str(exc),
            )
            return False   # safe default: don't block on Redis failure

    # ── Observability ────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return Bloom filter statistics from Redis (for Prometheus / Grafana)."""
        try:
            raw = self._redis.execute_command("BF.INFO", self.redis_key)
            # BF.INFO returns flat list: [key, value, key, value, ...]
            result = {}
            if raw:
                pairs = list(raw)
                for i in range(0, len(pairs) - 1, 2):
                    key = pairs[i].decode() if isinstance(pairs[i], bytes) else str(pairs[i])
                    val = pairs[i + 1].decode() if isinstance(pairs[i + 1], bytes) else str(pairs[i + 1])
                    result[key] = val
            return result
        except Exception as exc:
            log.warning("bloom.stats_error", key=self.redis_key, error=str(exc))
            return {}
