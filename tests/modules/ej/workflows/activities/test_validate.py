"""
Tests for modules/ej/workflows/activities/validate.py

Schema validation of canonical EJ records before storage.
"""
import pytest


def _make_input(canonical_record=None, bank_id="test-bank", atm_id="ATM001"):
    from modules.ej.workflows.activities.validate import EJValidateInput
    if canonical_record is None:
        canonical_record = {
            "transaction_type": "DISPENSE",
            "amount": 5000.0,
            "status": "SUCCESS",
            "timestamp": "2026-06-17T10:30:00+05:30",
            "error_code": None,
        }
    return EJValidateInput(
        canonical_record=canonical_record,
        canonical_hash="a" * 64,
        bank_id=bank_id,
        atm_id=atm_id,
        raw_log_hash="abc123",
    )


class TestEJValidateInput:
    def test_requires_canonical_record(self):
        from modules.ej.workflows.activities.validate import EJValidateInput
        with pytest.raises(Exception):
            EJValidateInput(canonical_hash="x" * 64, bank_id="b", atm_id="a", raw_log_hash="h")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.bank_id = "other"


class TestEJValidateHappyPath:
    @pytest.mark.asyncio
    async def test_valid_record_passes(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input())
        assert result.outcome == "VALID"

    @pytest.mark.asyncio
    async def test_result_has_bank_id(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input(bank_id="kotak"))
        assert result.bank_id == "kotak"

    @pytest.mark.asyncio
    async def test_valid_result_no_errors(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input())
        assert result.validation_errors == []


class TestEJValidateInvalidRecord:
    @pytest.mark.asyncio
    async def test_missing_transaction_type_is_invalid(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        record = {"amount": 5000.0, "status": "SUCCESS", "timestamp": "2026-06-17T10:30:00+05:30"}
        result = await validate_ej_canonical(_make_input(canonical_record=record))
        assert result.outcome == "INVALID"

    @pytest.mark.asyncio
    async def test_missing_status_is_invalid(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        record = {"transaction_type": "DISPENSE", "amount": 5000.0, "timestamp": "2026-06-17T10:30:00+05:30"}
        result = await validate_ej_canonical(_make_input(canonical_record=record))
        assert result.outcome == "INVALID"

    @pytest.mark.asyncio
    async def test_invalid_result_has_errors(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input(canonical_record={}))
        assert len(result.validation_errors) > 0

    @pytest.mark.asyncio
    async def test_empty_record_is_invalid(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input(canonical_record={}))
        assert result.outcome == "INVALID"

    @pytest.mark.asyncio
    async def test_invalid_does_not_raise(self):
        from modules.ej.workflows.activities.validate import validate_ej_canonical

        result = await validate_ej_canonical(_make_input(canonical_record={}))
        assert result is not None
