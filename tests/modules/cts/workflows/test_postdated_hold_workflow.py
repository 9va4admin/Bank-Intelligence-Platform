"""TDD — PostDatedHoldWorkflow.

Tests: hold registration, sleep-until-release, cancel signal, already-past-date,
workflow ID determinism.
"""
import uuid
import pytest
import pytest_asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from shared.temporal.converter import pydantic_data_converter
from modules.cts.workflows.postdated_hold_workflow import (
    PostDatedHoldInput,
    PostDatedHoldResult,
    PostDatedHoldWorkflow,
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


# ---------------------------------------------------------------------------
# Regression (found live, 2026-09-23): PostDatedHoldWorkflow.run() called
# `await workflow.sleep(timedelta(days=days_remaining))`, which does not exist on
# `temporalio.workflow` in the installed SDK (1.7.1) — confirmed live, the workflow
# task failed with `AttributeError: module 'temporalio.workflow' has no attribute
# 'sleep'` the first time that line ever actually ran, for any release_date more than
# zero days out. None of the tests above exercise workflow.run() against a real
# Temporal workflow environment at all (they test pure helper functions and
# dataclasses only), which is exactly why this was never caught before a live run.
#
# Fixed with `workflow.wait_condition(lambda: self._cancelled, timeout=...)`, which
# also fixes a real behavioural gap the old code had even if workflow.sleep() had
# existed: a signal-driven cancel_hold arriving during the wait now wakes the
# workflow immediately instead of only being checked after a full, uninterruptible
# sleep.
# ---------------------------------------------------------------------------

_stored_holds: list[dict] = []
_cancelled_holds: list[dict] = []


@activity.defn(name="store_postdated_hold")
async def _fake_store_postdated_hold(data: dict) -> None:
    _stored_holds.append(data)


@activity.defn(name="mark_hold_cancelled")
async def _fake_mark_hold_cancelled(data: dict) -> None:
    _cancelled_holds.append(data)


@workflow.defn(name="ChequeProcessingWorkflow")
class _FakeChequeProcessingWorkflow:
    """Stand-in for the real child workflow — PostDatedHoldWorkflow only needs to
    prove it can start one; ChequeProcessingWorkflow's own behaviour is out of scope."""

    @workflow.run
    async def run(self, data: dict) -> dict:
        return {"decision": "STUBBED"}


_FAKE_ACTIVITIES = [_fake_store_postdated_hold, _fake_mark_hold_cancelled]
_FAKE_WORKFLOWS = [PostDatedHoldWorkflow, _FakeChequeProcessingWorkflow]


@pytest_asyncio.fixture(scope="module")
async def temporal_env():
    # PostDatedHoldInput.release_date is a plain `date` field — the default data
    # converter can't encode it (TypeError: Object of type date is not JSON
    # serializable). Use the same pydantic_data_converter the real API/worker use
    # (shared/temporal/converter.py), required for exactly this reason there too.
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        yield env


@pytest.fixture(autouse=True)
def _reset_postdated_hold_state():
    _stored_holds.clear()
    _cancelled_holds.clear()
    yield
    _stored_holds.clear()
    _cancelled_holds.clear()


def _tq() -> str:
    return f"tq-postdated-{uuid.uuid4().hex[:8]}"


class TestPostDatedHoldWorkflowRealRun:
    """Runs PostDatedHoldWorkflow.run() for real against a Temporal time-skipping
    server — the class of test that would have caught the workflow.sleep() bug."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_sleep_to_release_date_completes_and_releases(self, temporal_env):
        """The direct regression case: release_date 2 days out, so days_remaining > 0
        and the wait_condition/timeout path actually executes. Before the fix, this
        raised AttributeError inside the workflow task and execute_workflow below
        would fail with a WorkflowFailureError instead of returning a result."""
        server_now = await temporal_env.get_current_time()
        release_date = (server_now + timedelta(days=2)).date()
        inp = PostDatedHoldInput(
            instrument_id=f"INS-{uuid.uuid4().hex[:8]}",
            bank_id="kbl",
            release_date=release_date,
            original_workflow_data={"instrument_id": "INS-001"},
        )
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=_FAKE_WORKFLOWS,
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                PostDatedHoldWorkflow.run,
                inp,
                id=f"test-postdated-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert result.status == "RELEASED"
        assert result.released_at is not None
        assert len(_stored_holds) == 1
        assert _stored_holds[0]["instrument_id"] == inp.instrument_id

    @pytest.mark.asyncio(loop_scope="module")
    async def test_cancel_signal_wakes_the_wait_before_the_release_date(self, temporal_env):
        """release_date is 30 days out; cancel_hold is signalled almost immediately.
        Proves the wait is interruptible (the behavioural improvement over the old,
        never-actually-run workflow.sleep() call), not just that the API name changed."""
        server_now = await temporal_env.get_current_time()
        release_date = (server_now + timedelta(days=30)).date()
        inp = PostDatedHoldInput(
            instrument_id=f"INS-{uuid.uuid4().hex[:8]}",
            bank_id="kbl",
            release_date=release_date,
            original_workflow_data={"instrument_id": "INS-002"},
        )
        tq = _tq()
        async with Worker(
            temporal_env.client,
            task_queue=tq,
            workflows=_FAKE_WORKFLOWS,
            activities=_FAKE_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_env.client.start_workflow(
                PostDatedHoldWorkflow.run,
                inp,
                id=f"test-postdated-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
            await handle.signal(PostDatedHoldWorkflow.cancel_hold, "drawer stop-payment")
            result = await handle.result()

        assert result.status == "CANCELLED"
        assert result.released_at is None
        assert len(_cancelled_holds) == 1
        assert _cancelled_holds[0]["cancel_reason"] == "drawer stop-payment"
