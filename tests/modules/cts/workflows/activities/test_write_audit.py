"""Tests for write_audit activity."""
import pytest
from unittest.mock import AsyncMock

from modules.cts.workflows.activities.write_audit import (
    WriteAuditInput,
    WriteAuditResult,
    write_audit,
    _VALID_EVENT_TYPES,
)


def _make_input(event_type="CTS_STP_CONFIRM", instrument_id="CHQ-001"):
    return WriteAuditInput(
        event_type=event_type,
        bank_id="test-bank",
        instrument_id=instrument_id,
        payload={"decision": "CONFIRM", "fraud_score": 0.12},
    )


class TestWriteAuditInput:
    def test_requires_event_type(self):
        with pytest.raises(Exception):
            WriteAuditInput(bank_id="b", payload={})

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.event_type = "other"

    def test_instrument_id_optional(self):
        inp = WriteAuditInput(event_type="CTS_STP_CONFIRM", bank_id="b", payload={})
        assert inp.instrument_id is None


class TestWriteAuditHappyPath:
    @pytest.mark.asyncio
    async def test_returns_success_true(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX-123"
        result = await write_audit(_make_input(), immudb_client=immudb)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_returns_transaction_id(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX-456"
        result = await write_audit(_make_input(), immudb_client=immudb)
        assert result.immudb_tx_id == "TX-456"

    @pytest.mark.asyncio
    async def test_calls_immudb_with_event_type(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX"
        await write_audit(_make_input("CTS_STP_RETURN"), immudb_client=immudb)
        _, kwargs = immudb.write.call_args
        assert kwargs["event_type"] == "CTS_STP_RETURN"

    @pytest.mark.asyncio
    async def test_calls_immudb_with_bank_id(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX"
        await write_audit(_make_input(), immudb_client=immudb)
        _, kwargs = immudb.write.call_args
        assert kwargs["bank_id"] == "test-bank"

    @pytest.mark.asyncio
    async def test_calls_immudb_with_cts_collection(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX"
        await write_audit(_make_input(), immudb_client=immudb)
        _, kwargs = immudb.write.call_args
        assert "cts_" in kwargs["collection"]


class TestWriteAuditFailure:
    @pytest.mark.asyncio
    async def test_immudb_error_raises(self):
        immudb = AsyncMock()
        immudb.write.side_effect = Exception("Immudb unavailable")
        with pytest.raises(Exception, match="Immudb unavailable"):
            await write_audit(_make_input(), immudb_client=immudb)

    @pytest.mark.asyncio
    async def test_unknown_event_type_still_writes(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX"
        result = await write_audit(
            WriteAuditInput(event_type="UNKNOWN_EVENT", bank_id="b", payload={}),
            immudb_client=immudb,
        )
        assert result.success is True
        immudb.write.assert_called_once()


class TestValidEventTypes:
    def test_stp_confirm_is_valid(self):
        assert "CTS_STP_CONFIRM" in _VALID_EVENT_TYPES

    def test_stp_return_is_valid(self):
        assert "CTS_STP_RETURN" in _VALID_EVENT_TYPES

    def test_iet_emergency_is_valid(self):
        assert "CTS_IET_EMERGENCY_FILED" in _VALID_EVENT_TYPES

    def test_human_review_decided_is_valid(self):
        assert "CTS_HUMAN_REVIEW_DECIDED" in _VALID_EVENT_TYPES
