"""
Tests for modules/cts/workflows/session_reconciliation_workflow.py

SessionReconciliationWorkflow — end-of-session clearing reconciliation.
Activities: fetch_ngch_settlement_report → match_submitted_vs_settled → generate_rrf → write_audit

Terminal states: RECONCILED | EXCEPTIONS_FLAGGED
"""
import pytest
from unittest.mock import MagicMock


def _make_input(**kwargs):
    from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationInput
    defaults = dict(
        session_id="SES-0619-001",
        bank_id="test-bank",
        bank_ifsc="SVCB0000001",
        clearing_date="2024-06-19",
        submitted_count=10,
    )
    defaults.update(kwargs)
    return SessionReconciliationInput(**defaults)


def _make_mocks(matched=10, exceptions=0, rrf_generated=False):
    return {
        "settlement_report": MagicMock(
            session_id="SES-0619-001",
            items=[MagicMock(instrument_id=f"OUT-{i:03d}") for i in range(matched)],
        ),
        "reconciliation": MagicMock(
            matched_count=matched,
            exception_count=exceptions,
            outcome="RECONCILED" if exceptions == 0 else "EXCEPTIONS_FLAGGED",
        ),
        "rrf": MagicMock(
            generated=rrf_generated,
            file_path="rrf/SES-0619-001_rrf.xml" if rrf_generated else None,
            return_count=0,
        ),
        "audit": MagicMock(audit_event_id="AUD-001"),
    }


class TestSessionReconciliationInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.session_id = "changed"

    def test_workflow_id_format(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        wid = wf.workflow_id("test-bank", "SES-0619-001")
        assert "test-bank" in wid
        assert "SES-0619-001" in wid

    def test_workflow_id_deterministic(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        assert wf.workflow_id("bank-a", "SES-1") == wf.workflow_id("bank-a", "SES-1")


class TestSessionReconciliationResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationResult
        r = SessionReconciliationResult(
            outcome="RECONCILED", session_id="SES-1", bank_id="b",
            matched_count=10, exception_count=0, rrf_generated=False, audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"


class TestSessionReconciliationHappyPath:
    @pytest.mark.asyncio
    async def test_reconciled_when_all_matched(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(matched=10, exceptions=0))
        assert result.outcome == "RECONCILED"

    @pytest.mark.asyncio
    async def test_matched_count_in_result(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(_make_input(submitted_count=5), mock_results=_make_mocks(matched=5))
        assert result.matched_count == 5

    @pytest.mark.asyncio
    async def test_zero_exceptions_on_clean_session(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(exceptions=0))
        assert result.exception_count == 0

    @pytest.mark.asyncio
    async def test_audit_written_on_reconciled(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks())
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_session_id_in_result(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(session_id="SES-SPECIAL-999"),
            mock_results=_make_mocks(),
        )
        assert result.session_id == "SES-SPECIAL-999"

    @pytest.mark.asyncio
    async def test_bank_id_in_result(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(bank_id="hdfc-bank"),
            mock_results=_make_mocks(),
        )
        assert result.bank_id == "hdfc-bank"


class TestSessionReconciliationExceptions:
    @pytest.mark.asyncio
    async def test_exceptions_flagged_when_mismatches_exist(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(matched=8, exceptions=2),
        )
        assert result.outcome == "EXCEPTIONS_FLAGGED"

    @pytest.mark.asyncio
    async def test_exception_count_propagated(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(matched=7, exceptions=3),
        )
        assert result.exception_count == 3

    @pytest.mark.asyncio
    async def test_audit_written_on_exceptions_flagged(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(matched=9, exceptions=1),
        )
        assert result.audit_written is True


class TestSessionReconciliationRRF:
    @pytest.mark.asyncio
    async def test_rrf_generated_when_returns_exist(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        mocks = _make_mocks(matched=10, exceptions=0, rrf_generated=True)
        mocks["rrf"] = MagicMock(generated=True, file_path="rrf/SES01.xml", return_count=2)
        result = await wf.run_with_mocks(_make_input(), mock_results=mocks)
        assert result.rrf_generated is True

    @pytest.mark.asyncio
    async def test_rrf_not_generated_when_no_returns(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_mocks(rrf_generated=False),
        )
        assert result.rrf_generated is False


class TestSessionReconciliationWorkflowId:
    def test_workflow_id_unique_per_session(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        wf = SessionReconciliationWorkflow()
        assert wf.workflow_id("bank-a", "SES-1") != wf.workflow_id("bank-a", "SES-2")
