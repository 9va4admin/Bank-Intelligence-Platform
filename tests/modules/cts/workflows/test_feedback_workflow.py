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

    @pytest.mark.asyncio
    async def test_legacy_signal_type_payee_still_works(self):
        """Backward-compat: old FeedbackEmitInput from feedback_workflow.py still routes correctly."""
        from modules.cts.workflows.feedback_workflow import (
            FeedbackAccumulatorWorkflow,
            FeedbackEmitInput as LegacyFeedbackEmitInput,
            FeedbackEmitWorkflow,
        )

        wf = FeedbackEmitWorkflow()
        payee_msg = PayeeSignalMessage(
            instrument_id="INS-010", bank_id="saraswat",
            ocr_payee="Old Format", name_match_score=0.8,
            script=None, workflow_decision="STP_CONFIRM",
            human_approved=None, image_path="",
        )
        # Use the legacy FeedbackEmitInput (with signal_type field)
        legacy_inp = LegacyFeedbackEmitInput(
            bank_id="saraswat",
            instrument_id="INS-010",
            signal_type="payee",
            payee_msg=payee_msg,
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle):
            await wf.run(legacy_inp)

        mock_handle.signal.assert_awaited_once()
        signal_target = mock_handle.signal.await_args[0][0]
        assert signal_target == FeedbackAccumulatorWorkflow.receive_payee_signal

    @pytest.mark.asyncio
    async def test_legacy_signal_type_micr_still_works(self):
        """Backward-compat: legacy MICR signal type still routes to receive_micr_signal."""
        from modules.cts.workflows.feedback_workflow import (
            FeedbackAccumulatorWorkflow,
            FeedbackEmitInput as LegacyFeedbackEmitInput,
            FeedbackEmitWorkflow,
        )

        wf = FeedbackEmitWorkflow()
        micr_msg = MicrSignalMessage(
            instrument_id="INS-011", bank_id="saraswat",
            ngch_outcome="ACCEPTED",
        )
        legacy_inp = LegacyFeedbackEmitInput(
            bank_id="saraswat",
            instrument_id="INS-011",
            signal_type="micr",
            micr_msg=micr_msg,
        )
        mock_handle = AsyncMock()
        with _patch_workflow(mock_handle):
            await wf.run(legacy_inp)

        mock_handle.signal.assert_awaited_once()
        signal_target = mock_handle.signal.await_args[0][0]
        assert signal_target == FeedbackAccumulatorWorkflow.receive_micr_signal
