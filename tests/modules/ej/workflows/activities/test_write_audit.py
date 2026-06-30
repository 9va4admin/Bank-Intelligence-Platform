"""
Tests for modules/ej/workflows/activities/write_audit.py

Writes immutable audit event to Immudb for all workflow terminal states.
"""
import pytest

from modules.ej.workflows.activities.write_audit import (
    EJWriteAuditResult,
    write_audit,
)


class TestEJWriteAuditResult:
    def test_result_fields(self):
        r = EJWriteAuditResult(outcome="WRITTEN", bank_id="test-bank")
        assert r.outcome == "WRITTEN"
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJWriteAuditResult(outcome="WRITTEN", bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestWriteAuditActivity:
    @pytest.mark.asyncio
    async def test_write_on_normalised_outcome(self):
        result = await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_write_on_parse_failed_outcome(self):
        result = await write_audit(
            workflow_outcome="PARSE_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash=None,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_write_on_validation_failed_outcome(self):
        result = await write_audit(
            workflow_outcome="VALIDATION_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="kotak-mah",
        )
        assert result.bank_id == "kotak-mah"

    @pytest.mark.asyncio
    async def test_accepts_none_canonical_hash(self):
        """canonical_hash is None when parse fails before hash is produced."""
        result = await write_audit(
            workflow_outcome="PARSE_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash=None,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "WRITTEN"
