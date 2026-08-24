"""
Tests for HoldEscalationWorkflow — time-based escalation chain for held cheques.

Three checkpoints:
  CP1: T+30min from hold placement   → send_hold_reminder (branch)
  CP2: T-60min before IET expiry     → send_hold_critical_alert (ops_manager)
  CP3: T-5min before IET expiry      → send_hold_p0_alert (ops_manager, bypass debouncer)

The `released` signal exits the workflow before any pending checkpoint fires.
IET safety: this workflow is notification-only — never files to NGCH.

Design notes:
  - temporal_env is module-scoped: the Temporal test server starts ONCE for all 7 tests
    instead of once per test (on Windows, each server start takes 30–60s; 7 per-test
    servers hit the 180s per-test timeout before any test even runs)
  - Inputs are built from the server's own clock (temporal_env.get_current_time) to avoid
    drift between real wall-clock time and the test server's internal clock
  - The `held_at` is set in the past (>30min ago) so CP1 fires immediately (no timer wait),
    and `iet_in_seconds=7200` keeps CP2/CP3 guards true while minimising timer waits
  - Each test gets a unique task_queue (uuid-based) so concurrent tests never collide
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from modules.cts.workflows.hold_escalation_workflow import (
    HoldEscalationInput,
    HoldEscalationWorkflow,
)

# Module-level event loop so module-scoped async fixtures work in STRICT mode
pytestmark = [pytest.mark.asyncio(loop_scope="module")]


# ---------------------------------------------------------------------------
# Test activity stubs — capture which checkpoints fired
# ---------------------------------------------------------------------------

_sent_checkpoints: list[str] = []
_reminder_payloads: list[dict] = []
_p0_payloads: list[dict] = []


@activity.defn(name="send_hold_reminder")
async def _fake_reminder(payload: dict) -> None:
    _sent_checkpoints.append(payload["checkpoint"])
    _reminder_payloads.append(payload)


@activity.defn(name="send_hold_critical_alert")
async def _fake_critical(payload: dict) -> None:
    _sent_checkpoints.append(payload["checkpoint"])


@activity.defn(name="send_hold_p0_alert")
async def _fake_p0(payload: dict) -> None:
    _sent_checkpoints.append(payload["checkpoint"])
    _p0_payloads.append(payload)


_FAKE_ACTIVITIES = [_fake_reminder, _fake_critical, _fake_p0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def temporal_env():
    """Single Temporal time-skipping server shared across all tests in this module."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture(autouse=True)
def _reset():
    """Clear captured call state before and after every test (sync — no loop needed)."""
    _sent_checkpoints.clear()
    _reminder_payloads.clear()
    _p0_payloads.clear()
    yield
    _sent_checkpoints.clear()
    _reminder_payloads.clear()
    _p0_payloads.clear()


# ---------------------------------------------------------------------------
# Input builder (async — uses server clock to avoid real-clock drift)
# ---------------------------------------------------------------------------

async def _make_inp(
    temporal_env: WorkflowEnvironment,
    *,
    held_seconds_ago: float = 2000.0,
    iet_in_seconds: float = 7200.0,
) -> HoldEscalationInput:
    """
    Build a HoldEscalationInput from the test server's own clock.

    held_seconds_ago defaults to 2000s (>30min) so the CP1 timer fires immediately
    (sleep_to_30min = max(0, 1800 - 2000) = 0), saving ~30min of time-skip per test.
    """
    server_now = (await temporal_env.get_current_time()).timestamp()
    return HoldEscalationInput(
        instrument_id=f"INS-{uuid.uuid4().hex[:8]}",
        bank_id="saraswat-coop",
        reviewer_id="ops.reviewer@saraswat.coop",
        iet_deadline=server_now + iet_in_seconds,
        held_at=server_now - held_seconds_ago,
        branch_email="branch@saraswat.coop",
        ops_manager_email="ops@saraswat.coop",
    )


def _tq() -> str:
    return f"tq-hold-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHoldEscalationWorkflow:

    @pytest.mark.asyncio(loop_scope="module")
    async def test_all_checkpoints_fire_when_no_release(self, temporal_env):
        """IET 2h away, held >30min ago — all three checkpoints fire without release."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert "30_MIN_REMINDER" in _sent_checkpoints
        assert "T_MINUS_60_MIN" in _sent_checkpoints
        assert "T_MINUS_5_MIN_P0" in _sent_checkpoints

    @pytest.mark.asyncio(loop_scope="module")
    async def test_checkpoints_fired_in_order(self, temporal_env):
        """Chronological order must be CP1 → CP2 → CP3."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert _sent_checkpoints == [
            "30_MIN_REMINDER",
            "T_MINUS_60_MIN",
            "T_MINUS_5_MIN_P0",
        ]

    @pytest.mark.asyncio(loop_scope="module")
    async def test_released_before_cp1_sends_nothing(self, temporal_env):
        """Signal sent immediately on a fresh hold (not yet held 30min) — exits without CP1."""
        # held_seconds_ago=0: instrument just placed on hold → CP1 timer = 1800s
        # Signal arrives before timer fires → should exit with zero notifications
        inp = await _make_inp(temporal_env, held_seconds_ago=0.0)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_env.client.start_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
            await handle.signal(HoldEscalationWorkflow.released)
            await handle.result()

        assert _sent_checkpoints == []

    @pytest.mark.asyncio(loop_scope="module")
    async def test_workflow_completes_without_error(self, temporal_env):
        """Workflow must return None and complete cleanly."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
        assert result is None

    @pytest.mark.asyncio(loop_scope="module")
    async def test_instrument_id_in_reminder_payload(self, temporal_env):
        """CP1 activity must receive the correct instrument_id and bank_id."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert len(_reminder_payloads) == 1
        assert _reminder_payloads[0]["instrument_id"] == inp.instrument_id
        assert _reminder_payloads[0]["bank_id"] == inp.bank_id

    @pytest.mark.asyncio(loop_scope="module")
    async def test_p0_alert_sets_bypass_debouncer(self, temporal_env):
        """P0 alert payload must set bypass_debouncer=True."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert len(_p0_payloads) == 1
        assert _p0_payloads[0]["bypass_debouncer"] is True
        assert _p0_payloads[0]["checkpoint"] == "T_MINUS_5_MIN_P0"

    @pytest.mark.asyncio(loop_scope="module")
    async def test_p0_alert_includes_iet_deadline(self, temporal_env):
        """P0 alert payload must carry the IET deadline so the recipient can display it."""
        inp = await _make_inp(temporal_env)
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=[HoldEscalationWorkflow],
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await temporal_env.client.execute_workflow(
                HoldEscalationWorkflow.run,
                inp,
                id=f"test-hold-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert _p0_payloads[0]["iet_deadline"] == inp.iet_deadline
