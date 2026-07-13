"""Tests for HumanReviewWorkflow — signal path, timeout, audit, NGCH filing."""
import time
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from modules.cts.workflows.human_review_workflow import (
    HumanReviewInput,
    HumanReviewWorkflow,
    HumanReviewResult,
    ReviewDecision,
    push_to_review_queue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(**kwargs):
    defaults = dict(
        instrument_id="CHQ-TEST-001",
        bank_id="test-bank",
        workflow_id="cts-test-bank-CHQ-TEST-001",
        context_bundle={"fraud_score": 0.85, "ocr_confidence": 0.92},
        iet_deadline=time.time() + 3600,
    )
    defaults.update(kwargs)
    return HumanReviewInput(**defaults)


def _make_decision(action="CONFIRM"):
    return ReviewDecision(
        action=action,
        reason="Verified with branch manager",
        reviewer_id="reviewer-001",
        decided_at=time.time(),
    )


def _make_ngch():
    ngch = AsyncMock()
    ngch.file_decision.return_value = {"acknowledgement_id": "ACK-001", "status": "FILED"}
    return ngch


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TestHumanReviewInput:
    def test_requires_instrument_id(self):
        with pytest.raises(Exception):
            HumanReviewInput(bank_id="b", workflow_id="w",
                             context_bundle={}, iet_deadline=1.0)

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.instrument_id = "other"

    def test_workflow_id_pattern(self):
        wf = HumanReviewWorkflow()
        wid = wf.workflow_id("test-bank", "CHQ-001")
        assert wid == "cts-humanreview-test-bank-CHQ-001"

    def test_workflow_id_unique_per_instrument(self):
        wf = HumanReviewWorkflow()
        assert wf.workflow_id("bank", "A") != wf.workflow_id("bank", "B")


# ---------------------------------------------------------------------------
# push_to_review_queue
# ---------------------------------------------------------------------------

class TestPushToReviewQueue:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_topic(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(), event_producer=producer)
        topic = producer.publish.call_args.kwargs["topic"]
        assert topic == "cts.human.review.test-bank"

    @pytest.mark.asyncio
    async def test_publishes_instrument_id(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(instrument_id="CHQ-XYZ"), event_producer=producer)
        payload = producer.publish.call_args.kwargs["payload"]
        assert payload["instrument_id"] == "CHQ-XYZ"

    @pytest.mark.asyncio
    async def test_publishes_schema_version(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(), event_producer=producer)
        assert producer.publish.call_args.kwargs["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Signal path — reviewer confirms
# ---------------------------------------------------------------------------

class TestReviewerConfirms:
    @pytest.mark.asyncio
    async def test_outcome_reviewer_confirmed(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.outcome == "REVIEWER_CONFIRMED"

    @pytest.mark.asyncio
    async def test_filed_decision_is_confirm(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.filed_decision == "CONFIRM"

    @pytest.mark.asyncio
    async def test_not_timed_out(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_reviewer_id_in_result(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.reviewer_id == "reviewer-001"

    @pytest.mark.asyncio
    async def test_files_to_ngch(self):
        ngch = _make_ngch()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=ngch,
            injected_decision=_make_decision("CONFIRM"),
        )
        ngch.file_decision.assert_called_once()
        _, kwargs = ngch.file_decision.call_args
        assert kwargs["decision"] == "CONFIRM"


# ---------------------------------------------------------------------------
# Signal path — reviewer returns
# ---------------------------------------------------------------------------

class TestReviewerReturns:
    @pytest.mark.asyncio
    async def test_outcome_reviewer_returned(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("RETURN"),
        )
        assert result.outcome == "REVIEWER_RETURNED"

    @pytest.mark.asyncio
    async def test_filed_decision_is_return(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("RETURN"),
        )
        assert result.filed_decision == "RETURN"


# ---------------------------------------------------------------------------
# Timeout path
# ---------------------------------------------------------------------------

class TestReviewTimeout:
    @pytest.mark.asyncio
    async def test_outcome_timeout_auto_returned(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.outcome == "TIMEOUT_AUTO_RETURNED"

    @pytest.mark.asyncio
    async def test_timed_out_flag_set(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_timeout_files_return_to_ngch(self):
        ngch = _make_ngch()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=ngch,
            simulate_timeout=True,
        )
        _, kwargs = ngch.file_decision.call_args
        assert kwargs["decision"] == "RETURN"

    @pytest.mark.asyncio
    async def test_timeout_reason_set(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert "timeout" in result.reason

    @pytest.mark.asyncio
    async def test_timeout_reviewer_id_is_none(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.reviewer_id is None


# ---------------------------------------------------------------------------
# Audit write
# ---------------------------------------------------------------------------

class TestAuditWrite:
    @pytest.mark.asyncio
    async def test_audit_written_on_confirm(self):
        audit = AsyncMock()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=audit,
            injected_decision=_make_decision("CONFIRM"),
        )
        audit.write.assert_called_once()
        kwargs = audit.write.call_args.kwargs
        assert kwargs["event_type"] == "CTS_HUMAN_REVIEW_DECIDED"

    @pytest.mark.asyncio
    async def test_audit_written_on_timeout(self):
        audit = AsyncMock()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=audit,
            simulate_timeout=True,
        )
        audit.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_audit_writer_does_not_crash(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=None,
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.outcome == "REVIEWER_CONFIRMED"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class TestHumanReviewResult:
    def test_result_is_frozen(self):
        r = HumanReviewResult(
            instrument_id="X", outcome="REVIEWER_CONFIRMED",
            filed_decision="CONFIRM", acknowledgement_id="ACK",
        )
        with pytest.raises(Exception):
            r.outcome = "other"

    def test_result_has_instrument_id(self):
        r = HumanReviewResult(
            instrument_id="CHQ-001", outcome="REVIEWER_RETURNED",
            filed_decision="RETURN", acknowledgement_id="ACK",
        )
        assert r.instrument_id == "CHQ-001"


class TestHumanReviewMissingBranches:
    def test_receive_decision_sets_internal_state(self):
        """Covers line 105: receive_decision() signal handler stores the decision."""
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow, ReviewDecision
        wf = HumanReviewWorkflow()
        decision = ReviewDecision(action="CONFIRM", reason="looks fine", reviewer_id="rev-001", decided_at=1234567890.0)
        wf.receive_decision(decision)
        assert wf._decision is decision

    @pytest.mark.asyncio
    async def test_no_injected_decision_no_timeout_falls_through(self):
        """Covers line 134: else branch — no injected decision and not simulating timeout."""
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
        from unittest.mock import AsyncMock

        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=None,
            simulate_timeout=False,
        )
        # No decision → treated as timeout path (_decision=None)
        assert result.outcome == "TIMEOUT_AUTO_RETURNED"


# --------------------------------------------------------------------------- #
# Real Temporal environment — exercises the actual @workflow.run entry point.
# Before this fix, HumanReviewWorkflow had no @workflow.defn at all, so none
# of this could ever run: apps/api/routers/cts.py already sends a real signal
# (handle.signal(HumanReviewWorkflow.receive_decision, ...)) to a workflow ID
# that could never actually be running.
# --------------------------------------------------------------------------- #

_queue_calls: list[dict] = []
_ngch_calls: list[dict] = []
_audit_calls: list[dict] = []


def _dget(inp, key):
    return inp[key] if isinstance(inp, dict) else getattr(inp, key)


@activity.defn(name="push_to_review_queue")
async def _fake_push_to_review_queue(inp):
    _queue_calls.append({"instrument_id": _dget(inp, "instrument_id")})


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch(inp):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
    decision = _dget(inp, "decision")
    _ngch_calls.append({"decision": decision, "instrument_id": _dget(inp, "instrument_id")})
    return NGCHFilerResult(acknowledgement_id="TEST-ACK", status="ACCEPTED", filed_decision=decision)


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch_watchdog_won_race(inp):
    from modules.cts.mcp.ngch_adapter import DuplicateFilingError
    _ngch_calls.append({"decision": _dget(inp, "decision"), "instrument_id": _dget(inp, "instrument_id")})
    raise DuplicateFilingError("watchdog already filed this decision")


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
def _reset_call_logs():
    _queue_calls.clear()
    _ngch_calls.clear()
    _audit_calls.clear()
    yield
    _queue_calls.clear()
    _ngch_calls.clear()
    _audit_calls.clear()


def _real_input(bank_id, instrument_id, deadline_seconds=3600):
    return HumanReviewInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        workflow_id=f"cts-{bank_id}-{instrument_id}",
        context_bundle={"fraud_score": 0.85},
        iet_deadline=time.time() + deadline_seconds,
    )


class TestHumanReviewRealWorkflowRun:
    @pytest.mark.asyncio
    async def test_real_run_files_reviewer_return_decision(self, temporal_env):
        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[HumanReviewWorkflow],
            activities=[_fake_push_to_review_queue, _fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _real_input(bank_id, instrument_id),
                id=f"cts-humanreview-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )
            await handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="RETURN", reason="Signature mismatch confirmed",
                    reviewer_id="reviewer-007", decided_at=time.time(),
                ),
            )
            result = await handle.result()

        assert result.outcome == "REVIEWER_RETURNED"
        assert result.timed_out is False
        assert len(_queue_calls) == 1
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "RETURN"
        assert len(_audit_calls) == 1
        assert _audit_calls[0]["event_type"] == "CTS_HUMAN_REVIEW_DECIDED"

    @pytest.mark.asyncio
    async def test_real_run_timeout_auto_returns(self, temporal_env):
        """No signal ever arrives — the real 55-minute timeout fires (time-skipped)."""
        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[HumanReviewWorkflow],
            activities=[_fake_push_to_review_queue, _fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _real_input(bank_id, instrument_id),
                id=f"cts-humanreview-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )
            result = await handle.result()

        assert result.outcome == "TIMEOUT_AUTO_RETURNED"
        assert result.timed_out is True
        assert _ngch_calls[0]["decision"] == "RETURN"

    @pytest.mark.asyncio
    async def test_real_run_signals_sibling_watchdog_which_stands_down(self, temporal_env):
        """ASTRA-02 close-the-loop proof: a real IETWatchdogWorkflow sibling,
        signalled by HumanReviewWorkflow once the reviewer decides, must stand
        down (SAFE, no emergency file) instead of racing to its own T-30s fire."""
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow, IETWatchdogInput

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client,
            task_queue=task_queue,
            workflows=[HumanReviewWorkflow, IETWatchdogWorkflow],
            activities=[_fake_push_to_review_queue, _fake_file_to_ngch, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            now = temporal_env.get_current_time
            deadline = (await now()).timestamp() + 90
            watchdog_handle = await temporal_env.client.start_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    iet_deadline=deadline, workflow_id=f"cts-{bank_id}-{instrument_id}",
                ),
                id=f"cts-iet-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )
            review_handle = await temporal_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _real_input(bank_id, instrument_id, deadline_seconds=90),
                id=f"cts-humanreview-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )
            await review_handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="CONFIRM", reason="Branch manager verified",
                    reviewer_id="reviewer-009", decided_at=time.time(),
                ),
            )

            review_result = await review_handle.result()
            watchdog_result = await watchdog_handle.result()

        assert review_result.outcome == "REVIEWER_CONFIRMED"
        assert watchdog_result.outcome == "SAFE"
        assert watchdog_result.emergency_filed is False
        # Exactly one NGCH filing overall — HumanReviewWorkflow's, never a duplicate
        # emergency file from the watchdog.
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "CONFIRM"

    @pytest.mark.asyncio
    async def test_real_run_survives_losing_the_filing_race_to_watchdog(self, temporal_env):
        """CRITICAL-3 (cts-workflow-reviewer): if the IET watchdog wins the race
        and files first, HumanReviewWorkflow's own file_to_ngch call gets a 409
        -> DuplicateFilingError. Before this fix that propagated unhandled and
        killed the whole workflow BEFORE write_audit ever ran — losing the
        record of the reviewer's actual decision entirely, even though NGCH
        itself had exactly one correct filing. The workflow must complete
        normally and still audit the real decision."""
        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "test-bank", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[HumanReviewWorkflow],
            activities=[_fake_push_to_review_queue, _fake_file_to_ngch_watchdog_won_race, _fake_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _real_input(bank_id, instrument_id),
                id=f"cts-humanreview-{bank_id}-{instrument_id}",
                task_queue=task_queue,
            )
            await handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="RETURN", reason="Signature mismatch confirmed",
                    reviewer_id="reviewer-007", decided_at=time.time(),
                ),
            )
            result = await handle.result()

        assert result.outcome == "REVIEWER_RETURNED"   # workflow completes, doesn't crash
        assert len(_audit_calls) == 1                   # real decision still recorded
        assert _audit_calls[0]["event_type"] == "CTS_HUMAN_REVIEW_DECIDED"
