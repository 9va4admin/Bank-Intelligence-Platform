"""Tests for SMB forwarding activities — IET headroom, forwarding log, audit."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


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
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = 300
            result = await validate_smb_forwarding_window.__wrapped__(
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
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = 300
            # Only 100s remaining, threshold is 300
            result = await validate_smb_forwarding_window.__wrapped__(
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
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = 300
            result = await validate_smb_forwarding_window.__wrapped__(
                "CHQ-001", "sb-bank", "smb-001", _past_deadline(60)
            )
        assert result["safe_to_forward"] is False

    @pytest.mark.asyncio
    async def test_invalid_deadline_format_returns_safe_false(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = 300
            result = await validate_smb_forwarding_window.__wrapped__(
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
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = None  # no config → default 300
            # 200s remaining < 300s default
            result = await validate_smb_forwarding_window.__wrapped__(
                "CHQ-001", "sb-bank", "smb-001", _future_deadline(200)
            )
        assert result["safe_to_forward"] is False

    @pytest.mark.asyncio
    async def test_zulu_deadline_parsed_correctly(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
        )
        with patch(
            "modules.cts.workflows.activities.smb_forwarding_activities.config_service"
        ) as mock_cfg:
            mock_cfg.get.return_value = 300
            # Use Z suffix (common ISO format)
            deadline = (
                datetime.now(timezone.utc) + timedelta(seconds=600)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            result = await validate_smb_forwarding_window.__wrapped__(
                "CHQ-001", "sb-bank", "smb-001", deadline
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
        result = await write_forwarding_log_start.__wrapped__(
            "fwd-uuid-001", "CHQ-001", "sb-bank", "smb-001", "600123", _future_deadline(600)
        )
        assert result["forwarding_id"] == "fwd-uuid-001"
        assert result["forwarding_status"] == "FORWARDING"
        assert result["instrument_id"] == "CHQ-001"
        assert result["bank_id"] == "sb-bank"
        assert result["sub_member_id"] == "smb-001"
        assert result["micr_prefix_matched"] == "600123"
        assert result["written_at"]


# ---------------------------------------------------------------------------
# write_forwarding_log_complete
# ---------------------------------------------------------------------------

class TestWriteForwardingLogComplete:
    @pytest.mark.asyncio
    async def test_completed_status_on_stp_confirm(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete.__wrapped__(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"
        assert result["terminal_decision"] == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_failed_status_on_iet_emergency(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete.__wrapped__(
            "fwd-uuid-001", "sb-bank", "IET_EMERGENCY", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_completed_status_on_stp_return(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete.__wrapped__(
            "fwd-uuid-001", "sb-bank", "STP_RETURN", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_completed_status_on_human_review(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete,
        )
        result = await write_forwarding_log_complete.__wrapped__(
            "fwd-uuid-001", "sb-bank", "HUMAN_REVIEW", "smb-wf-id-001"
        )
        assert result["forwarding_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# write_smb_forwarding_audit
# ---------------------------------------------------------------------------

class TestWriteSmbForwardingAudit:
    @pytest.mark.asyncio
    async def test_returns_audit_event_id(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        result = await write_smb_forwarding_audit.__wrapped__(
            "fwd-uuid-001", "sb-bank", "STP_CONFIRM", "COMPLETED"
        )
        assert result["event_type"] == "SMB_CHEQUE_FORWARDED"
        assert result["written"] is True
        assert result["audit_event_id"]

    @pytest.mark.asyncio
    async def test_audit_event_has_correct_payload(self):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit,
        )
        result = await write_smb_forwarding_audit.__wrapped__(
            "fwd-uuid-999", "sb-bank", "IET_EMERGENCY", "SHORT_CIRCUIT_IET_HEADROOM"
        )
        assert result["written"] is True
        assert result["audit_event_id"]
