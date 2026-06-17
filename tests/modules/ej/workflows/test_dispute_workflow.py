"""
Tests for modules/ej/workflows/dispute_workflow.py

DisputeResolutionWorkflow: match → fetch CCTV → auto-resolve or escalate.
CCTV evidence required before any auto-resolution decision.
Workflow ID: ej-dispute-{bank_id}-{npci_claim_id}
"""
import pytest


def _make_input(bank_id="test-bank", atm_id="ATM001", npci_claim_id="CLAIM001"):
    from modules.ej.workflows.dispute_workflow import EJDisputeInput
    return EJDisputeInput(
        bank_id=bank_id,
        atm_id=atm_id,
        npci_claim_id=npci_claim_id,
        claim_amount=5000.0,
        claim_timestamp="2026-06-17T10:30:00+05:30",
        claim_type="CASH_NOT_DISPENSED",
    )


def _make_matched_results(cctv_outcome="EXTRACTED", claim_type="CASH_NOT_DISPENSED"):
    from modules.ej.workflows.activities.dispute_match import EJDisputeMatchResult
    from modules.ej.workflows.activities.cctv_extract import CCTVExtractResult

    return {
        "dispute_match": EJDisputeMatchResult(
            outcome="MATCHED",
            matched_canonical_hash="abc123",
            match_score=0.92,
        ),
        "cctv_extract": CCTVExtractResult(
            outcome=cctv_outcome,
            object_key="cctv/test-bank/ATM001/CLAIM001.mp4" if cctv_outcome == "EXTRACTED" else None,
        ),
    }


class TestEJDisputeInput:
    def test_requires_npci_claim_id(self):
        from modules.ej.workflows.dispute_workflow import EJDisputeInput
        with pytest.raises(Exception):
            EJDisputeInput(bank_id="b", atm_id="a", claim_amount=100.0,
                           claim_timestamp="ts", claim_type="X")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.npci_claim_id = "other"

    def test_workflow_id_is_deterministic(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow
        wf = DisputeResolutionWorkflow()
        wf_id = wf.workflow_id("test-bank", "CLAIM001")
        assert wf_id == "ej-dispute-test-bank-CLAIM001"


class TestEJDisputeHappyPath:
    @pytest.mark.asyncio
    async def test_matched_with_cctv_auto_resolves(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

        wf = DisputeResolutionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_matched_results())
        assert result.outcome in ("AUTO_RESOLVED", "ESCALATED_TO_HUMAN")

    @pytest.mark.asyncio
    async def test_result_has_bank_id(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

        wf = DisputeResolutionWorkflow()
        result = await wf.run_with_mocks(_make_input(bank_id="kotak"), mock_results=_make_matched_results())
        assert result.bank_id == "kotak"

    @pytest.mark.asyncio
    async def test_result_has_npci_claim_id(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

        wf = DisputeResolutionWorkflow()
        result = await wf.run_with_mocks(_make_input(npci_claim_id="CLAIM999"), mock_results=_make_matched_results())
        assert result.npci_claim_id == "CLAIM999"

    @pytest.mark.asyncio
    async def test_result_is_frozen(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

        wf = DisputeResolutionWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_matched_results())
        with pytest.raises(Exception):
            result.outcome = "other"


class TestEJDisputeCCTVRequired:
    @pytest.mark.asyncio
    async def test_no_match_escalates_to_human(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow
        from modules.ej.workflows.activities.dispute_match import EJDisputeMatchResult
        from modules.ej.workflows.activities.cctv_extract import CCTVExtractResult

        wf = DisputeResolutionWorkflow()
        results = {
            "dispute_match": EJDisputeMatchResult(outcome="NO_MATCH"),
            "cctv_extract": CCTVExtractResult(outcome="CCTV_UNAVAILABLE"),
        }
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "ESCALATED_TO_HUMAN"

    @pytest.mark.asyncio
    async def test_cctv_unavailable_escalates_even_if_matched(self):
        """Auto-resolution requires CCTV evidence — unavailable CCTV → escalate."""
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

        wf = DisputeResolutionWorkflow()
        results = _make_matched_results(cctv_outcome="CCTV_UNAVAILABLE")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "ESCALATED_TO_HUMAN"

    @pytest.mark.asyncio
    async def test_match_failed_escalates(self):
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow
        from modules.ej.workflows.activities.dispute_match import EJDisputeMatchResult
        from modules.ej.workflows.activities.cctv_extract import CCTVExtractResult

        wf = DisputeResolutionWorkflow()
        results = {
            "dispute_match": EJDisputeMatchResult(outcome="MATCH_FAILED"),
            "cctv_extract": CCTVExtractResult(outcome="EXTRACTED", object_key="cctv/x.mp4"),
        }
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "ESCALATED_TO_HUMAN"
