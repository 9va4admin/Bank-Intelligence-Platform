"""
Tests for modules/ej/workflows/activities/fingerprint.py

OEM fingerprinting: receives fingerprint detected at edge (Go binary).
Python side does NOT detect OEM — it receives and validates the fingerprint.
"""
import pytest
from unittest.mock import AsyncMock


def _make_input(oem_fingerprint="NCR_SELFSERV", atm_id="ATM001", bank_id="test-bank"):
    from modules.ej.workflows.activities.fingerprint import EJFingerprintInput
    return EJFingerprintInput(
        oem_fingerprint=oem_fingerprint,
        atm_id=atm_id,
        bank_id=bank_id,
        raw_log_hash="abc123",
    )


_KNOWN_OEMS = ["NCR_SELFSERV", "DIEBOLD_NIXDORF", "WINCOR_NIXDORF", "HYOSUNG", "GRG_BANKING"]


class TestEJFingerprintInput:
    def test_requires_oem_fingerprint(self):
        from modules.ej.workflows.activities.fingerprint import EJFingerprintInput
        with pytest.raises(Exception):
            EJFingerprintInput(atm_id="ATM1", bank_id="b", raw_log_hash="h")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.oem_fingerprint = "other"


class TestEJFingerprintHappyPath:
    @pytest.mark.asyncio
    async def test_known_oem_returns_validated(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(oem_fingerprint="NCR_SELFSERV"))
        assert result.outcome == "VALIDATED"

    @pytest.mark.asyncio
    async def test_validated_result_has_oem(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(oem_fingerprint="DIEBOLD_NIXDORF"))
        assert result.oem_fingerprint == "DIEBOLD_NIXDORF"

    @pytest.mark.asyncio
    async def test_all_known_oems_validate(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        for oem in _KNOWN_OEMS:
            result = await validate_oem_fingerprint(_make_input(oem_fingerprint=oem))
            assert result.outcome == "VALIDATED", f"OEM {oem} should validate"

    @pytest.mark.asyncio
    async def test_result_includes_bank_id(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(bank_id="kotak"))
        assert result.bank_id == "kotak"


class TestEJFingerprintUnknown:
    @pytest.mark.asyncio
    async def test_unknown_oem_returns_unknown(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(oem_fingerprint="UNKNOWN_OEM_XYZ"))
        assert result.outcome == "UNKNOWN_OEM"

    @pytest.mark.asyncio
    async def test_unknown_oem_does_not_raise(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(oem_fingerprint="VENDOR_42"))
        assert result is not None

    @pytest.mark.asyncio
    async def test_unknown_oem_preserves_fingerprint_for_logging(self):
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint

        result = await validate_oem_fingerprint(_make_input(oem_fingerprint="MYSTERY_VENDOR"))
        assert result.oem_fingerprint == "MYSTERY_VENDOR"
