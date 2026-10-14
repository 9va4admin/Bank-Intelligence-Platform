"""TDD tests for the OCR feedback-loop wiring:

- FeedbackEmitInput (feedback_types.py) — dataclass construction and defaults
- FeedbackEmitWorkflow — signal routing, accumulator-id scoping, error swallowing
- Field-mapping logic: ChequeWorkflowInput → FeedbackEmitInput (mirrors cheque_workflow.py)
- ngch_filed_ok logic: True for STP_CONFIRM / STP_RETURN, False for HUMAN_REVIEW

All FeedbackEmitWorkflow tests patch `modules.cts.workflows.feedback_workflow.workflow`
so no Temporal runtime is required.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
from modules.cts.workflows.feedback_types import (
    FeedbackEmitInput,
    MicrSignalMessage,
    PayeeSignalMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cheque_inp(**overrides) -> ChequeWorkflowInput:
    defaults = dict(
        instrument_id="INS-001",
        bank_id="saraswat",
        image_url="minio://bucket/cheques/INS-001.jpg",
        account_number="1234567890",
        cheque_number="000123",
        presented_amount=50000.0,
        presented_payee="Ramesh Kumar",
        iet_deadline=1e10,
    )
    defaults.update(overrides)
    return ChequeWorkflowInput(**defaults)


def _build_emit_input(inp: ChequeWorkflowInput, decision: str) -> FeedbackEmitInput:
    """Mirror the exact field-mapping in cheque_workflow.py finalise()."""
    return FeedbackEmitInput(
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        ocr_payee=inp.presented_payee,
        name_match_score=0.0,
        workflow_decision=decision,
        image_path=inp.image_url,
        account_suffix=inp.account_number[-4:],
        ngch_filed_ok=(decision != "HUMAN_REVIEW"),
    )


@contextmanager
def _patch_workflow(mock_handle: AsyncMock):
    """Patch the temporalio workflow module inside feedback_workflow, returning the mock workflow obj."""
    with patch("modules.cts.workflows.feedback_workflow.workflow") as mock_wf:
        mock_wf.get_external_workflow_handle_for.return_value = mock_handle
        # Make workflow.unsafe.imports_passed_through() a no-op context manager
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=None)
        cm.__exit__ = MagicMock(return_value=False)
        mock_wf.unsafe.imports_passed_through.return_value = cm
        yield mock_wf


# ---------------------------------------------------------------------------
# 1. FeedbackEmitInput dataclass
# ---------------------------------------------------------------------------

class TestFeedbackEmitInput:
    def test_required_fields_are_stored(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001",
            bank_id="saraswat",
            ocr_payee="Ramesh Kumar",
            name_match_score=0.92,
            workflow_decision="STP_CONFIRM",
            image_path="minio://bucket/img.jpg",
            account_suffix="1234",
        )
        assert inp.instrument_id == "INS-001"
        assert inp.bank_id == "saraswat"
        assert inp.ocr_payee == "Ramesh Kumar"
        assert inp.name_match_score == 0.92
        assert inp.workflow_decision == "STP_CONFIRM"

    def test_ngch_filed_ok_defaults_false(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="b", ocr_payee="X",
            name_match_score=0.0, workflow_decision="STP_CONFIRM",
            image_path="", account_suffix="1234",
        )
        assert inp.ngch_filed_ok is False

    def test_cbs_degraded_defaults_false(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="b", ocr_payee="X",
            name_match_score=0.0, workflow_decision="STP_CONFIRM",
            image_path="", account_suffix="1234",
        )
        assert inp.cbs_degraded is False

    def test_script_defaults_none(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="b", ocr_payee="X",
            name_match_score=0.0, workflow_decision="STP_CONFIRM",
            image_path="", account_suffix="1234",
        )
        assert inp.script is None

    def test_human_approved_defaults_none(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="b", ocr_payee="X",
            name_match_score=0.0, workflow_decision="STP_CONFIRM",
            image_path="", account_suffix="1234",
        )
        assert inp.human_approved is None


# ---------------------------------------------------------------------------
# 2. ngch_filed_ok logic (mirrors cheque_workflow.py finalise() line)
# ---------------------------------------------------------------------------

class TestNgchFiledOkLogic:
    @pytest.mark.parametrize("decision,expected", [
        ("STP_CONFIRM", True),
        ("STP_RETURN", True),
        ("HUMAN_REVIEW", False),
    ])
    def test_ngch_filed_ok_by_decision(self, decision: str, expected: bool):
        ngch_filed_ok = decision != "HUMAN_REVIEW"
        assert ngch_filed_ok == expected

    def test_account_suffix_is_last_four_digits(self):
        account_number = "1234567890"
        suffix = account_number[-4:]
        assert suffix == "7890"

    def test_account_suffix_stored_in_emit_input(self):
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="b", ocr_payee="X",
            name_match_score=0.0, workflow_decision="STP_CONFIRM",
            image_path="", account_suffix="7890", ngch_filed_ok=True,
        )
        assert inp.account_suffix == "7890"


# ---------------------------------------------------------------------------
# 3. Field-mapping: ChequeWorkflowInput → FeedbackEmitInput
# ---------------------------------------------------------------------------

class TestFeedbackEmitInputFieldMapping:
    def test_instrument_id_forwarded(self):
        emit = _build_emit_input(_make_cheque_inp(), "STP_CONFIRM")
        assert emit.instrument_id == "INS-001"

    def test_bank_id_forwarded(self):
        emit = _build_emit_input(_make_cheque_inp(bank_id="federal-bank"), "STP_CONFIRM")
        assert emit.bank_id == "federal-bank"

    def test_ocr_payee_is_presented_payee(self):
        emit = _build_emit_input(_make_cheque_inp(presented_payee="Kavitha Nair"), "STP_CONFIRM")
        assert emit.ocr_payee == "Kavitha Nair"

    def test_image_path_is_image_url(self):
        emit = _build_emit_input(
            _make_cheque_inp(image_url="minio://bucket/INS-001.jpg"), "STP_CONFIRM",
        )
        assert emit.image_path == "minio://bucket/INS-001.jpg"

    def test_account_suffix_from_last_four_of_account_number(self):
        emit = _build_emit_input(_make_cheque_inp(account_number="9988776655"), "STP_CONFIRM")
        assert emit.account_suffix == "6655"

    def test_workflow_decision_forwarded(self):
        emit = _build_emit_input(_make_cheque_inp(), "STP_RETURN")
        assert emit.workflow_decision == "STP_RETURN"

    def test_ngch_filed_ok_true_for_stp_confirm(self):
        emit = _build_emit_input(_make_cheque_inp(), "STP_CONFIRM")
        assert emit.ngch_filed_ok is True

    def test_ngch_filed_ok_true_for_stp_return(self):
        emit = _build_emit_input(_make_cheque_inp(), "STP_RETURN")
        assert emit.ngch_filed_ok is True

    def test_ngch_filed_ok_false_for_human_review(self):
        emit = _build_emit_input(_make_cheque_inp(), "HUMAN_REVIEW")
        assert emit.ngch_filed_ok is False

    def test_name_match_score_is_placeholder_zero(self):
        emit = _build_emit_input(_make_cheque_inp(), "STP_CONFIRM")
        assert emit.name_match_score == 0.0


# ---------------------------------------------------------------------------
# 4. FeedbackEmitWorkflow — signal routing
# ---------------------------------------------------------------------------

class TestFeedbackEmitWorkflow:
    """Tests call FeedbackEmitWorkflow.run() directly with Temporal patched out."""

    @pytest.mark.asyncio
    async def test_payee_signal_sent_for_ocr_payee_input(self):
        from modules.cts.workflows.feedback_workflow import (
            FeedbackAccumulatorWorkflow,
            FeedbackEmitWorkflow,
        )

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="saraswat",
            ocr_payee="Ramesh Kumar", name_match_score=0.92,
            workflow_decision="STP_CONFIRM", image_path="minio://x",
            account_suffix="1234", ngch_filed_ok=True,
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle):
            await wf.run(inp)

        mock_handle.signal.assert_awaited_once()
        signal_target = mock_handle.signal.await_args[0][0]
        assert signal_target == FeedbackAccumulatorWorkflow.receive_payee_signal

    @pytest.mark.asyncio
    async def test_payee_signal_message_has_correct_ocr_payee(self):
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-001", bank_id="saraswat",
            ocr_payee="Kavitha Nair", name_match_score=0.88,
            workflow_decision="STP_RETURN", image_path="minio://y",
            account_suffix="5678", ngch_filed_ok=True,
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle):
            await wf.run(inp)

        msg = mock_handle.signal.await_args[0][1]
        assert isinstance(msg, PayeeSignalMessage)
        assert msg.ocr_payee == "Kavitha Nair"
        assert msg.workflow_decision == "STP_RETURN"
        assert msg.instrument_id == "INS-001"
        assert msg.bank_id == "saraswat"

    @pytest.mark.asyncio
    async def test_accumulator_workflow_id_is_bank_scoped(self):
        from modules.cts.workflows.feedback_workflow import (
            FeedbackAccumulatorWorkflow,
            FeedbackEmitWorkflow,
        )

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-002", bank_id="federal-bank",
            ocr_payee="X", name_match_score=0.0,
            workflow_decision="STP_CONFIRM", image_path="", account_suffix="0000",
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle) as mock_wf:
            await wf.run(inp)

        call_kwargs = mock_wf.get_external_workflow_handle_for.call_args
        wf_run = call_kwargs[0][0]
        wf_id = call_kwargs[1]["workflow_id"]
        assert wf_run == FeedbackAccumulatorWorkflow.run
        assert wf_id == "cts-feedback-federal-bank"

    @pytest.mark.asyncio
    async def test_payee_signal_includes_image_path(self):
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-003", bank_id="saraswat",
            ocr_payee="Rajan", name_match_score=0.75,
            workflow_decision="HUMAN_REVIEW",
            image_path="minio://bucket/INS-003.tiff",
            account_suffix="4321", ngch_filed_ok=False,
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle):
            await wf.run(inp)

        msg = mock_handle.signal.await_args[0][1]
        assert msg.image_path == "minio://bucket/INS-003.tiff"

    @pytest.mark.asyncio
    async def test_accumulator_unreachable_does_not_raise(self):
        """If the accumulator is not running, FeedbackEmitWorkflow swallows the error."""
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-004", bank_id="saraswat",
            ocr_payee="X", name_match_score=0.0,
            workflow_decision="STP_CONFIRM", image_path="", account_suffix="1111",
        )
        mock_handle = AsyncMock()
        mock_handle.signal.side_effect = RuntimeError("accumulator workflow not found")

        with _patch_workflow(mock_handle):
            await wf.run(inp)  # must not raise

    @pytest.mark.asyncio
    async def test_handle_lookup_failure_does_not_raise(self):
        """get_external_workflow_handle_for failure is also swallowed."""
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        wf = FeedbackEmitWorkflow()
        inp = FeedbackEmitInput(
            instrument_id="INS-005", bank_id="saraswat",
            ocr_payee="Y", name_match_score=0.0,
            workflow_decision="STP_RETURN", image_path="", account_suffix="2222",
        )
        with _patch_workflow(AsyncMock()) as mock_wf:
            mock_wf.get_external_workflow_handle_for.side_effect = RuntimeError("temporal down")
            await wf.run(inp)  # must not raise


# ---------------------------------------------------------------------------
# Regression (found live, 2026-09-23): ModelRetrainWorkflow.run() called
# `await workflow.sleep(_SHADOW_POLL_INTERVAL)`, which does not exist on
# `temporalio.workflow` in the installed SDK (1.7.1) — same bug already found and
# fixed in postdated_hold_workflow.py the same day. None of the tests above (or
# anywhere else in this file) ever execute ModelRetrainWorkflow.run() against a real
# Temporal environment — exactly why this was never caught before a live run.
#
# Fixed with workflow.wait_condition(lambda: False, timeout=...) wrapped in
# try/except asyncio.TimeoutError — a pure, uninterruptible sleep, since this poll
# loop has no signal to react to (unlike PostDatedHoldWorkflow's cancel_hold).
# ---------------------------------------------------------------------------

import uuid
import pytest_asyncio
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from modules.cts.workflows.feedback_workflow import ModelRetrainWorkflow, ModelRetrainInput
from modules.cts.workflows.activities.feedback_activities import RetrainJobResult, ShadowEvalResult

_retrain_calls: list[dict] = []
_promote_calls: list[dict] = []


@activity.defn(name="dispatch_retrain_job")
async def _fake_dispatch_retrain_job(bank_id: str, corpus_type: str) -> RetrainJobResult:
    _retrain_calls.append({"bank_id": bank_id, "corpus_type": corpus_type})
    return RetrainJobResult(bank_id=bank_id, mlflow_run_id="run-001", status="submitted")


@activity.defn(name="run_shadow_evaluation")
async def _fake_run_shadow_evaluation(bank_id: str, mlflow_run_id: str, corpus_type: str) -> ShadowEvalResult:
    # new_accuracy > 0 breaks the poll loop after exactly one sleep interval —
    # keeps the test fast (real 7-day max wait, under time-skipping) while still
    # exercising the sleep line at least once.
    return ShadowEvalResult(
        bank_id=bank_id, mlflow_run_id=mlflow_run_id,
        new_accuracy=0.95, baseline_accuracy=0.90, improvement=0.05, promote=True,
    )


@activity.defn(name="promote_model")
async def _fake_promote_model(bank_id: str, mlflow_run_id: str, corpus_type: str) -> None:
    _promote_calls.append({"bank_id": bank_id, "mlflow_run_id": mlflow_run_id})


_FAKE_RETRAIN_ACTIVITIES = [_fake_dispatch_retrain_job, _fake_run_shadow_evaluation, _fake_promote_model]


@pytest_asyncio.fixture(scope="module")
async def retrain_temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture(autouse=True)
def _reset_retrain_state():
    _retrain_calls.clear()
    _promote_calls.clear()
    yield
    _retrain_calls.clear()
    _promote_calls.clear()


class TestModelRetrainWorkflowRealRun:
    """Runs ModelRetrainWorkflow.run() for real against a Temporal time-skipping
    server — the class of test that would have caught the workflow.sleep() bug."""

    @pytest.mark.asyncio(loop_scope="module")
    async def test_poll_sleep_completes_and_promotes(self, retrain_temporal_env):
        """Direct regression case: the poll loop's sleep must actually execute (and the
        workflow reach promote_model) instead of raising AttributeError inside the
        workflow task."""
        inp = ModelRetrainInput(bank_id="kbl", corpus_type="payee_name")
        tq = f"tq-retrain-{uuid.uuid4().hex[:8]}"
        async with Worker(
            retrain_temporal_env.client,
            task_queue=tq,
            workflows=[ModelRetrainWorkflow],
            activities=_FAKE_RETRAIN_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await retrain_temporal_env.client.execute_workflow(
                ModelRetrainWorkflow.run,
                inp,
                id=f"test-retrain-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )

        assert len(_retrain_calls) == 1
        assert _retrain_calls[0]["bank_id"] == "kbl"
        assert len(_promote_calls) == 1
        assert _promote_calls[0]["mlflow_run_id"] == "run-001"
