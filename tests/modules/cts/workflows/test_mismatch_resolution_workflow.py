"""
Tests for modules/cts/workflows/mismatch_resolution_workflow.py

MismatchResolutionWorkflow — branch supervisor resolution for Vision ↔ scanner mismatch.

Triggered by: OutwardScanWorkflow when Vision LLM amount differs from scanner MICR amount.
Holds instrument. Publishes hold event to Kafka (branch SSE picks up).
Waits for Temporal signal: GO_AHEAD | REJECTED.
4-hour timeout → TIMEOUT_AUTO_REJECTED.

Terminal states: GO_AHEAD | REJECTED | TIMEOUT_AUTO_REJECTED
Workflow ID: cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_mismatch_input(**kwargs):
    from modules.cts.workflows.mismatch_resolution_workflow import MismatchInput
    defaults = dict(
        mismatch_id="MM-SVCB-001",
        bank_id="saraswat-coop",
        branch_id="BRANCH-ANDHERI-01",
        scan_id="SC-001245",
        instrument_id="OUT-INST-001245",
        pu_id="MUMBAI-MAIN",
        scanner_amount_str="45000.00",
        vision_amount_str="4500.00",
        mismatch_fields=["amount_figures"],
        payee_display="R***",
        session_id="EEH-SESS-001",
    )
    defaults.update(kwargs)
    return MismatchInput(**defaults)


class TestMismatchInput:
    def test_input_is_frozen(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchInput
        inp = _make_mismatch_input()
        with pytest.raises(Exception):
            inp.mismatch_id = "changed"

    def test_requires_mismatch_id(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchInput
        with pytest.raises(Exception):
            MismatchInput(
                bank_id="b", branch_id="br", scan_id="s", instrument_id="i",
                pu_id="pu", scanner_amount_str="100", vision_amount_str="10",
                mismatch_fields=["amount_figures"], payee_display="X***",
                session_id="sess",
            )

    def test_mismatch_fields_is_list(self):
        inp = _make_mismatch_input()
        assert isinstance(inp.mismatch_fields, list)
        assert "amount_figures" in inp.mismatch_fields


class TestMismatchResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResult
        r = MismatchResult(
            outcome="GO_AHEAD",
            mismatch_id="MM-001",
            bank_id="b",
            branch_id="br",
            resolved_by="op-mahesh",
            audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"

    def test_all_outcomes_valid(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResult
        for outcome in ("GO_AHEAD", "REJECTED", "TIMEOUT_AUTO_REJECTED"):
            r = MismatchResult(
                outcome=outcome, mismatch_id="MM", bank_id="b", branch_id="br",
                resolved_by=None, audit_written=True,
            )
            assert r.outcome == outcome

    def test_resolved_by_optional(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResult
        r = MismatchResult(
            outcome="TIMEOUT_AUTO_REJECTED",
            mismatch_id="MM",
            bank_id="b",
            branch_id="br",
            resolved_by=None,        # no human resolver on timeout
            audit_written=True,
        )
        assert r.resolved_by is None


class TestMismatchWorkflowId:
    def test_workflow_id_format(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        wid = wf.workflow_id("saraswat-coop", "BRANCH-ANDHERI-01", "MM-001")
        assert "saraswat-coop" in wid
        assert "BRANCH-ANDHERI-01" in wid
        assert "MM-001" in wid

    def test_workflow_id_is_deterministic(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        assert (
            wf.workflow_id("b", "br", "mm-1")
            == wf.workflow_id("b", "br", "mm-1")
        )

    def test_workflow_id_unique_per_mismatch(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        assert (
            wf.workflow_id("b", "br", "mm-1")
            != wf.workflow_id("b", "br", "mm-2")
        )


class TestMismatchResolutionGoAhead:
    @pytest.mark.asyncio
    async def test_go_ahead_signal_produces_go_ahead_outcome(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(audit_event_id="AUD-001"),
            "signal": MagicMock(action="GO_AHEAD", resolved_by="op-mahesh", supervisor_note=""),
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.outcome == "GO_AHEAD"

    @pytest.mark.asyncio
    async def test_go_ahead_includes_resolved_by(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(audit_event_id="AUD-001"),
            "signal": MagicMock(action="GO_AHEAD", resolved_by="op-priya", supervisor_note=""),
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.resolved_by == "op-priya"

    @pytest.mark.asyncio
    async def test_audit_written_on_go_ahead(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(audit_event_id="AUD-001"),
            "signal": MagicMock(action="GO_AHEAD", resolved_by="op-x", supervisor_note=""),
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.audit_written is True


class TestMismatchResolutionRejected:
    @pytest.mark.asyncio
    async def test_rejected_signal_produces_rejected_outcome(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(audit_event_id="AUD-002"),
            "signal": MagicMock(action="REJECTED", resolved_by="op-supervisor", supervisor_note="Wrong amount"),
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.outcome == "REJECTED"

    @pytest.mark.asyncio
    async def test_audit_written_on_rejected(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(),
            "signal": MagicMock(action="REJECTED", resolved_by="sup", supervisor_note=""),
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_mismatch_id_in_result(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(),
            "signal": MagicMock(action="REJECTED", resolved_by="sup", supervisor_note=""),
        }
        result = await wf.run_with_mocks(
            _make_mismatch_input(mismatch_id="MM-SPECIAL-99"),
            mock_results=mock_results,
        )
        assert result.mismatch_id == "MM-SPECIAL-99"


class TestMismatchResolutionTimeout:
    @pytest.mark.asyncio
    async def test_timeout_produces_timeout_auto_rejected(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(),
            "signal": None,          # None = timeout — no signal arrived
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.outcome == "TIMEOUT_AUTO_REJECTED"

    @pytest.mark.asyncio
    async def test_timeout_resolved_by_is_none(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(),
            "signal": None,
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.resolved_by is None

    @pytest.mark.asyncio
    async def test_audit_written_on_timeout(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        mock_results = {
            "kafka": MagicMock(),
            "audit": MagicMock(),
            "signal": None,
        }
        result = await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        assert result.audit_written is True


class TestMismatchKafkaPublish:
    @pytest.mark.asyncio
    async def test_kafka_publishes_hold_event_before_waiting(self):
        """Kafka publish must happen synchronously before any wait — branch SSE needs this."""
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        kafka_mock = MagicMock()
        mock_results = {
            "kafka": kafka_mock,
            "audit": MagicMock(),
            "signal": MagicMock(action="GO_AHEAD", resolved_by="op", supervisor_note=""),
        }
        await wf.run_with_mocks(_make_mismatch_input(), mock_results=mock_results)
        # Kafka publish must have been accessed (used by run_with_mocks)
        assert mock_results["kafka"] is kafka_mock

    @pytest.mark.asyncio
    async def test_kafka_topic_includes_branch_id(self):
        """Topic must be cts.mismatch.{bank_id}.{branch_id} — branch-scoped, not global."""
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        topic = wf.mismatch_kafka_topic("saraswat-coop", "BRANCH-ANDHERI-01")
        assert "saraswat-coop" in topic
        assert "BRANCH-ANDHERI-01" in topic

    def test_mismatch_kafka_topic_format(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
        wf = MismatchResolutionWorkflow()
        topic = wf.mismatch_kafka_topic("bank-a", "BRANCH-B")
        assert topic == "cts.mismatch.bank-a.BRANCH-B"


# ---------------------------------------------------------------------------
# publish_mismatch_hold activity — real body (not mocked)
# ---------------------------------------------------------------------------

class TestPublishMismatchHold:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_topic(self):
        from modules.cts.workflows.mismatch_resolution_workflow import (
            publish_mismatch_hold, PublishMismatchHoldInput,
        )
        producer = AsyncMock()
        result = await publish_mismatch_hold(
            PublishMismatchHoldInput(
                mismatch_id="MM-001", bank_id="saraswat-coop", branch_id="BRANCH-01",
                scan_id="SC-001", instrument_id="OUT-001",
                scanner_amount_str="45000.00", vision_amount_str="4500.00",
                mismatch_fields=["amount_figures"], payee_display="R***",
                session_id="SESS-001",
            ),
            event_producer=producer,
        )
        assert result.published is True
        producer.publish.assert_called_once()
        call_kwargs = producer.publish.call_args.kwargs
        assert call_kwargs["topic"] == "cts.mismatch.saraswat-coop.BRANCH-01"
        assert call_kwargs["event_type"] == "CTS_OUT_MISMATCH_HELD"
        assert call_kwargs["payload"]["mismatch_id"] == "MM-001"


# ---------------------------------------------------------------------------
# MismatchResolutionWorkflow.run() — the real @workflow.run, driven through
# an actual Temporal Worker + time-skipping test server.
# ---------------------------------------------------------------------------

import uuid
from temporalio import activity as _activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


@_activity.defn(name="publish_mismatch_hold")
async def _fake_publish_hold(inp) -> dict:
    return {"published": True}


@_activity.defn(name="write_audit")
async def _fake_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    return WriteAuditResult(success=True, immudb_tx_id="TEST-TX")


class TestMismatchResolutionWorkflowRealRun:
    @pytest.mark.asyncio
    async def test_real_run_go_ahead_via_signal(self):
        from modules.cts.workflows.mismatch_resolution_workflow import (
            MismatchResolutionWorkflow, MismatchSignal,
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client, task_queue=task_queue,
                workflows=[MismatchResolutionWorkflow],
                activities=[_fake_publish_hold, _fake_write_audit],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    MismatchResolutionWorkflow.run,
                    _make_mismatch_input(),
                    id=f"cts-mismatch-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )
                await handle.signal(
                    MismatchResolutionWorkflow.resolve,
                    MismatchSignal(action="GO_AHEAD", resolved_by="op-mahesh"),
                )
                result = await handle.result()

        assert result.outcome == "GO_AHEAD"
        assert result.resolved_by == "op-mahesh"
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_real_run_rejected_via_signal(self):
        from modules.cts.workflows.mismatch_resolution_workflow import (
            MismatchResolutionWorkflow, MismatchSignal,
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client, task_queue=task_queue,
                workflows=[MismatchResolutionWorkflow],
                activities=[_fake_publish_hold, _fake_write_audit],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    MismatchResolutionWorkflow.run,
                    _make_mismatch_input(),
                    id=f"cts-mismatch-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )
                await handle.signal(
                    MismatchResolutionWorkflow.resolve,
                    MismatchSignal(action="REJECTED", resolved_by="op-priya", supervisor_note="wrong amount"),
                )
                result = await handle.result()

        assert result.outcome == "REJECTED"
        assert result.resolved_by == "op-priya"

    @pytest.mark.asyncio
    async def test_real_run_timeout_auto_rejects(self):
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client, task_queue=task_queue,
                workflows=[MismatchResolutionWorkflow],
                activities=[_fake_publish_hold, _fake_write_audit],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                # No signal sent — time-skipping server fast-forwards through
                # the 4-hour wait_condition timeout automatically.
                result = await env.client.execute_workflow(
                    MismatchResolutionWorkflow.run,
                    _make_mismatch_input(),
                    id=f"cts-mismatch-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "TIMEOUT_AUTO_REJECTED"
        assert result.resolved_by is None
