"""TDD — PostDatedHoldWorkflow.

Tests: hold registration, sleep-until-release, cancel signal, already-past-date,
workflow ID determinism.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from modules.cts.workflows.postdated_hold_workflow import (
    PostDatedHoldInput,
    PostDatedHoldResult,
    make_hold_workflow_id,
)


class TestMakeHoldWorkflowId:
    def test_id_contains_bank_and_instrument(self):
        wid = make_hold_workflow_id("saraswat", "INS-001")
        assert "saraswat" in wid
        assert "INS-001" in wid

    def test_id_is_deterministic(self):
        assert make_hold_workflow_id("bank", "INS-X") == make_hold_workflow_id("bank", "INS-X")

    def test_id_has_no_spaces(self):
        wid = make_hold_workflow_id("saraswat coop", "INS-001")
        assert " " not in wid

    def test_different_instrument_different_id(self):
        assert make_hold_workflow_id("bank", "INS-1") != make_hold_workflow_id("bank", "INS-2")


class TestPostDatedHoldInput:
    def test_input_construction(self):
        inp = PostDatedHoldInput(
            instrument_id="INS-001",
            bank_id="saraswat",
            release_date=date(2026, 9, 15),
            original_workflow_data={"cheque": "data"},
        )
        assert inp.instrument_id == "INS-001"
        assert inp.release_date == date(2026, 9, 15)


class TestPostDatedHoldResult:
    def test_released_result(self):
        r = PostDatedHoldResult(status="RELEASED", released_at="2026-09-15T00:00:01")
        assert r.status == "RELEASED"

    def test_cancelled_result(self):
        r = PostDatedHoldResult(status="CANCELLED", released_at=None)
        assert r.status == "CANCELLED"
        assert r.released_at is None


class TestPostDatedHoldWorkflowUnit:
    """Unit tests for the workflow logic without Temporal harness."""

    def test_release_days_calculation_positive(self):
        from modules.cts.workflows.postdated_hold_workflow import _days_until_release
        today = date(2026, 8, 12)
        release = date(2026, 9, 15)
        assert _days_until_release(release, reference=today) == 34

    def test_release_days_calculation_zero(self):
        from modules.cts.workflows.postdated_hold_workflow import _days_until_release
        today = date(2026, 9, 15)
        release = date(2026, 9, 15)
        assert _days_until_release(release, reference=today) == 0

    def test_release_days_calculation_past(self):
        from modules.cts.workflows.postdated_hold_workflow import _days_until_release
        today = date(2026, 9, 16)
        release = date(2026, 9, 15)
        assert _days_until_release(release, reference=today) < 0

    def test_hold_workflow_id_pattern(self):
        wid = make_hold_workflow_id("federal-bank", "CHQ-2026-001")
        assert wid.startswith("cts-hold-")

    def test_input_is_frozen(self):
        inp = PostDatedHoldInput(
            instrument_id="INS-001",
            bank_id="bank",
            release_date=date(2026, 9, 15),
            original_workflow_data={},
        )
        with pytest.raises(Exception):
            inp.instrument_id = "changed"  # frozen dataclass


class TestReturnReasonCodeRegistry:
    """Post-dated cheques must NOT have a return reason code."""

    def test_postdated_has_no_return_reason(self):
        from modules.cts.preprocessing.cheque_date_validator import validate_cheque_date
        from datetime import date

        result = validate_cheque_date(
            "15/09/2026",
            stale_days=90,
            reference_date=date(2026, 8, 12),
        )
        assert result.decision == "POST_DATED"
        assert result.return_reason_code is None

    def test_postdated_days_old_is_negative(self):
        from modules.cts.preprocessing.cheque_date_validator import validate_cheque_date
        from datetime import date

        result = validate_cheque_date(
            "15/09/2026",
            stale_days=90,
            reference_date=date(2026, 8, 12),
        )
        assert result.days_old is not None
        assert result.days_old < 0
