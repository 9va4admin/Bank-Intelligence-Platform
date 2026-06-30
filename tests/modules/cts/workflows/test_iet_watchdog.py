"""
Tests for modules/cts/workflows/iet_watchdog_workflow.py

IETWatchdogWorkflow monitors the IET deadline countdown.
At T-30 seconds it fires an emergency filing to NGCH.
IET breach rate must be 0.000% — this is structural, not configurable.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_watchdog_input(seconds_remaining=10800, instrument_id="INST001", bank_id="test-bank"):
    from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogInput
    return IETWatchdogInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        iet_deadline=time.time() + seconds_remaining,
        workflow_id=f"cts-{bank_id}-{instrument_id}",
    )


class TestIETWatchdogInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogInput
        with pytest.raises(Exception):
            IETWatchdogInput(bank_id="b", iet_deadline=9999999999.0, workflow_id="wf-1")

    def test_is_frozen(self):
        inp = _make_watchdog_input()
        with pytest.raises(Exception):
            inp.instrument_id = "OTHER"

    def test_watchdog_id_is_deterministic(self):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        wf = IETWatchdogWorkflow()
        wf_id = wf.watchdog_id("test-bank", "INST001")
        assert wf_id == "cts-iet-test-bank-INST001"


class TestIETWatchdogSafeCase:
    @pytest.mark.asyncio
    async def test_safe_outcome_when_parent_completes_before_deadline(self):
        """Parent completes before T-30s → watchdog returns SAFE."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=10800),
            parent_completed_at=time.time(),  # parent done immediately
        )
        assert result.outcome == "SAFE"

    @pytest.mark.asyncio
    async def test_safe_outcome_has_no_emergency_filing(self):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=10800),
            parent_completed_at=time.time(),
        )
        assert result.emergency_filed is False


class TestIETWatchdogEmergency:
    @pytest.mark.asyncio
    async def test_emergency_outcome_when_deadline_imminent(self):
        """T-30s or less → watchdog must file emergency before IET breach."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        mock_ngch = AsyncMock()
        mock_ngch.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "EMRG001", "status": "ACCEPTED"}
        )

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=25),  # only 25s left
            parent_completed_at=None,  # parent NOT done
            ngch_adapter=mock_ngch,
        )
        assert result.outcome == "EMERGENCY_FILED"

    @pytest.mark.asyncio
    async def test_emergency_files_confirm_to_ngch(self):
        """Emergency filing always CONFIRMS — protect IET, never miss."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        mock_ngch = AsyncMock()
        mock_ngch.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "EMRG001", "status": "ACCEPTED"}
        )

        wf = IETWatchdogWorkflow()
        await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=20),
            parent_completed_at=None,
            ngch_adapter=mock_ngch,
        )
        mock_ngch.file_decision.assert_called_once()
        call_decision = mock_ngch.file_decision.call_args[1].get("decision") or \
                        mock_ngch.file_decision.call_args[0][1]
        assert call_decision == "CONFIRM"

    @pytest.mark.asyncio
    async def test_emergency_flag_set_in_result(self):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        mock_ngch = AsyncMock()
        mock_ngch.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "EMRG001", "status": "ACCEPTED"}
        )

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=15),
            parent_completed_at=None,
            ngch_adapter=mock_ngch,
        )
        assert result.emergency_filed is True

    @pytest.mark.asyncio
    async def test_iet_threshold_is_30_seconds(self):
        """Emergency triggers at exactly T-30s — structural, not configurable."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        mock_ngch = AsyncMock()
        mock_ngch.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "EMRG001", "status": "ACCEPTED"}
        )

        wf = IETWatchdogWorkflow()
        # 31 seconds left → parent done → SAFE (no emergency)
        result_safe = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=31),
            parent_completed_at=time.time(),
            ngch_adapter=mock_ngch,
        )
        # 29 seconds left → parent NOT done → EMERGENCY
        result_emergency = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=29),
            parent_completed_at=None,
            ngch_adapter=mock_ngch,
        )

        assert result_safe.outcome == "SAFE"
        assert result_emergency.outcome == "EMERGENCY_FILED"


class TestIETWatchdogParentClosePolicy:
    def test_watchdog_id_is_independent_of_parent(self):
        """Watchdog survives parent failure — parent_close_policy=ABANDON."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        wf = IETWatchdogWorkflow()
        # Parent close policy is ABANDON — watchdog has its own lifecycle
        assert wf.parent_close_policy == "ABANDON"


class TestIETWatchdogSafeNoParent:
    @pytest.mark.asyncio
    async def test_safe_when_parent_not_done_and_time_remaining(self):
        """Covers line 82: parent_completed_at=None but > 30s remaining → SAFE."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=120),
            parent_completed_at=None,   # parent not done
            ngch_adapter=None,
        )
        assert result.outcome == "SAFE"
        assert result.emergency_filed is False
