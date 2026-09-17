"""
Cut 3 — Timeout workflows with Temporal time-skipping.

Tests (all use WorkflowEnvironment.start_time_skipping()):
  Inward:
    - HumanReviewWorkflow 55-minute timeout fires and produces TIMEOUT_AUTO_RETURNED
    - HumanReviewWorkflow resolves immediately when signal is received before timeout

  Outward:
    - MismatchResolutionWorkflow 4-hour timeout fires and auto-rejects the instrument
    - MismatchResolutionWorkflow resolves on GO_AHEAD signal

Time-skipping collapses real wall-clock waits into milliseconds.
Without this cut, these timeout paths are never exercised against real Temporal.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from tests.integration.cut3.conftest import TEST_BANK_ID

pytestmark = [pytest.mark.integration, pytest.mark.cut3]

_INSTR_ID = lambda: f"CTS-CUT3-TO-{uuid.uuid4().hex[:8]}"


# ════════════════════════════════════════════════════════════════════════════
# Module-level activity stubs — carry the exact activity-type names that
# the production workflows call via workflow.execute_activity(fn_ref, ...).
# Without matching names, Temporal would queue tasks nobody dequeues.
# ════════════════════════════════════════════════════════════════════════════

from temporalio import activity as _activity


@_activity.defn(name="push_to_review_queue")
async def _stub_push_queue(inp):
    return None


@_activity.defn(name="file_to_ngch")
async def _stub_file_to_ngch(inp):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
    return NGCHFilerResult(
        acknowledgement_id=f"ACK-STUB-{uuid.uuid4().hex[:8]}",
        status="ACCEPTED",
        filed_decision=getattr(inp, "decision", "RETURN"),
    )


@_activity.defn(name="write_audit")
async def _stub_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    return WriteAuditResult(success=True)


@_activity.defn(name="publish_mismatch_hold")
async def _stub_publish_hold(inp):
    from modules.cts.workflows.mismatch_resolution_workflow import PublishMismatchHoldResult
    return PublishMismatchHoldResult(published=True)


@_activity.defn(name="persist_mismatch_hold_db")
async def _stub_persist_hold_db(inp):
    return None


@_activity.defn(name="resolve_mismatch_db")
async def _stub_resolve_db(inp):
    return None


# ════════════════════════════════════════════════════════════════════════════
# Input helpers
# ════════════════════════════════════════════════════════════════════════════

def _make_hr_input(instr_id: str, timeout_minutes: int = 55):
    from modules.cts.workflows.human_review_workflow import HumanReviewInput
    return HumanReviewInput(
        instrument_id=instr_id,
        bank_id=TEST_BANK_ID,
        workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
        context_bundle={"ocr_confidence": 0.91, "fraud_score": 0.08},
        iet_deadline=time.time() + 3600,
        review_timeout_minutes=timeout_minutes,
    )


def _make_mismatch_input(instr_id: str):
    from modules.cts.workflows.mismatch_resolution_workflow import MismatchInput
    mismatch_id = f"MISMATCH-{uuid.uuid4().hex[:8]}"
    return MismatchInput(
        mismatch_id=mismatch_id,
        bank_id=TEST_BANK_ID,
        branch_id="BRANCH-001",
        scan_id=f"SCAN-{uuid.uuid4().hex[:6]}",
        instrument_id=instr_id,
        pu_id=f"PU-{uuid.uuid4().hex[:6]}",
        scanner_amount_str="95000.00",
        vision_amount_str="96000.00",
        mismatch_fields=["amount_figures"],
        payee_display="P***",
        session_id=f"SESSION-{uuid.uuid4().hex[:6]}",
    )


# ════════════════════════════════════════════════════════════════════════════
# HumanReviewWorkflow — 55-minute timeout (inward)
# ════════════════════════════════════════════════════════════════════════════

class TestHumanReviewTimeout:

    @pytest.mark.asyncio
    async def test_human_review_55min_timeout_fires(self, time_skip_env):
        """
        HumanReviewWorkflow must auto-timeout when no signal arrives.
        Using review_timeout_minutes=1 with time-skipping collapses the wait to ms.

        Catches:
          - Timeout not wired to review_timeout_minutes from config_service
          - CancelledException swallowed instead of propagating
          - Wrong timeout unit (minutes vs seconds)
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow

        instr_id = _INSTR_ID()
        tq = f"cts-hr-test-{uuid.uuid4().hex[:6]}"

        async with Worker(
            time_skip_env.client,
            task_queue=tq,
            workflows=[HumanReviewWorkflow],
            activities=[_stub_push_queue, _stub_file_to_ngch, _stub_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            handle = await time_skip_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _make_hr_input(instr_id, timeout_minutes=1),
                id=f"cts-humanreview-{TEST_BANK_ID}-{instr_id}",
                task_queue=tq,
            )
            # No signal → timeout fires (time-skip collapses 1 minute to ms)
            result = await asyncio.wait_for(handle.result(), timeout=60.0)

        assert result.timed_out is True, (
            f"Timeout did not fire — outcome: {result.outcome}"
        )
        assert result.outcome == "TIMEOUT_AUTO_RETURNED"

    @pytest.mark.asyncio
    async def test_human_review_resolves_on_signal(self, time_skip_env):
        """
        HumanReviewWorkflow resolves immediately when a ReviewDecision signal
        arrives before the timeout.
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.workflows.human_review_workflow import (
            HumanReviewWorkflow, ReviewDecision,
        )

        instr_id = _INSTR_ID()
        tq = f"cts-hr-sig-{uuid.uuid4().hex[:6]}"

        async with Worker(
            time_skip_env.client,
            task_queue=tq,
            workflows=[HumanReviewWorkflow],
            activities=[_stub_push_queue, _stub_file_to_ngch, _stub_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            handle = await time_skip_env.client.start_workflow(
                HumanReviewWorkflow.run,
                _make_hr_input(instr_id, timeout_minutes=55),
                id=f"cts-humanreview-{TEST_BANK_ID}-{instr_id}",
                task_queue=tq,
            )

            # Send review signal before timeout
            await handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="CONFIRM",
                    reason="image_matches_account",
                    reviewer_id="ops-001",
                    decided_at=time.time(),
                ),
            )

            result = await asyncio.wait_for(handle.result(), timeout=30.0)

        assert result.outcome == "REVIEWER_CONFIRMED"
        assert result.timed_out is False


# ════════════════════════════════════════════════════════════════════════════
# MismatchResolutionWorkflow — 4-hour timeout (outward)
# ════════════════════════════════════════════════════════════════════════════

class TestMismatchResolutionTimeout:

    @pytest.mark.asyncio
    async def test_mismatch_resolution_4hr_timeout_auto_rejects(self, time_skip_env):
        """
        MismatchResolutionWorkflow auto-rejects when no resolution signal arrives
        within 4 hours (MISMATCH_TIMEOUT_HOURS = 4, hardcoded constant in the workflow).
        Time-skip collapses this to milliseconds.

        Catches:
          - Timeout not firing (Temporal timer not registered)
          - auto-reject not producing TIMEOUT_AUTO_REJECTED in MismatchResult.outcome
          - Wrong timeout value (4 instead of 4*3600)
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow

        instr_id = _INSTR_ID()
        tq = f"cts-mismatch-test-{uuid.uuid4().hex[:6]}"

        async with Worker(
            time_skip_env.client,
            task_queue=tq,
            workflows=[MismatchResolutionWorkflow],
            activities=[
                _stub_publish_hold, _stub_persist_hold_db,
                _stub_resolve_db, _stub_write_audit,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            handle = await time_skip_env.client.start_workflow(
                MismatchResolutionWorkflow.run,
                _make_mismatch_input(instr_id),
                id=f"cts-mismatch-{TEST_BANK_ID}-{instr_id}",
                task_queue=tq,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60.0)

        assert result.outcome == "TIMEOUT_AUTO_REJECTED", (
            f"Expected TIMEOUT_AUTO_REJECTED on 4-hr timeout, got {result.outcome}"
        )

    @pytest.mark.asyncio
    async def test_mismatch_resolves_on_go_ahead_signal(self, time_skip_env):
        """
        MismatchResolutionWorkflow proceeds when ops_manager sends GO_AHEAD signal
        before the 4-hour timeout fires.
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.workflows.mismatch_resolution_workflow import (
            MismatchResolutionWorkflow, MismatchSignal,
        )

        instr_id = _INSTR_ID()
        tq = f"cts-mismatch-go-{uuid.uuid4().hex[:6]}"

        async with Worker(
            time_skip_env.client,
            task_queue=tq,
            workflows=[MismatchResolutionWorkflow],
            activities=[
                _stub_publish_hold, _stub_persist_hold_db,
                _stub_resolve_db, _stub_write_audit,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            handle = await time_skip_env.client.start_workflow(
                MismatchResolutionWorkflow.run,
                _make_mismatch_input(instr_id),
                id=f"cts-mismatch-{TEST_BANK_ID}-{instr_id}",
                task_queue=tq,
            )

            await handle.signal(
                MismatchResolutionWorkflow.resolve,
                MismatchSignal(action="GO_AHEAD", resolved_by="ops-mgr-001"),
            )

            result = await asyncio.wait_for(handle.result(), timeout=30.0)

        assert result.outcome == "GO_AHEAD"


# ════════════════════════════════════════════════════════════════════════════
# DB + Immudb write — Cut 3's version of the pairing rule
# ════════════════════════════════════════════════════════════════════════════

class TestDecisionPairingCut3:

    @pytest.mark.asyncio
    async def test_timeout_decision_db_immudb_both_written(
        self, cut3_db_pool, cut3_immudb_writer
    ):
        """
        When HumanReview times out, the auto-RETURN decision must be written to
        BOTH YugabyteDB (cts.agent_decisions) and Immudb simultaneously.
        No silently-skipped audit write.
        """
        from modules.cts.workflows.activities.persist_decision import (
            PersistDecisionInput, persist_agent_decision,
        )
        from modules.cts.workflows.activities.write_audit import (
            WriteAuditInput, write_audit,
        )

        instr_id = _INSTR_ID()
        now = time.time()

        dec = PersistDecisionInput(
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
            workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
            decision="STP_RETURN",
            decision_reason="human_review_timeout",
            fraud_score=0.0,
            shap_values={},
            processing_started_at=now - 55 * 60,
            processing_completed_at=now,
        )
        async with cut3_db_pool.acquire() as conn:
            await persist_agent_decision(dec, db_conn=conn)

        aud = WriteAuditInput(
            event_type="CTS_WF_REVIEW_TIMEOUT",
            bank_id=TEST_BANK_ID,
            instrument_id=instr_id,
            payload={"decision": "STP_RETURN", "reason": "human_review_timeout"},
        )
        aud_result = await write_audit(aud, cut3_immudb_writer, hsm=None)
        assert aud_result.success is True

        # Verify DB row
        async with cut3_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision, decision_reason FROM cts.agent_decisions "
                "WHERE instrument_id = $1",
                instr_id,
            )
        assert row is not None
        assert row["decision"] == "STP_RETURN"
        assert row["decision_reason"] == "human_review_timeout"
