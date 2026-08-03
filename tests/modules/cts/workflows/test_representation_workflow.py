"""
Tests for modules/cts/workflows/representation_workflow.py

ChequeRepresentationWorkflow — 24-hour re-presentation mandate.

Per RBI/NPCI rules, instruments returned with RE_PRESENTATION_CODES must be
fixed and re-presented within 24 hours (excluding holidays). This workflow:
  1. Notifies ops / customer that re-presentation is pending
  2. Waits for ops approval signal (the "fix" has been applied)
  3. Re-submits to NGCH on approval
  4. Expires and routes to human queue if signal not received within config window

Terminal states: REPRESENTATION_SUBMITTED | REPRESENTATION_EXPIRED | REPRESENTATION_FAILED
Workflow ID: cts-represent-{bank_id}-{instrument_id}
"""
import pytest
from unittest.mock import MagicMock

from modules.cts.compliance.models import RE_PRESENTATION_CODES


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_input(**kwargs):
    from modules.cts.workflows.representation_workflow import ChequeRepresentationInput
    defaults = dict(
        instrument_id="OUT-001",
        bank_id="test-bank",
        bank_ifsc="SVCB0000001",
        return_reason_code="39",
        original_session_id="SES-0619-001",
        clearing_date="2026-07-21",
    )
    defaults.update(kwargs)
    return ChequeRepresentationInput(**defaults)


def _make_mocks(
    notify_ok=True,
    resubmit_ok=True,
    approved=True,
    expired=False,
):
    return {
        "notify": MagicMock(notified=notify_ok),
        "resubmit": MagicMock(
            submitted=resubmit_ok and approved and not expired,
            ngch_reference=f"NGCH-REPR-001" if (resubmit_ok and approved and not expired) else None,
        ),
        "audit": MagicMock(audit_event_id="AUD-002"),
        "approved": approved,
        "expired": expired,
    }


# ── input model ───────────────────────────────────────────────────────────────

class TestChequeRepresentationInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.instrument_id = "changed"

    def test_accepts_valid_representation_code(self):
        for code in RE_PRESENTATION_CODES:
            inp = _make_input(return_reason_code=code)
            assert inp.return_reason_code == code

    def test_accepts_all_six_representation_codes(self):
        assert len(RE_PRESENTATION_CODES) == 6
        expected = {"35", "39", "40", "67", "68", "83"}
        assert RE_PRESENTATION_CODES == expected


# ── result model ──────────────────────────────────────────────────────────────

class TestChequeRepresentationResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationResult
        r = ChequeRepresentationResult(
            outcome="REPRESENTATION_SUBMITTED",
            instrument_id="OUT-001",
            bank_id="test-bank",
            representation_submitted=True,
            audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"

    def test_result_has_required_fields(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationResult
        r = ChequeRepresentationResult(
            outcome="REPRESENTATION_EXPIRED",
            instrument_id="OUT-002",
            bank_id="test-bank",
            representation_submitted=False,
            audit_written=True,
        )
        assert r.instrument_id == "OUT-002"
        assert r.bank_id == "test-bank"
        assert r.representation_submitted is False
        assert r.audit_written is True


# ── workflow id ───────────────────────────────────────────────────────────────

class TestRepresentationWorkflowId:
    def test_workflow_id_format(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        wid = wf.workflow_id("test-bank", "OUT-001")
        assert "test-bank" in wid
        assert "OUT-001" in wid
        assert wid.startswith("cts-represent-")

    def test_workflow_id_deterministic(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        assert wf.workflow_id("bank-a", "OUT-001") == wf.workflow_id("bank-a", "OUT-001")

    def test_workflow_id_unique_per_instrument(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        assert wf.workflow_id("bank-a", "OUT-001") != wf.workflow_id("bank-a", "OUT-002")

    def test_workflow_id_unique_per_bank(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        assert wf.workflow_id("bank-a", "OUT-001") != wf.workflow_id("bank-b", "OUT-001")


# ── happy path: approval received, NGCH re-submission ────────────────────────

class TestRepresentationHappyPath:
    @pytest.mark.asyncio
    async def test_submitted_when_approved(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(approved=True))
        assert result.outcome == "REPRESENTATION_SUBMITTED"

    @pytest.mark.asyncio
    async def test_representation_submitted_flag_true_on_approval(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(approved=True))
        assert result.representation_submitted is True

    @pytest.mark.asyncio
    async def test_instrument_id_in_result(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(instrument_id="OUT-SPECIAL-999"),
            mock_results=_make_mocks(approved=True),
        )
        assert result.instrument_id == "OUT-SPECIAL-999"

    @pytest.mark.asyncio
    async def test_bank_id_in_result(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(bank_id="hdfc-bank"),
            mock_results=_make_mocks(approved=True),
        )
        assert result.bank_id == "hdfc-bank"

    @pytest.mark.asyncio
    async def test_audit_written_on_submission(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(approved=True))
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_all_representation_codes_accepted(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        for code in sorted(RE_PRESENTATION_CODES):
            result = await wf.run_with_mocks(
                _make_input(return_reason_code=code),
                mock_results=_make_mocks(approved=True),
            )
            assert result.outcome == "REPRESENTATION_SUBMITTED", f"Code {code} should succeed"


# ── expiry path: signal not received within window ───────────────────────────

class TestRepresentationExpiry:
    @pytest.mark.asyncio
    async def test_expired_when_signal_not_received(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=False, expired=True),
        )
        assert result.outcome == "REPRESENTATION_EXPIRED"

    @pytest.mark.asyncio
    async def test_not_submitted_when_expired(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=False, expired=True),
        )
        assert result.representation_submitted is False

    @pytest.mark.asyncio
    async def test_audit_written_on_expiry(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=False, expired=True),
        )
        assert result.audit_written is True


# ── resubmit failure path ─────────────────────────────────────────────────────

class TestRepresentationNgchFailure:
    @pytest.mark.asyncio
    async def test_failed_when_resubmit_fails(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=True, resubmit_ok=False),
        )
        assert result.outcome == "REPRESENTATION_FAILED"

    @pytest.mark.asyncio
    async def test_not_submitted_when_ngch_fails(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=True, resubmit_ok=False),
        )
        assert result.representation_submitted is False

    @pytest.mark.asyncio
    async def test_audit_written_on_failure(self):
        from modules.cts.workflows.representation_workflow import ChequeRepresentationWorkflow
        wf = ChequeRepresentationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(approved=True, resubmit_ok=False),
        )
        assert result.audit_written is True


# ── activities: notify_representation_pending ─────────────────────────────────

class TestNotifyRepresentationPending:
    def test_activity_importable(self):
        from modules.cts.workflows.activities.representation_activities import (
            notify_representation_pending,
        )
        assert callable(notify_representation_pending)

    def test_notify_input_is_frozen(self):
        from modules.cts.workflows.activities.representation_activities import (
            NotifyRepresentationInput,
        )
        inp = NotifyRepresentationInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
            representation_window_hours=24,
        )
        with pytest.raises(Exception):
            inp.instrument_id = "changed"

    def test_notify_result_has_notified_flag(self):
        from modules.cts.workflows.activities.representation_activities import (
            NotifyRepresentationResult,
        )
        r = NotifyRepresentationResult(notified=True)
        assert r.notified is True

    @pytest.mark.asyncio
    async def test_notify_degrades_when_no_dispatcher(self):
        from modules.cts.workflows.activities.representation_activities import (
            NotifyRepresentationInput,
            notify_representation_pending,
        )
        inp = NotifyRepresentationInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
            representation_window_hours=24,
        )
        result = await notify_representation_pending(inp, dispatcher=None)
        assert result.notified is False
        assert result.degraded is True


# ── activities: re_submit_to_ngch_for_representation ─────────────────────────

class TestResubmitActivity:
    def test_activity_importable(self):
        from modules.cts.workflows.activities.representation_activities import (
            re_submit_to_ngch_for_representation,
        )
        assert callable(re_submit_to_ngch_for_representation)

    def test_resubmit_input_is_frozen(self):
        from modules.cts.workflows.activities.representation_activities import (
            ResubmitNgchInput,
        )
        inp = ResubmitNgchInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
        )
        with pytest.raises(Exception):
            inp.instrument_id = "changed"

    def test_resubmit_result_has_submitted_flag(self):
        from modules.cts.workflows.activities.representation_activities import (
            ResubmitNgchResult,
        )
        r = ResubmitNgchResult(submitted=True, ngch_reference="NGCH-REPR-001")
        assert r.submitted is True
        assert r.ngch_reference == "NGCH-REPR-001"

    @pytest.mark.asyncio
    async def test_resubmit_degrades_when_no_ngch_client(self):
        from modules.cts.workflows.activities.representation_activities import (
            ResubmitNgchInput,
            re_submit_to_ngch_for_representation,
        )
        inp = ResubmitNgchInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
        )
        result = await re_submit_to_ngch_for_representation(inp, ngch_client=None)
        assert result.submitted is False
        assert result.degraded is True


# ── config-driven window (not hardcoded) ─────────────────────────────────────

class TestRepresentationConfigDriven:
    def test_representation_window_not_hardcoded(self):
        """Verify the notify activity accepts representation_window_hours as a param."""
        from modules.cts.workflows.activities.representation_activities import (
            NotifyRepresentationInput,
        )
        inp_24 = NotifyRepresentationInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
            representation_window_hours=24,
        )
        inp_48 = NotifyRepresentationInput(
            instrument_id="OUT-001",
            bank_id="test-bank",
            return_reason_code="39",
            original_session_id="SES-001",
            clearing_date="2026-07-21",
            representation_window_hours=48,
        )
        assert inp_24.representation_window_hours == 24
        assert inp_48.representation_window_hours == 48


# ── SessionReconciliationWorkflow spawns representation child workflows ───────

class TestSessionReconciliationSpawnsRepresentation:
    @pytest.mark.asyncio
    async def test_representation_workflows_spawned_for_re_presentation_codes(self):
        from modules.cts.workflows.session_reconciliation_workflow import (
            SessionReconciliationInput,
            SessionReconciliationWorkflow,
        )
        exceptions = [
            {"instrument_id": "OUT-001", "status": "RETURNED", "reason_code": "39"},
            {"instrument_id": "OUT-002", "status": "RETURNED", "reason_code": "35"},
        ]
        mocks = {
            "settlement_report": MagicMock(session_id="SES-001"),
            "reconciliation": MagicMock(
                matched_count=8,
                exception_count=2,
                outcome="EXCEPTIONS_FLAGGED",
                exception_instruments=exceptions,
            ),
            "rrf": MagicMock(generated=True, file_path="rrf/SES-001.xml", return_count=2),
            "audit": MagicMock(audit_event_id="AUD-001"),
        }
        inp = SessionReconciliationInput(
            session_id="SES-001",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            clearing_date="2026-07-21",
            submitted_count=10,
        )
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(inp, mock_results=mocks)
        assert result.representation_workflows_spawned == 2

    @pytest.mark.asyncio
    async def test_non_representation_codes_do_not_spawn_workflows(self):
        from modules.cts.workflows.session_reconciliation_workflow import (
            SessionReconciliationInput,
            SessionReconciliationWorkflow,
        )
        # Code "01" (insufficient funds) is customer-fault, not a RE_PRESENTATION_CODE
        exceptions = [
            {"instrument_id": "OUT-001", "status": "RETURNED", "reason_code": "01"},
        ]
        mocks = {
            "settlement_report": MagicMock(session_id="SES-002"),
            "reconciliation": MagicMock(
                matched_count=9,
                exception_count=1,
                outcome="EXCEPTIONS_FLAGGED",
                exception_instruments=exceptions,
            ),
            "rrf": MagicMock(generated=True, file_path="rrf/SES-002.xml", return_count=1),
            "audit": MagicMock(audit_event_id="AUD-002"),
        }
        inp = SessionReconciliationInput(
            session_id="SES-002",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            clearing_date="2026-07-21",
            submitted_count=10,
        )
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(inp, mock_results=mocks)
        assert result.representation_workflows_spawned == 0

    @pytest.mark.asyncio
    async def test_mixed_codes_only_spawns_for_representation_codes(self):
        from modules.cts.workflows.session_reconciliation_workflow import (
            SessionReconciliationInput,
            SessionReconciliationWorkflow,
        )
        exceptions = [
            {"instrument_id": "OUT-001", "status": "RETURNED", "reason_code": "01"},  # customer fault
            {"instrument_id": "OUT-002", "status": "RETURNED", "reason_code": "39"},  # re-present
            {"instrument_id": "OUT-003", "status": "RETURNED", "reason_code": "67"},  # re-present
        ]
        mocks = {
            "settlement_report": MagicMock(session_id="SES-003"),
            "reconciliation": MagicMock(
                matched_count=7,
                exception_count=3,
                outcome="EXCEPTIONS_FLAGGED",
                exception_instruments=exceptions,
            ),
            "rrf": MagicMock(generated=True, file_path="rrf/SES-003.xml", return_count=3),
            "audit": MagicMock(audit_event_id="AUD-003"),
        }
        inp = SessionReconciliationInput(
            session_id="SES-003",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            clearing_date="2026-07-21",
            submitted_count=10,
        )
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(inp, mock_results=mocks)
        assert result.representation_workflows_spawned == 2

    @pytest.mark.asyncio
    async def test_no_exceptions_spawns_zero_workflows(self):
        from modules.cts.workflows.session_reconciliation_workflow import (
            SessionReconciliationInput,
            SessionReconciliationWorkflow,
        )
        mocks = {
            "settlement_report": MagicMock(session_id="SES-004"),
            "reconciliation": MagicMock(
                matched_count=10,
                exception_count=0,
                outcome="RECONCILED",
                exception_instruments=[],
            ),
            "rrf": MagicMock(generated=False, file_path=None, return_count=0),
            "audit": MagicMock(audit_event_id="AUD-004"),
        }
        inp = SessionReconciliationInput(
            session_id="SES-004",
            bank_id="test-bank",
            bank_ifsc="SVCB0000001",
            clearing_date="2026-07-21",
            submitted_count=10,
        )
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(inp, mock_results=mocks)
        assert result.representation_workflows_spawned == 0
