"""Cheque de-duplication validator for CTS outward and inward processing.

Key: composite of bank_id + MICR_code (9 digits) + cheque_number (6 digits).
MICR_code uniquely identifies bank+branch; cheque_number is unique within a book.
Together they form a globally unique cheque identifier for the clearing period.

Storage:
  - Redis: primary fast lookup, TTL = 18 months (beyond CTS retention minimum)
  - Callers must separately persist to YugabyteDB cts.cheque_dedup for compliance
    audit trail — Redis is cache; DB is source of truth for long-term records.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# 18 months in seconds — matches RBI CTS instrument retention window
DEDUP_TTL_SECONDS: int = 18 * 30 * 24 * 3600  # 46,656,000 seconds


DedupDecision = Literal["FRESH", "DUPLICATE"]


@dataclass(frozen=True)
class DedupCheckResult:
    decision: DedupDecision
    existing_instrument_id: str | None
    existing_presented_at: str | None


def make_dedup_key(bank_id: str, micr_code: str, cheque_number: str) -> str:
    """Build a stable Redis key for this cheque.

    Format: chq_dedup:{bank_id_clean}:{micr_9}:{chq_6}
    Spaces in bank_id are replaced with '-' so the key has no whitespace.
    """
    clean_bank = bank_id.replace(" ", "-").lower()
    return f"chq_dedup:{clean_bank}:{micr_code}:{cheque_number}"


async def check_and_register_dedup(
    bank_id: str,
    micr_code: str,
    cheque_number: str,
    instrument_id: str,
    presented_at: str,
    redis,
    ttl_seconds: int = DEDUP_TTL_SECONDS,
) -> DedupCheckResult:
    """Check for duplicate and register this presentation atomically.

    Args:
        bank_id:       Bank identifier (from context — NOT from cheque OCR).
        micr_code:     9-digit MICR bank+branch code.
        cheque_number: 6-digit cheque serial number.
        instrument_id: New instrument ID being processed.
        presented_at:  ISO datetime string of this presentation.
        redis:         Async Redis client (aioredis or compatible).
        ttl_seconds:   Redis key TTL. Default = 18 months.

    Returns:
        DedupCheckResult with FRESH (first time seen) or DUPLICATE (seen before).
        DUPLICATE result includes the original instrument ID for audit trail.
    """
    key = make_dedup_key(bank_id, micr_code, cheque_number)
    existing_raw = await redis.get(key)

    if existing_raw is not None:
        raw_str = existing_raw.decode() if isinstance(existing_raw, bytes) else existing_raw
        parts = raw_str.split("|", 1)
        return DedupCheckResult(
            decision="DUPLICATE",
            existing_instrument_id=parts[0] if parts else None,
            existing_presented_at=parts[1] if len(parts) > 1 else None,
        )

    # First time seen — register this presentation
    value = f"{instrument_id}|{presented_at}"
    await redis.setex(key, ttl_seconds, value)

    return DedupCheckResult(
        decision="FRESH",
        existing_instrument_id=None,
        existing_presented_at=None,
    )
