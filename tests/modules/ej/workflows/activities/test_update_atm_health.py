"""
Tests for modules/ej/workflows/activities/update_atm_health.py

Emits ATM health signal derived from the normalised EJ canonical record.
"""
import pytest

from modules.ej.workflows.activities.update_atm_health import (
    EJUpdateATMHealthResult,
    update_atm_health,
)


class TestEJUpdateATMHealthResult:
    def test_result_fields(self):
        r = EJUpdateATMHealthResult(outcome="UPDATED", atm_id="ATM001", bank_id="test-bank")
        assert r.outcome == "UPDATED"
        assert r.atm_id == "ATM001"
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJUpdateATMHealthResult(outcome="UPDATED", atm_id="ATM001", bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestUpdateATMHealthActivity:
    @pytest.mark.asyncio
    async def test_happy_path_returns_updated(self):
        result = await update_atm_health(
            canonical_record={"transaction_type": "DISPENSE", "status": "SUCCESS"},
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "UPDATED"

    @pytest.mark.asyncio
    async def test_atm_id_preserved_in_result(self):
        result = await update_atm_health(
            canonical_record={},
            atm_id="ATM042",
            bank_id="test-bank",
        )
        assert result.atm_id == "ATM042"

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await update_atm_health(
            canonical_record={},
            atm_id="ATM001",
            bank_id="hdfc-bank",
        )
        assert result.bank_id == "hdfc-bank"
