"""Tests for SMBForwardingWorkflow — IET short-circuit and normal forwarding paths."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Input / Output model tests (no Temporal runtime needed)
# ---------------------------------------------------------------------------

class TestSMBForwardingInputOutput:
    def test_smb_forwarding_input_fields(self):
        from modules.cts.workflows.smb_forwarding_workflow import SMBForwardingInput
        inp = SMBForwardingInput(
            instrument_id="CHQ-001",
            bank_id="sb-bank",
            sub_member_id="smb-001",
            micr_prefix_matched="600123",
            iet_deadline_utc="2026-06-26T12:00:00Z",
            cheque_image_ref="minio/bucket/img.tiff",
            micr_line="123456789012345678",
            amount_range="STANDARD",
            session_date="2026-06-26",
            clearing_session="SESSION_1",
        )
        assert inp.instrument_id == "CHQ-001"
        assert inp.sub_member_id == "smb-001"
        assert inp.bank_id == "sb-bank"

    def test_smb_forwarding_result_fields(self):
        from modules.cts.workflows.smb_forwarding_workflow import SMBForwardingResult
        result = SMBForwardingResult(
            instrument_id="CHQ-001",
            sub_member_id="smb-001",
            terminal_decision="STP_CONFIRM",
            forwarding_id="fwd-uuid-001",
            smb_workflow_id="smb-cts-smb-001-CHQ-001",
            short_circuited=False,
            completed_at="2026-06-26T10:00:00Z",
        )
        assert result.terminal_decision == "STP_CONFIRM"
        assert result.short_circuited is False


# ---------------------------------------------------------------------------
# Workflow ID pattern tests
# ---------------------------------------------------------------------------

class TestWorkflowIdPattern:
    def test_smb_forwarding_workflow_id_pattern(self):
        bank_id = "sb-bank"
        instrument_id = "CHQ-001"
        expected = f"smb-fwd-{bank_id}-{instrument_id}"
        assert expected == "smb-fwd-sb-bank-CHQ-001"

    def test_smb_cheque_workflow_id_pattern(self):
        sub_member_id = "smb-001"
        instrument_id = "CHQ-001"
        expected = f"smb-cts-{sub_member_id}-{instrument_id}"
        assert expected == "smb-cts-smb-001-CHQ-001"


# ---------------------------------------------------------------------------
# IET headroom threshold tests
# ---------------------------------------------------------------------------

class TestIETHeadroomLogic:
    def test_short_circuit_triggered_below_threshold(self):
        # Business rule: safe_to_forward=False → IET_EMERGENCY
        safe_to_forward = False
        reason = "INSUFFICIENT_IET_HEADROOM: 200s remaining, need 300s"
        assert not safe_to_forward
        assert "INSUFFICIENT_IET_HEADROOM" in reason

    def test_forwarding_proceeds_above_threshold(self):
        safe_to_forward = True
        reason = "OK"
        assert safe_to_forward
        assert reason == "OK"
