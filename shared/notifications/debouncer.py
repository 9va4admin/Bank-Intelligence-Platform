"""
NotificationDebouncer — Gemini Fix E.

Prevents notification storms from overwhelming bank operators.

Problem: 500 parallel cheque-processing agents can fire 500 "VAULT_MISS" notifications
simultaneously for the same SMB. Operators receive an unworkable flood; P0 alerts get
buried and missed.

Solution: Redis sorted-set burst detection.
  - Track notification events by (bank_id, smb_id, event_category) in a sliding window
  - If count in window reaches threshold → suppress individuals, emit ONE summary
  - P0 (IET breach, fraud, CRITICAL security) are NEVER debounced — always pass through
  - If Redis is unavailable → PASS_THROUGH (safe default — notifications resume normally)

Config keys (all from config_service, never hardcoded):
  notification.debounce.enabled           (bool, default: true)
  notification.debounce.threshold         (int, default: 10)
  notification.debounce.window_seconds    (int, default: 60)
  notification.debounce.exempt_priorities (list, default: ["P0"])

Redis key: notif:debounce:{bank_id}:{smb_id}:{event_category}
Redis structure: sorted set — member=UUID, score=epoch_timestamp
Expiry: entries older than window_seconds are pruned on each call (ZREMRANGEBYSCORE).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class NotificationEvent(BaseModel):
    """Represents a single notification candidate being evaluated for debouncing."""
    model_config = ConfigDict(frozen=True)
    bank_id: str
    smb_id: Optional[str]           # None for SB-level events
    event_category: str             # e.g. "VAULT_MISS", "CBS_TIMEOUT", "FRAUD_ALERT"
    priority: str                   # "P0" | "P1" | "P2" | "P3"
    payload: dict[str, Any]         # original notification payload


class DebounceDecision(BaseModel):
    """Decision returned by check_and_record for each notification event."""
    model_config = ConfigDict(frozen=True)
    action: str                     # "PASS_THROUGH" | "SUPPRESS" | "EMIT_SUMMARY"
    event_category: str
    bank_id: str
    suppressed_count: int = 0
    summary_payload: Optional[dict[str, Any]] = None  # populated when action=EMIT_SUMMARY


# ---------------------------------------------------------------------------
# Debouncer
# ---------------------------------------------------------------------------

class NotificationDebouncer:
    """
    Burst-detection debouncer for ASTRA notification pipeline.

    Call check_and_record() before dispatching any notification.
    Act on the returned DebounceDecision:
      PASS_THROUGH → dispatch normally
      SUPPRESS     → discard this notification (a summary was already emitted at threshold)
      EMIT_SUMMARY → dispatch a consolidated summary notification instead of the individual
    """

    def __init__(self, redis_client: Any, config: dict[str, Any]) -> None:
        self._redis = redis_client
        self._config = config

    def check_and_record(self, event: NotificationEvent) -> DebounceDecision:
        """
        Evaluate whether this notification should pass through or be debounced.

        Synchronous: called on the hot path before channel dispatch.
        Redis operations are fast (< 1ms typical).
        """
        enabled: bool = self._config.get("notification.debounce.enabled", True)
        if not enabled:
            return DebounceDecision(
                action="PASS_THROUGH",
                event_category=event.event_category,
                bank_id=event.bank_id,
            )

        exempt_priorities: list[str] = self._config.get(
            "notification.debounce.exempt_priorities", ["P0"]
        )
        if event.priority in exempt_priorities:
            log.debug(
                "debounce.exempt_priority",
                priority=event.priority,
                event_category=event.event_category,
                bank_id=event.bank_id,
            )
            return DebounceDecision(
                action="PASS_THROUGH",
                event_category=event.event_category,
                bank_id=event.bank_id,
            )

        threshold: int = self._config.get("notification.debounce.threshold", 10)
        window_seconds: int = self._config.get("notification.debounce.window_seconds", 60)

        redis_key = self._build_key(event)
        now = time.time()
        window_start = now - window_seconds

        try:
            # 1. Prune entries older than window
            self._redis.zremrangebyscore(redis_key, "-inf", window_start)

            # 2. Record this event
            member = str(uuid.uuid4())
            self._redis.zadd(redis_key, {member: now})

            # 3. Count events in current window
            count: int = self._redis.zcount(redis_key, window_start, now)

        except Exception as exc:
            log.warning(
                "debounce.redis_error",
                event_category=event.event_category,
                bank_id=event.bank_id,
                error=str(exc),
            )
            # Safe default: Redis failure → let all notifications through
            return DebounceDecision(
                action="PASS_THROUGH",
                event_category=event.event_category,
                bank_id=event.bank_id,
            )

        if count < threshold:
            return DebounceDecision(
                action="PASS_THROUGH",
                event_category=event.event_category,
                bank_id=event.bank_id,
                suppressed_count=0,
            )

        if count == threshold:
            # First time crossing the threshold → emit consolidated summary
            log.info(
                "debounce.threshold_reached",
                event_category=event.event_category,
                bank_id=event.bank_id,
                smb_id=event.smb_id,
                count=count,
                threshold=threshold,
                window_seconds=window_seconds,
            )
            summary_payload = self._build_summary_payload(event, count)
            return DebounceDecision(
                action="EMIT_SUMMARY",
                event_category=event.event_category,
                bank_id=event.bank_id,
                suppressed_count=count,
                summary_payload=summary_payload,
            )

        # count > threshold — summary was already emitted, suppress this one
        log.debug(
            "debounce.suppressed",
            event_category=event.event_category,
            bank_id=event.bank_id,
            count=count,
        )
        return DebounceDecision(
            action="SUPPRESS",
            event_category=event.event_category,
            bank_id=event.bank_id,
            suppressed_count=count,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _build_key(self, event: NotificationEvent) -> str:
        smb_part = event.smb_id or "no-smb"
        return f"notif:debounce:{event.bank_id}:{smb_part}:{event.event_category}"

    @staticmethod
    def _build_summary_payload(event: NotificationEvent, count: int) -> dict[str, Any]:
        return {
            "event_category": event.event_category,
            "bank_id": event.bank_id,
            "smb_id": event.smb_id,
            "count": count,
            "message": (
                f"{count} {event.event_category} notifications fired within the debounce window. "
                f"Please review the ops workstation for details."
            ),
        }
