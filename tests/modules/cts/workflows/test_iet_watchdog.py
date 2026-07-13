"""
Tests for modules/cts/workflows/iet_watchdog_workflow.py

IETWatchdogWorkflow monitors the IET deadline countdown.
At T-30 seconds it fires an emergency filing to NGCH.
IET breach rate must be 0.000% — this is structural, not configurable.
"""
import time
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


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
    async def test_emergency_files_confirm_when_no_decision_ever_signalled(self):
        """No parent decision was ever reached — CONFIRM is the safe fallback,
        matching RBI's own deemed-approval default for a missed IET."""
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
    async def test_emergency_files_the_signalled_decision_not_hardcoded_confirm(self):
        """ASTRA-02 regression guard: if the parent already decided RETURN (e.g.
        fraud, stop-payment, frozen account) and just hasn't finished filing when
        T-30s hits, the watchdog must file RETURN — never override that with
        CONFIRM. Auto-paying a cheque the platform already flagged as invalid is
        exactly the 'deemed approval' loss the watchdog exists to prevent."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow

        mock_ngch = AsyncMock()
        mock_ngch.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "EMRG001", "status": "ACCEPTED"}
        )

        wf = IETWatchdogWorkflow()
        result = await wf.run_with_mocks(
            _make_watchdog_input(seconds_remaining=20),
            parent_completed_at=None,
            ngch_adapter=mock_ngch,
            signaled_decision="RETURN",
        )
        call_decision = mock_ngch.file_decision.call_args[1].get("decision") or \
                        mock_ngch.file_decision.call_args[0][1]
        assert call_decision == "RETURN"
        assert result.outcome == "EMERGENCY_FILED"

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


# --------------------------------------------------------------------------- #
# Real Temporal environment — exercises the actual @workflow.run entry point,
# not run_with_mocks(). This is the gap that let ASTRA-02 ship undetected:
# every prior test in this file only called run_with_mocks().
# --------------------------------------------------------------------------- #

_ngch_calls: list[dict] = []
_audit_calls: list[dict] = []


def _dget(inp, key):
    return inp[key] if isinstance(inp, dict) else getattr(inp, key)


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch(inp):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
    # This installed temporalio has no pydantic-aware data converter (a separate,
    # pre-existing gap — see project memory), so Pydantic activity inputs arrive
    # as plain dicts rather than reconstructed NGCHFilerInput. Handle both shapes.
    decision = _dget(inp, "decision")
    instrument_id = _dget(inp, "instrument_id")
    _ngch_calls.append({"decision": decision, "instrument_id": instrument_id})
    return NGCHFilerResult(acknowledgement_id="TEST-ACK", status="ACCEPTED", filed_decision=decision)


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch_duplicate(inp):
    from modules.cts.mcp.ngch_adapter import DuplicateFilingError
    _ngch_calls.append({"decision": _dget(inp, "decision"), "instrument_id": _dget(inp, "instrument_id")})
    raise DuplicateFilingError("already filed by parent")


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch_unavailable(inp):
    from modules.cts.mcp.ngch_adapter import NGCHUnavailableError
    _ngch_calls.append({"decision": _dget(inp, "decision"), "instrument_id": _dget(inp, "instrument_id")})
    raise NGCHUnavailableError("ngch genuinely down")


@activity.defn(name="write_audit")
async def _fake_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    _audit_calls.append({
        "event_type": _dget(inp, "event_type"),
        "instrument_id": _dget(inp, "instrument_id"),
    })
    return WriteAuditResult(success=True, immudb_tx_id="TEST-TX")


@pytest_asyncio.fixture()
async def temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture(autouse=True)
def _reset_ngch_calls():
    _ngch_calls.clear()
    _audit_calls.clear()
    yield
    _ngch_calls.clear()
    _audit_calls.clear()


class TestIETWatchdogRealWorkflowRun:
    """Drives IETWatchdogWorkflow.run() (the real @workflow.run) through an
    actual Temporal Worker + time-skipping test server — signals included."""

    @pytest.mark.asyncio
    async def test_real_run_emergency_files_signalled_decision_not_confirm(self, temporal_env):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"
        wf_id = f"cts-iet-{bank_id}-{instrument_id}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[IETWatchdogWorkflow],
            activities=[_fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            handle = await temporal_env.client.start_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instrument_id,
                    bank_id=bank_id,
                    iet_deadline=(await now()).timestamp() + 90,
                    workflow_id=f"cts-{bank_id}-{instrument_id}",
                ),
                id=wf_id,
                task_queue=task_queue,
            )
            # Parent already decided RETURN (fraud) but hasn't finished filing.
            await handle.signal(IETWatchdogWorkflow.decision_ready, "RETURN")

            result = await handle.result()

        assert result.outcome == "EMERGENCY_FILED"
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "RETURN"
        # CRITICAL-2 (cts-workflow-reviewer): emergency filing must be audited —
        # the single highest-stakes action in the platform can't be log-only.
        assert len(_audit_calls) == 1
        assert _audit_calls[0]["event_type"] == "CTS_IET_EMERGENCY_FILED"

    @pytest.mark.asyncio
    async def test_real_run_stands_down_when_filing_complete_signalled(self, temporal_env):
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"
        wf_id = f"cts-iet-{bank_id}-{instrument_id}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[IETWatchdogWorkflow],
            activities=[_fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            handle = await temporal_env.client.start_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instrument_id,
                    bank_id=bank_id,
                    iet_deadline=(await now()).timestamp() + 90,
                    workflow_id=f"cts-{bank_id}-{instrument_id}",
                ),
                id=wf_id,
                task_queue=task_queue,
            )
            # Parent filed on its own, well before the emergency window.
            await handle.signal(IETWatchdogWorkflow.decision_ready, "CONFIRM")
            await handle.signal(IETWatchdogWorkflow.filing_complete)

            result = await handle.result()

        assert result.outcome == "SAFE"
        assert result.emergency_filed is False
        assert len(_ngch_calls) == 0   # never files — parent already handled it
        assert len(_audit_calls) == 0  # nothing to audit — parent's own write_audit covers it

    @pytest.mark.asyncio
    async def test_real_run_falls_back_to_confirm_when_never_signalled(self, temporal_env):
        """No decision_ready() ever arrives — genuinely no info from the parent.
        CONFIRM is still the correct fallback here (matches RBI deemed-approval)."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"
        wf_id = f"cts-iet-{bank_id}-{instrument_id}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[IETWatchdogWorkflow],
            activities=[_fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            handle = await temporal_env.client.start_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instrument_id,
                    bank_id=bank_id,
                    iet_deadline=(await now()).timestamp() + 90,
                    workflow_id=f"cts-{bank_id}-{instrument_id}",
                ),
                id=wf_id,
                task_queue=task_queue,
            )
            result = await handle.result()

        assert result.outcome == "EMERGENCY_FILED"
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "CONFIRM"


class TestIETWatchdogEmergencyFilingRace:
    """CRITICAL-1 (cts-workflow-reviewer): the bare `except Exception` in the
    original fix conflated a safe duplicate-filing race with a genuine NGCH
    failure — both landed on outcome=SAFE. These prove the two are now told
    apart: DuplicateFilingError is the only case that's actually safe."""

    @pytest.mark.asyncio
    async def test_duplicate_filing_error_is_safe_no_audit_no_raise(self, temporal_env):
        """The parent (or HumanReviewWorkflow) won the race and already filed —
        NGCH's 409 surfaces as DuplicateFilingError. Genuinely safe: the filer's
        own write_audit already recorded the real decision, so the watchdog
        must not raise and must not write a second, redundant audit event."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[IETWatchdogWorkflow],
            activities=[_fake_file_to_ngch_duplicate, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            result = await temporal_env.client.execute_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instrument_id,
                    bank_id=bank_id,
                    iet_deadline=(await now()).timestamp() + 90,
                    workflow_id=f"cts-{bank_id}-{instrument_id}",
                ),
                id=f"cts-iet-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )

        assert result.outcome == "SAFE"
        assert result.emergency_filed is False
        assert len(_audit_calls) == 0

    @pytest.mark.asyncio
    async def test_genuine_ngch_failure_raises_and_is_audited_not_reported_safe(self, temporal_env):
        """NGCH is genuinely unreachable (retries exhausted) — the platform's
        last line of defence just failed to file before the IET deadline. This
        must never be silently reported as SAFE: it has to be audited and the
        workflow must end in failure so Temporal surfaces it."""
        from temporalio.client import WorkflowFailureError
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[IETWatchdogWorkflow],
            activities=[_fake_file_to_ngch_unavailable, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            with pytest.raises(WorkflowFailureError):
                await temporal_env.client.execute_workflow(
                    IETWatchdogWorkflow.run,
                    IETWatchdogInput(
                        instrument_id=instrument_id,
                        bank_id=bank_id,
                        iet_deadline=(await now()).timestamp() + 90,
                        workflow_id=f"cts-{bank_id}-{instrument_id}",
                    ),
                    id=f"cts-iet-{bank_id}-{instrument_id}",
                    task_queue=task_queue,
                )

        assert len(_audit_calls) == 1
        assert _audit_calls[0]["event_type"] == "CTS_IET_EMERGENCY_FILED"
