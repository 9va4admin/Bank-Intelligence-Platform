"""
Tests for modules/cts/workflows/ngch_submission_workflow.py

NGCHSubmissionWorkflow — submits an endorsed lot to NGCH for clearing.
Activities: build_ngch_file → submit_to_ngch → confirm_acknowledgement → write_audit

Terminal states: SUBMITTED | SUBMISSION_FAILED
"""
import pytest
from unittest.mock import MagicMock


def _make_input(**kwargs):
    from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionInput
    defaults = dict(
        lot_number="LOT_SVCB0000001_20240619_SES01_01",
        bank_id="test-bank",
        bank_ifsc="SVCB0000001",
        session_id="SES01",
        clearing_date="2024-06-19",
        instrument_count=5,
    )
    defaults.update(kwargs)
    return NGCHSubmissionInput(**defaults)


def _make_mocks(ack_ok=True):
    return {
        "ngch_file": MagicMock(file_path="ngch/SVCB_20240619_SES01_01.xml", checksum="abc123"),
        "submission": MagicMock(reference_number="NGCH-REF-001", status="ACCEPTED" if ack_ok else "REJECTED"),
        "acknowledgement": MagicMock(
            acknowledged=ack_ok,
            reference_number="NGCH-REF-001",
            reason=None if ack_ok else "DUPLICATE_SUBMISSION",
        ),
        "audit": MagicMock(audit_event_id="AUD-001"),
    }


class TestNGCHSubmissionInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.lot_number = "changed"

    def test_workflow_id_format(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        wid = wf.workflow_id("test-bank", "LOT_SVCB_20240619_S01_01")
        assert "test-bank" in wid
        assert "LOT_SVCB_20240619_S01_01" in wid

    def test_workflow_id_deterministic(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        assert wf.workflow_id("bank-a", "LOT-1") == wf.workflow_id("bank-a", "LOT-1")


class TestNGCHSubmissionResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionResult
        r = NGCHSubmissionResult(
            outcome="SUBMITTED", lot_number="LOT_1", bank_id="b",
            ngch_reference="NGCH-REF-001", audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"


class TestNGCHSubmissionHappyPath:
    @pytest.mark.asyncio
    async def test_submitted_when_ngch_acknowledges(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=True))
        assert result.outcome == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_ngch_reference_in_result(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=True))
        assert result.ngch_reference == "NGCH-REF-001"

    @pytest.mark.asyncio
    async def test_audit_written_on_submitted(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=True))
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_lot_number_in_result(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(
            _make_input(lot_number="LOT_SVCB_20240619_S01_99"),
            mock_results=_make_mocks(ack_ok=True),
        )
        assert result.lot_number == "LOT_SVCB_20240619_S01_99"

    @pytest.mark.asyncio
    async def test_bank_id_in_result(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(
            _make_input(bank_id="kotak-mah"),
            mock_results=_make_mocks(ack_ok=True),
        )
        assert result.bank_id == "kotak-mah"


class TestNGCHSubmissionFailedPath:
    @pytest.mark.asyncio
    async def test_submission_failed_when_ngch_rejects(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=False))
        assert result.outcome == "SUBMISSION_FAILED"

    @pytest.mark.asyncio
    async def test_audit_written_on_failure(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=False))
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_failure_reason_in_result(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(ack_ok=False))
        assert result.failure_reason is not None
        assert "DUPLICATE" in result.failure_reason or result.failure_reason != ""


class TestNGCHSubmissionIdempotency:
    def test_workflow_id_unique_per_lot(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        wf = NGCHSubmissionWorkflow()
        assert wf.workflow_id("bank-a", "LOT-1") != wf.workflow_id("bank-a", "LOT-2")


# ---------------------------------------------------------------------------
# Temporal decorator presence tests (new — verify real Temporal wiring)
# ---------------------------------------------------------------------------

class TestNGCHSubmissionTemporalDecorators:
    def test_workflow_defn_decorator(self):
        """@workflow.defn must be present for Temporal worker registration."""
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        assert hasattr(NGCHSubmissionWorkflow, "__temporal_workflow_definition")

    def test_run_method_exists(self):
        from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
        assert callable(getattr(NGCHSubmissionWorkflow, "run", None))


class TestNGCHSubmissionWriteAuditEvents:
    def test_ngch_submitted_event_type_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_OUT_NGCH_SUBMITTED" in _VALID_EVENT_TYPES

    def test_ngch_submission_failed_event_type_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_OUT_NGCH_SUBMISSION_FAILED" in _VALID_EVENT_TYPES


# ---------------------------------------------------------------------------
# NGCH submission activities tests
# ---------------------------------------------------------------------------

class TestNGCHSubmissionActivities:
    @pytest.mark.asyncio
    async def test_build_ngch_file_no_lot_store(self):
        from modules.cts.workflows.activities.ngch_submission_activities import (
            BuildNGCHFileInput,
            build_ngch_file,
        )
        inp = BuildNGCHFileInput(
            lot_number="LOT-001",
            bank_id="srcb",
            bank_ifsc="SRCB0000001",
            session_id="SES-001",
            clearing_date="2026-07-19",
            instrument_count=5,
        )
        result = await build_ngch_file(inp, lot_store=None)
        assert result.instrument_count == 5
        assert "LOT-001" in result.file_path

    @pytest.mark.asyncio
    async def test_submit_to_ngch_no_client(self):
        from modules.cts.workflows.activities.ngch_submission_activities import (
            SubmitToNGCHInput,
            submit_to_ngch,
        )
        inp = SubmitToNGCHInput(
            lot_number="LOT-001",
            bank_id="srcb",
            bank_ifsc="SRCB0000001",
            file_path="cts/ngch/srcb/LOT-001/file.xml",
            checksum_sha256="abc",
            instrument_count=5,
        )
        result = await submit_to_ngch(inp, ngch_client=None)
        assert result.submitted is False
        assert result.failure_reason == "NGCH_CLIENT_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_confirm_acknowledgement_no_reference(self):
        from modules.cts.workflows.activities.ngch_submission_activities import (
            ConfirmAcknowledgementInput,
            confirm_acknowledgement,
        )
        inp = ConfirmAcknowledgementInput(
            lot_number="LOT-001",
            bank_id="srcb",
            ngch_reference=None,
        )
        result = await confirm_acknowledgement(inp, ngch_client=None)
        assert result.acknowledged is False
        assert result.reason == "NO_NGCH_REFERENCE"

    @pytest.mark.asyncio
    async def test_confirm_acknowledgement_no_client(self):
        from modules.cts.workflows.activities.ngch_submission_activities import (
            ConfirmAcknowledgementInput,
            confirm_acknowledgement,
        )
        inp = ConfirmAcknowledgementInput(
            lot_number="LOT-001",
            bank_id="srcb",
            ngch_reference="NGCH-REF-001",
        )
        result = await confirm_acknowledgement(inp, ngch_client=None)
        assert result.acknowledged is False
        assert result.reason == "NGCH_CLIENT_UNAVAILABLE"
