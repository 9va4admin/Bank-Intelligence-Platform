"""
Tests for modules/msv/workflows/activities/write_audit.py

Covers:
  - Known event_type → writes to immudb, returns tx_id
  - Unknown event_type → logs warning but still writes
  - Immudb failure → re-raises so Temporal can retry with AUDIT_RETRY
  - Result is typed WriteAuditResult
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.msv.workflows.activities.write_audit import (
    WriteAuditInput,
    WriteAuditResult,
    write_audit,
)


def _make_immudb(tx_id: str = "immudb-tx-123"):
    client = MagicMock()
    client.write = AsyncMock(return_value=tx_id)
    return client


class TestMSVWriteAudit:
    @pytest.mark.asyncio
    async def test_known_event_type_writes_and_returns_tx_id(self):
        client = _make_immudb("tx-001")
        inp = WriteAuditInput(
            event_type="MSV_VALIDATED",
            bank_id="kotak-mah",
            instrument_id="CHQ-001",
            payload={"outcome": "GREEN", "confidence": 0.97},
        )
        result = await write_audit(inp, immudb_client=client)
        assert isinstance(result, WriteAuditResult)
        assert result.success is True
        assert result.immudb_tx_id == "tx-001"

    @pytest.mark.asyncio
    async def test_unknown_event_type_still_writes(self):
        """Unknown event type should write (with warning log) not raise."""
        client = _make_immudb("tx-002")
        inp = WriteAuditInput(
            event_type="MSV_UNKNOWN_XYZ",
            bank_id="kotak-mah",
            instrument_id=None,
            payload={},
        )
        result = await write_audit(inp, immudb_client=client)
        assert result.success is True
        client.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_immudb_failure_reraises_for_temporal_retry(self):
        """Immudb error must propagate so Temporal's AUDIT_RETRY policy retries."""
        client = MagicMock()
        client.write = AsyncMock(side_effect=RuntimeError("immudb unreachable"))
        inp = WriteAuditInput(
            event_type="MSV_VALIDATED",
            bank_id="kotak-mah",
            instrument_id="CHQ-001",
            payload={},
        )
        with pytest.raises(RuntimeError, match="immudb unreachable"):
            await write_audit(inp, immudb_client=client)

    @pytest.mark.asyncio
    async def test_write_includes_bank_id_in_collection(self):
        """Immudb collection must include bank_id for tenant isolation."""
        client = _make_immudb()
        inp = WriteAuditInput(
            event_type="MSV_VALIDATED",
            bank_id="kotak-mah",
            instrument_id="CHQ-001",
            payload={"outcome": "GREEN"},
        )
        await write_audit(inp, immudb_client=client)
        call_kwargs = client.write.call_args
        # Collection must contain bank_id
        all_args = str(call_kwargs)
        assert "kotak-mah" in all_args

    @pytest.mark.asyncio
    async def test_result_is_frozen_pydantic_model(self):
        client = _make_immudb("tx-frozen")
        inp = WriteAuditInput(
            event_type="MSV_ENROLLMENT_COMPLETE",
            bank_id="kotak-mah",
            payload={},
        )
        result = await write_audit(inp, immudb_client=client)
        with pytest.raises((TypeError, Exception)):
            result.success = False  # frozen model should reject mutation
