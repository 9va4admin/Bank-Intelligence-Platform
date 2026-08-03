"""
Phase D — Queue Segmentation tests (TDD RED first).

Tests:
 1. Kafka topic constants for segmented inward queues exist in topics.py
 2. resolve_queue_tier() routes amounts to the correct tier
 3. Tier thresholds come from cts_config, never hardcoded
 4. ChequeWorkflowInput carries a queue_tier field
 5. task_queue_for_tier() produces the correct Temporal queue name
"""
import pytest


# ---------------------------------------------------------------------------
# 1. Kafka topic constants
# ---------------------------------------------------------------------------

class TestQueueTopicConstants:
    def test_cts_inward_standard_topic_constant_exists(self):
        from shared.event_bus.topics import CTS_INWARD_STANDARD
        assert "{bank_id}" in CTS_INWARD_STANDARD

    def test_cts_inward_high_value_topic_constant_exists(self):
        from shared.event_bus.topics import CTS_INWARD_HIGH_VALUE
        assert "{bank_id}" in CTS_INWARD_HIGH_VALUE

    def test_cts_inward_very_high_topic_constant_exists(self):
        from shared.event_bus.topics import CTS_INWARD_VERY_HIGH
        assert "{bank_id}" in CTS_INWARD_VERY_HIGH

    def test_topic_names_are_distinct(self):
        from shared.event_bus.topics import (
            CTS_INWARD_STANDARD, CTS_INWARD_HIGH_VALUE, CTS_INWARD_VERY_HIGH,
        )
        assert CTS_INWARD_STANDARD != CTS_INWARD_HIGH_VALUE
        assert CTS_INWARD_HIGH_VALUE != CTS_INWARD_VERY_HIGH

    def test_topic_format_includes_bank_id(self):
        from shared.event_bus.topics import CTS_INWARD_HIGH_VALUE
        formatted = CTS_INWARD_HIGH_VALUE.format(bank_id="saraswat-coop")
        assert "saraswat-coop" in formatted


# ---------------------------------------------------------------------------
# 2. resolve_queue_tier() — tier routing
# ---------------------------------------------------------------------------

class TestResolveQueueTier:
    def _cfg(self, high=100_000.0, very_high=1_000_000.0):
        return {
            "queue_tier_high_value_threshold": high,
            "queue_tier_very_high_threshold": very_high,
        }

    def test_standard_below_high_threshold(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(50_000.0, self._cfg()) == "standard"

    def test_high_value_at_exact_threshold(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(100_000.0, self._cfg()) == "high_value"

    def test_high_value_above_threshold_below_very_high(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(500_000.0, self._cfg()) == "high_value"

    def test_very_high_at_exact_threshold(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(1_000_000.0, self._cfg()) == "very_high"

    def test_very_high_above_threshold(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(5_000_000.0, self._cfg()) == "very_high"

    def test_zero_amount_is_standard(self):
        from modules.cts.queue_tier import resolve_queue_tier
        assert resolve_queue_tier(0.0, self._cfg()) == "standard"

    def test_custom_thresholds_respected(self):
        from modules.cts.queue_tier import resolve_queue_tier
        cfg = {"queue_tier_high_value_threshold": 200_000.0,
               "queue_tier_very_high_threshold": 2_000_000.0}
        assert resolve_queue_tier(150_000.0, cfg) == "standard"
        assert resolve_queue_tier(200_000.0, cfg) == "high_value"
        assert resolve_queue_tier(2_000_000.0, cfg) == "very_high"


# ---------------------------------------------------------------------------
# 3. resolve_queue_tier() uses cts_config — no hardcoded thresholds
# ---------------------------------------------------------------------------

class TestQueueTierConfigDriven:
    def test_missing_high_value_threshold_uses_default(self):
        """Falls back to documented defaults when key absent — never crashes."""
        from modules.cts.queue_tier import resolve_queue_tier
        result = resolve_queue_tier(500_000.0, {})
        assert result in ("standard", "high_value", "very_high")  # doesn't crash

    def test_missing_very_high_threshold_uses_default(self):
        from modules.cts.queue_tier import resolve_queue_tier
        result = resolve_queue_tier(5_000_000.0, {})
        assert result in ("standard", "high_value", "very_high")

    def test_explicit_low_thresholds_override_defaults(self):
        """Banks can set low thresholds to route most cheques to high_value."""
        from modules.cts.queue_tier import resolve_queue_tier
        cfg = {"queue_tier_high_value_threshold": 1.0,
               "queue_tier_very_high_threshold": 2.0}
        assert resolve_queue_tier(1.0, cfg) == "high_value"


# ---------------------------------------------------------------------------
# 4. ChequeWorkflowInput carries queue_tier field
# ---------------------------------------------------------------------------

class TestChequeWorkflowInputQueueTier:
    def test_queue_tier_field_exists(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
        import time
        inp = ChequeWorkflowInput(
            instrument_id="INST001", bank_id="test-bank",
            image_url="s3://bucket/x.jpg", account_number="123",
            cheque_number="001", presented_amount=50_000.0,
            presented_payee="Payee", iet_deadline=time.time() + 3600,
        )
        assert hasattr(inp, "queue_tier")

    def test_queue_tier_defaults_to_standard(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
        import time
        inp = ChequeWorkflowInput(
            instrument_id="INST001", bank_id="test-bank",
            image_url="s3://bucket/x.jpg", account_number="123",
            cheque_number="001", presented_amount=50_000.0,
            presented_payee="Payee", iet_deadline=time.time() + 3600,
        )
        assert inp.queue_tier == "standard"

    def test_queue_tier_can_be_set_explicitly(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
        import time
        inp = ChequeWorkflowInput(
            instrument_id="INST001", bank_id="test-bank",
            image_url="s3://bucket/x.jpg", account_number="123",
            cheque_number="001", presented_amount=1_000_000.0,
            presented_payee="Payee", iet_deadline=time.time() + 3600,
            queue_tier="very_high",
        )
        assert inp.queue_tier == "very_high"

    def test_queue_tier_values_are_valid(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
        import time
        for tier in ("standard", "high_value", "very_high"):
            inp = ChequeWorkflowInput(
                instrument_id="INST001", bank_id="test-bank",
                image_url="s3://bucket/x.jpg", account_number="123",
                cheque_number="001", presented_amount=50_000.0,
                presented_payee="Payee", iet_deadline=time.time() + 3600,
                queue_tier=tier,
            )
            assert inp.queue_tier == tier


# ---------------------------------------------------------------------------
# 5. task_queue_for_tier() — Temporal task queue name
# ---------------------------------------------------------------------------

class TestTaskQueueForTier:
    def test_standard_tier_queue_name(self):
        from modules.cts.queue_tier import task_queue_for_tier
        q = task_queue_for_tier("saraswat-coop", "standard")
        assert "saraswat-coop" in q
        assert "standard" in q

    def test_high_value_tier_queue_name(self):
        from modules.cts.queue_tier import task_queue_for_tier
        q = task_queue_for_tier("saraswat-coop", "high_value")
        assert "saraswat-coop" in q
        assert "high" in q

    def test_very_high_tier_queue_name(self):
        from modules.cts.queue_tier import task_queue_for_tier
        q = task_queue_for_tier("saraswat-coop", "very_high")
        assert "saraswat-coop" in q
        assert "very" in q or "high" in q

    def test_queue_names_are_distinct_per_tier(self):
        from modules.cts.queue_tier import task_queue_for_tier
        std = task_queue_for_tier("test-bank", "standard")
        hv  = task_queue_for_tier("test-bank", "high_value")
        vh  = task_queue_for_tier("test-bank", "very_high")
        assert std != hv
        assert hv != vh

    def test_queue_names_are_distinct_per_bank(self):
        from modules.cts.queue_tier import task_queue_for_tier
        q1 = task_queue_for_tier("bank-a", "standard")
        q2 = task_queue_for_tier("bank-b", "standard")
        assert q1 != q2

    def test_unknown_tier_raises(self):
        from modules.cts.queue_tier import task_queue_for_tier
        with pytest.raises((ValueError, KeyError)):
            task_queue_for_tier("test-bank", "platinum")
