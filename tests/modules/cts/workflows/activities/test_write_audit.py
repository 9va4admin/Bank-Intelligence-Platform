"""Tests for write_audit activity."""
import pytest
from unittest.mock import AsyncMock, patch

from modules.cts.workflows.activities.write_audit import (
    WriteAuditInput,
    WriteAuditResult,
    write_audit,
    _VALID_EVENT_TYPES,
)


def _make_input(event_type="CTS_NGCH_FILED_CONFIRM", instrument_id="CHQ-001"):
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
        inp = WriteAuditInput(event_type="CTS_NGCH_FILED_CONFIRM", bank_id="b", payload={})
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
        await write_audit(_make_input("CTS_NGCH_FILED_RETURN"), immudb_client=immudb)
        _, kwargs = immudb.write.call_args
        assert kwargs["event_type"] == "CTS_NGCH_FILED_RETURN"

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


class TestIncidentSignalEmission:
    """The 'know before the end user tells us' path — see
    docs/astra-incident-management-plan §06/§09. write_audit is the single
    choke-point almost every CTS decision/error already flows through, so
    it's the highest-leverage place to wire emit_incident_signal()."""

    @pytest.mark.asyncio
    async def test_emits_signal_for_the_written_event_type_on_success(self):
        immudb = AsyncMock()
        immudb.write.return_value = "TX"
        with patch("modules.cts.workflows.activities.write_audit.emit_incident_signal") as mock_emit:
            await write_audit(_make_input("CTS_WF_IET_WATCHDOG_FIRED"), immudb_client=immudb)
        mock_emit.assert_any_call("CTS_WF_IET_WATCHDOG_FIRED", bank_id="test-bank")

    @pytest.mark.asyncio
    async def test_emits_platform_audit_write_failed_signal_on_immudb_error(self):
        immudb = AsyncMock()
        immudb.write.side_effect = Exception("Immudb unavailable")
        with patch("modules.cts.workflows.activities.write_audit.emit_incident_signal") as mock_emit:
            with pytest.raises(Exception, match="Immudb unavailable"):
                await write_audit(_make_input(), immudb_client=immudb)
        mock_emit.assert_any_call("PLATFORM_AUDIT_WRITE_FAILED", bank_id="test-bank")

    @pytest.mark.asyncio
    async def test_does_not_emit_the_written_event_signal_when_immudb_fails(self):
        """On failure, the event that FAILED to write was never actually
        recorded — only the meta-signal (the audit pipeline itself broke)
        should fire, not a signal claiming the original event happened."""
        immudb = AsyncMock()
        immudb.write.side_effect = Exception("boom")
        with patch("modules.cts.workflows.activities.write_audit.emit_incident_signal") as mock_emit:
            with pytest.raises(Exception):
                await write_audit(_make_input("CTS_WF_IET_WATCHDOG_FIRED"), immudb_client=immudb)
        calls = [c.args[0] for c in mock_emit.call_args_list]
        assert "CTS_WF_IET_WATCHDOG_FIRED" not in calls
        assert "PLATFORM_AUDIT_WRITE_FAILED" in calls


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
    """Every entry here must also exist in shared/messages/locales/messages.yaml
    — write_audit's own event types are not a separate taxonomy (messages.md)."""

    def test_ngch_filed_confirm_is_valid(self):
        assert "CTS_NGCH_FILED_CONFIRM" in _VALID_EVENT_TYPES

    def test_ngch_filed_return_is_valid(self):
        assert "CTS_NGCH_FILED_RETURN" in _VALID_EVENT_TYPES

    def test_iet_watchdog_fired_is_valid(self):
        assert "CTS_WF_IET_WATCHDOG_FIRED" in _VALID_EVENT_TYPES

    def test_human_confirmed_is_valid(self):
        assert "CTS_WF_HUMAN_CONFIRMED" in _VALID_EVENT_TYPES

    def test_human_returned_is_valid(self):
        assert "CTS_WF_HUMAN_RETURNED" in _VALID_EVENT_TYPES

    def test_review_timeout_is_valid(self):
        assert "CTS_WF_REVIEW_TIMEOUT" in _VALID_EVENT_TYPES

    def test_human_review_queued_is_valid(self):
        assert "CTS_WF_HUMAN_REVIEW_QUEUED" in _VALID_EVENT_TYPES

    def test_all_valid_event_types_are_registered_messages(self):
        """Guard against write_audit.py's event types drifting from the
        single source of truth in messages.yaml — see messages.md."""
        import yaml
        from pathlib import Path
        messages_path = (
            Path(__file__).resolve().parents[5]
            / "shared" / "messages" / "locales" / "messages.yaml"
        )
        registered = set(yaml.safe_load(messages_path.read_text(encoding="utf-8")).keys())
        # CTS_NGCH_FILED / CTS_VAULT_SYNC_* predate this taxonomy alignment and
        # are used by ngch_filer.py / vault_sync_workflow.py's own event_producer
        # publishes (Kafka), not write_audit — not required to be in messages.yaml.
        exempt = {"CTS_NGCH_FILED", "CTS_VAULT_SYNC_COMPLETE", "CTS_VAULT_SYNC_FAILED"}
        missing = (_VALID_EVENT_TYPES - exempt) - registered
        assert not missing, f"write_audit event types missing from messages.yaml: {missing}"
