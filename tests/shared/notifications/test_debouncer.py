"""
TDD — RED phase: tests for shared/notifications/debouncer.py

Notification Debouncer (Gemini Fix E):
  - If ≥ N notifications for same (bank_id, smb_id, event_category) within W seconds:
      suppress individual notifications, emit ONE consolidated summary
  - P0 (priority=0) events are NEVER debounced — always pass through immediately
  - Config-driven: threshold=10, window=60s (from config_service — never hardcoded)
  - Redis sorted sets: ZADD for burst tracking, ZCOUNT for window check
  - Key: notif:debounce:{bank_id}:{smb_id}:{event_category}
  - All tests use MockRedis — no real Redis dependency
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_debouncer(redis_client=None, threshold=10, window_seconds=60, exempt_priorities=None):
    from shared.notifications.debouncer import NotificationDebouncer
    config = {
        "notification.debounce.enabled": True,
        "notification.debounce.threshold": threshold,
        "notification.debounce.window_seconds": window_seconds,
        "notification.debounce.exempt_priorities": exempt_priorities or ["P0"],
    }
    return NotificationDebouncer(
        redis_client=redis_client or MagicMock(),
        config=config,
    )


def _make_event(
    bank_id="test-bank",
    smb_id="smb-001",
    event_category="VAULT_MISS",
    priority="P2",
    payload=None,
):
    from shared.notifications.debouncer import NotificationEvent
    return NotificationEvent(
        bank_id=bank_id,
        smb_id=smb_id,
        event_category=event_category,
        priority=priority,
        payload=payload or {"message": "vault miss"},
    )


# ---------------------------------------------------------------------------
# NotificationEvent model
# ---------------------------------------------------------------------------

class TestNotificationEvent:
    def test_event_fields(self):
        from shared.notifications.debouncer import NotificationEvent
        ev = NotificationEvent(
            bank_id="sbi-main",
            smb_id="smb-xyz",
            event_category="IET_RISK",
            priority="P1",
            payload={"instrument_id": "instr-001"},
        )
        assert ev.bank_id == "sbi-main"
        assert ev.smb_id == "smb-xyz"
        assert ev.event_category == "IET_RISK"
        assert ev.priority == "P1"

    def test_event_is_frozen(self):
        ev = _make_event()
        with pytest.raises(Exception):
            ev.bank_id = "tampered"

    def test_event_with_no_smb_id(self):
        """SMB id is optional — SB-level events have no SMB."""
        from shared.notifications.debouncer import NotificationEvent
        ev = NotificationEvent(
            bank_id="hdfc-bank",
            smb_id=None,
            event_category="CBS_TIMEOUT",
            priority="P2",
            payload={},
        )
        assert ev.smb_id is None


# ---------------------------------------------------------------------------
# DebounceDecision model
# ---------------------------------------------------------------------------

class TestDebounceDecision:
    def test_pass_through_decision(self):
        from shared.notifications.debouncer import DebounceDecision
        d = DebounceDecision(
            action="PASS_THROUGH",
            event_category="VAULT_MISS",
            bank_id="test-bank",
            suppressed_count=0,
        )
        assert d.action == "PASS_THROUGH"
        assert d.summary_payload is None

    def test_suppress_decision_carries_summary(self):
        from shared.notifications.debouncer import DebounceDecision
        d = DebounceDecision(
            action="SUPPRESS",
            event_category="VAULT_MISS",
            bank_id="test-bank",
            suppressed_count=12,
            summary_payload={"total": 12, "category": "VAULT_MISS"},
        )
        assert d.action == "SUPPRESS"
        assert d.suppressed_count == 12
        assert d.summary_payload["total"] == 12

    def test_emit_summary_decision(self):
        from shared.notifications.debouncer import DebounceDecision
        d = DebounceDecision(
            action="EMIT_SUMMARY",
            event_category="VAULT_MISS",
            bank_id="test-bank",
            suppressed_count=10,
            summary_payload={"total": 10, "category": "VAULT_MISS"},
        )
        assert d.action == "EMIT_SUMMARY"


# ---------------------------------------------------------------------------
# check_and_record — main debouncing logic
# ---------------------------------------------------------------------------

class TestCheckAndRecord:
    def test_below_threshold_returns_pass_through(self):
        """4 events within 60s window, threshold=10 → PASS_THROUGH."""
        redis = MagicMock()
        # Simulate 4 events already in window
        redis.zcount.return_value = 4
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10, window_seconds=60)
        ev = _make_event()
        decision = debouncer.check_and_record(ev)

        assert decision.action == "PASS_THROUGH"

    def test_at_threshold_returns_emit_summary(self):
        """Exactly at threshold (10 events) → EMIT_SUMMARY (first consolidated alert)."""
        redis = MagicMock()
        # After adding this event, count becomes 10 = threshold
        redis.zcount.return_value = 10
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event()
        decision = debouncer.check_and_record(ev)

        assert decision.action == "EMIT_SUMMARY"
        assert decision.suppressed_count == 10

    def test_above_threshold_returns_suppress(self):
        """14 events in window, threshold=10 → SUPPRESS (already emitted summary)."""
        redis = MagicMock()
        redis.zcount.return_value = 14
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event()
        decision = debouncer.check_and_record(ev)

        assert decision.action == "SUPPRESS"
        assert decision.suppressed_count >= 10

    def test_p0_event_always_pass_through_regardless_of_count(self):
        """P0 events are never debounced — IET breach, fraud alert, etc."""
        redis = MagicMock()
        # Even with 999 events in window
        redis.zcount.return_value = 999
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event(priority="P0", event_category="IET_BREACH")
        decision = debouncer.check_and_record(ev)

        # P0 must NEVER be suppressed
        assert decision.action == "PASS_THROUGH"

    def test_p0_event_does_not_call_redis(self):
        """P0 events bypass Redis entirely — no tracking overhead."""
        redis = MagicMock()
        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event(priority="P0")
        debouncer.check_and_record(ev)

        # Redis should not be queried for P0 events
        redis.zcount.assert_not_called()

    def test_debouncer_disabled_always_pass_through(self):
        """If debouncing is disabled in config, all events pass through."""
        from shared.notifications.debouncer import NotificationDebouncer
        redis = MagicMock()
        redis.zcount.return_value = 999

        config = {
            "notification.debounce.enabled": False,
            "notification.debounce.threshold": 10,
            "notification.debounce.window_seconds": 60,
            "notification.debounce.exempt_priorities": ["P0"],
        }
        debouncer = NotificationDebouncer(redis_client=redis, config=config)
        ev = _make_event()
        decision = debouncer.check_and_record(ev)

        assert decision.action == "PASS_THROUGH"
        redis.zcount.assert_not_called()


# ---------------------------------------------------------------------------
# Redis key structure — isolation
# ---------------------------------------------------------------------------

class TestRedisKeyIsolation:
    def test_redis_key_includes_bank_id(self):
        """Bank isolation: keys for different banks must not collide."""
        redis = MagicMock()
        redis.zcount.return_value = 0
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis)

        ev_hdfc = _make_event(bank_id="hdfc-bank", smb_id="smb-a")
        ev_kotak = _make_event(bank_id="kotak-mah", smb_id="smb-a")

        debouncer.check_and_record(ev_hdfc)
        debouncer.check_and_record(ev_kotak)

        # Both calls must use different Redis keys
        all_zadd_keys = [str(c) for c in redis.zadd.call_args_list]
        assert any("hdfc-bank" in k for k in all_zadd_keys)
        assert any("kotak-mah" in k for k in all_zadd_keys)

    def test_redis_key_includes_smb_id(self):
        """SMB isolation: events for different SMBs under same SB are tracked separately."""
        redis = MagicMock()
        redis.zcount.return_value = 0
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis)

        ev_smb1 = _make_event(smb_id="smb-001")
        ev_smb2 = _make_event(smb_id="smb-002")

        debouncer.check_and_record(ev_smb1)
        debouncer.check_and_record(ev_smb2)

        all_zadd_keys = [str(c) for c in redis.zadd.call_args_list]
        assert any("smb-001" in k for k in all_zadd_keys)
        assert any("smb-002" in k for k in all_zadd_keys)

    def test_redis_key_includes_event_category(self):
        """Different event categories tracked independently."""
        redis = MagicMock()
        redis.zcount.return_value = 0
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis)

        ev_vault = _make_event(event_category="VAULT_MISS")
        ev_fraud = _make_event(event_category="FRAUD_ALERT")

        debouncer.check_and_record(ev_vault)
        debouncer.check_and_record(ev_fraud)

        all_zadd_keys = [str(c) for c in redis.zadd.call_args_list]
        assert any("VAULT_MISS" in k for k in all_zadd_keys)
        assert any("FRAUD_ALERT" in k for k in all_zadd_keys)

    def test_redis_key_format(self):
        """Key format: notif:debounce:{bank_id}:{smb_id}:{event_category}."""
        redis = MagicMock()
        redis.zcount.return_value = 0
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis)
        ev = _make_event(bank_id="sbi-main", smb_id="smb-xyz", event_category="CBS_TIMEOUT")
        debouncer.check_and_record(ev)

        all_calls = str(redis.zadd.call_args_list)
        assert "notif:debounce:sbi-main:smb-xyz:CBS_TIMEOUT" in all_calls


# ---------------------------------------------------------------------------
# Window expiry (old events fall out of window)
# ---------------------------------------------------------------------------

class TestWindowExpiry:
    def test_zcount_uses_time_window(self):
        """Only events within the last window_seconds are counted."""
        redis = MagicMock()
        redis.zcount.return_value = 3
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10, window_seconds=60)
        ev = _make_event()
        debouncer.check_and_record(ev)

        # zcount must be called with a min score (now - 60) and max score (now)
        assert redis.zcount.called
        zcount_args = redis.zcount.call_args
        # The min and max arguments should be within current epoch range
        min_score, max_score = zcount_args[0][1], zcount_args[0][2]
        now = time.time()
        assert max_score <= now + 1        # max ≈ now
        assert min_score >= now - 61       # min ≈ now - window_seconds

    def test_old_entries_removed_with_zremrangebyscore(self):
        """Expired entries (outside window) should be pruned to keep Redis sets small."""
        redis = MagicMock()
        redis.zcount.return_value = 0
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, window_seconds=60)
        ev = _make_event()
        debouncer.check_and_record(ev)

        # zremrangebyscore must be called to clean up old entries
        assert redis.zremrangebyscore.called


# ---------------------------------------------------------------------------
# Redis failure graceful degradation
# ---------------------------------------------------------------------------

class TestDebouncerRedisFailure:
    def test_redis_failure_returns_pass_through_safe_default(self):
        """If Redis is unavailable, debouncer must PASS_THROUGH (never block notifications)."""
        redis = MagicMock()
        redis.zcount.side_effect = Exception("Redis connection refused")
        redis.zadd.side_effect = Exception("Redis connection refused")

        debouncer = _make_debouncer(redis_client=redis)
        ev = _make_event()
        decision = debouncer.check_and_record(ev)

        # Safe default: when debouncer fails → let the notification through
        assert decision.action == "PASS_THROUGH"

    def test_redis_failure_does_not_raise(self):
        """Debouncer must never propagate Redis exceptions to the caller."""
        redis = MagicMock()
        redis.zcount.side_effect = RuntimeError("Redis cluster unreachable")

        debouncer = _make_debouncer(redis_client=redis)
        ev = _make_event()
        # Must not raise
        decision = debouncer.check_and_record(ev)
        assert decision is not None


# ---------------------------------------------------------------------------
# Summary payload structure
# ---------------------------------------------------------------------------

class TestSummaryPayload:
    def test_emit_summary_payload_contains_count_and_category(self):
        """Summary notification must include the burst count and event category."""
        redis = MagicMock()
        redis.zcount.return_value = 10  # exactly at threshold
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event(event_category="VAULT_MISS", bank_id="test-bank", smb_id="smb-001")
        decision = debouncer.check_and_record(ev)

        assert decision.action == "EMIT_SUMMARY"
        assert decision.summary_payload is not None
        assert decision.summary_payload["event_category"] == "VAULT_MISS"
        assert decision.summary_payload["count"] >= 10

    def test_emit_summary_payload_contains_bank_and_smb_ids(self):
        """Summary must identify which bank/SMB triggered the burst."""
        redis = MagicMock()
        redis.zcount.return_value = 10
        redis.zadd.return_value = 1

        debouncer = _make_debouncer(redis_client=redis, threshold=10)
        ev = _make_event(bank_id="kotak-mah", smb_id="smb-xyz")
        decision = debouncer.check_and_record(ev)

        assert decision.summary_payload["bank_id"] == "kotak-mah"
        assert decision.summary_payload["smb_id"] == "smb-xyz"
