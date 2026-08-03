"""Tests for SMB forwarding activities — IET headroom, forwarding log, audit."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _future_deadline(seconds: float = 600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _past_deadline(seconds: float = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# validate_smb_forwarding_window
# ---------------------------------------------------------------------------

class TestValidateSmbForwardingWindow:
    @pytest.mark.asyncio
    async def test_sufficient_headroom_returns_safe(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(600)
            )
        assert result["safe_to_forward"] is True
        assert result["reason"] == "OK"
        assert result["iet_seconds_remaining"] > 0
        assert result["forwarding_id"]  # UUID assigned

    @pytest.mark.asyncio
    async def test_insufficient_headroom_blocks_forwarding(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            # Only 100s remaining, threshold is 300
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(100)
            )
        assert result["safe_to_forward"] is False
        assert "INSUFFICIENT_IET_HEADROOM" in result["reason"]

    @pytest.mark.asyncio
    async def test_expired_deadline_blocks_forwarding(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _past_deadline(60)
            )
        assert result["safe_to_forward"] is False

    @pytest.mark.asyncio
    async def test_invalid_deadline_format_returns_safe_false(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", "NOT-A-DATE"
            )
        assert result["safe_to_forward"] is False
        assert "INVALID_IET_DEADLINE" in result["reason"]

    @pytest.mark.asyncio
    async def test_default_headroom_300_when_config_returns_none(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=None)
        ):
            # 200s remaining < 300s default
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(200)
            )
        assert result["safe_to_forward"] is False

    @pytest.mark.asyncio
    async def test_default_headroom_300_when_config_key_unseeded(self):
        """Regression: config_service.get() raises ConfigKeyNotFoundError for an
        unseeded Layer 3 key rather than returning None -- this sits on the
        IET-safety-critical path and must degrade to the documented default
        (300s), never crash the whole forwarding decision."""
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get",
            new=AsyncMock(side_effect=Exception("Config key not found")),
        ):
            # 200s remaining < 300s default
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(200)
            )
        assert result["safe_to_forward"] is False
        assert "INSUFFICIENT_IET_HEADROOM" in result["reason"]

    @pytest.mark.asyncio
    async def test_zulu_deadline_parsed_correctly(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            # Use Z suffix (common ISO format)
            deadline = (
                datetime.now(timezone.utc) + timedelta(seconds=600)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", deadline
            )
        assert result["safe_to_forward"] is True

    @pytest.mark.asyncio
    async def test_smb_active_queried_from_db_when_injected(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        mock_db = AsyncMock()
        mock_db.fetchval = AsyncMock(return_value=False)  # SMB suspended
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(600), db=mock_db
            )
        assert result["safe_to_forward"] is False
        assert "SMB_SUSPENDED" in result["reason"]
        mock_db.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_smb_active_defaults_true_when_db_unavailable(self):
        """An outage on this check must never itself become the reason a live
        SMB gets blocked -- IET safety is the higher-priority invariant."""
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        mock_db = AsyncMock()
        mock_db.fetchval = AsyncMock(side_effect=Exception("DB unreachable"))
        with patch(
            "shared.config.config_service.config_service.get", new=AsyncMock(return_value=300)
        ):
            result = await validate_smb_forwarding_window(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(600), db=mock_db
            )
        assert result["safe_to_forward"] is True


# ---------------------------------------------------------------------------
# write_forwarding_log_start
# ---------------------------------------------------------------------------

class TestWriteForwardingLogStart:
    @pytest.mark.asyncio
    async def test_returns_expected_fields(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_start,
        )
        result = await write_forwarding_log_start(
            "fwd-uuid-001", "CHQ-001", "sb-bank", "smb-001", "600123", _future_deadline(600)
        )
        assert result["forwarding_id"] == "fwd-uuid-001"
        assert result["forwarding_status"] == "FORWARDING"
        assert result["instrument_id"] == "CHQ-001"
        assert result["bank_id"] == "sb-bank"
        assert result["sub_member_id"] == "smb-001"
        assert result["micr_prefix_matched"] == "600123"
        assert result["written_at"]

    @pytest.mark.asyncio
    async def test_inserts_via_injected_db(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_start,
        )
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=None)
        await write_forwarding_log_start(
            "fwd-uuid-001", "CHQ-001", "sb-bank", "smb-001", "600123",
            _future_deadline(600), db=mock_db,
        )
        mock_db.execute.assert_awaited_once()
        args = mock_db.execute.call_args.args
        assert args[1] == "fwd-uuid-001"
        assert args[2] == "sb-bank"
        assert args[3] == "smb-001"

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_db_insert_fails(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_start,
        )
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB unreachable"))
        result = await write_forwarding_log_start(
            "fwd-uuid-001", "CHQ-001", "sb-bank", "smb-001", "600123",
            _future_deadline(600), db=mock_db,
        )
        assert result["forwarding_status"] == "FORWARDING"  # still returns, never raises


# ---------------------------------------------------------------------------
# write_forwarding_log_complete
# ---------------------------------------------------------------------------

class TestWriteForwardingLogComplete:
    @pytest.mark.asyncio
    async def test_completed_status_on_stp_confirm(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"
        assert result["terminal_decision"] == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_failed_status_on_iet_emergency(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete(
            "fwd-uuid-001", "sb-bank", "IET_EMERGENCY", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_completed_status_on_stp_return(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete(
            "fwd-uuid-001", "sb-bank", "STP_RETURN", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_completed_status_on_human_review(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete(
            "fwd-uuid-001", "sb-bank", "HUMAN_REVIEW", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_updates_via_injected_db(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=None)
        await write_forwarding_log_complete(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "smb-wf-id-001", db=mock_db,
        )
        mock_db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# write_smb_forwarding_audit
# ---------------------------------------------------------------------------

class TestWriteSmbForwardingAudit:
    @pytest.mark.asyncio
    async def test_returns_audit_event_id(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        mock_immudb = MagicMock()
        mock_immudb.write_event = MagicMock(return_value={"tx_id": 1})
        result = await write_smb_forwarding_audit(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "COMPLETED", immudb_client=mock_immudb,
        )
        assert result["event_type"] == "CTS_SMB_CHEQUE_FORWARDED"
        assert result["written"] is True
        assert result["audit_event_id"]
        mock_immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_event_has_correct_payload(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        mock_immudb = MagicMock()
        mock_immudb.write_event = MagicMock(return_value={"tx_id": 1})
        result = await write_smb_forwarding_audit(
            "fwd-uuid-999", "sb-bank", "IET_EMERGENCY", "SHORT_CIRCUIT_IET_HEADROOM",
            immudb_client=mock_immudb,
        )
        assert result["written"] is True
        assert result["audit_event_id"]
        payload = mock_immudb.write_event.call_args.args[0]
        assert payload["payload"]["forwarding_id"] == "fwd-uuid-999"
        assert payload["payload"]["terminal_decision"] == "IET_EMERGENCY"

    @pytest.mark.asyncio
    async def test_degrades_gracefully_without_immudb_client(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        result = await write_smb_forwarding_audit(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "COMPLETED",
        )
        assert result["written"] is False
        assert result["audit_event_id"]  # event still constructed, just not persisted

    @pytest.mark.asyncio
    async def test_degrades_gracefully_when_immudb_write_fails(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        mock_immudb = MagicMock()
        mock_immudb.write_event = MagicMock(side_effect=Exception("immudb unreachable"))
        result = await write_smb_forwarding_audit(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "COMPLETED", immudb_client=mock_immudb,
        )
        assert result["written"] is False
