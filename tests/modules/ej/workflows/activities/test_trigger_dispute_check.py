"""
Tests for modules/ej/workflows/activities/trigger_dispute_check.py

Publishes normalised EJ record to Kafka for dispute matching.
"""
import pytest

from modules.ej.workflows.activities.trigger_dispute_check import (
    EJTriggerDisputeCheckResult,
    trigger_dispute_check,
)


class TestEJTriggerDisputeCheckResult:
    def test_result_fields(self):
        r = EJTriggerDisputeCheckResult(outcome="TRIGGERED", bank_id="test-bank")
        assert r.outcome == "TRIGGERED"
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJTriggerDisputeCheckResult(outcome="TRIGGERED", bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestTriggerDisputeCheckActivity:
    @pytest.mark.asyncio
    async def test_happy_path_returns_triggered(self):
        result = await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "TRIGGERED"

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="kotak-mah",
        )
        assert result.bank_id == "kotak-mah"
