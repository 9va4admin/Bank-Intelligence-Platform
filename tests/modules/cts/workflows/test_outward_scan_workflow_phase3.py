"""
Phase 3 tests for OutwardScanWorkflow — PU context + Vision LLM last step + mismatch.

These tests extend the original test_outward_scan_workflow.py without modifying it.
New fields: pu_id in OutwardScanInput and OutwardScanResult.
New step: vision_llm runs AFTER lot assignment (last step before audit).
New outcome: MISMATCH_HELD when Vision LLM disagrees with scanner.
New: when mismatch, MismatchResolutionWorkflow is referenced by result.
"""
import pytest
from unittest.mock import MagicMock


def _make_p3_input(**kwargs):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    defaults = dict(
        scan_id="SCAN-P3-001",
        instrument_id="OUT-INST-P3-001",
        bank_id="saraswat-coop",
        bank_ifsc="SVCB0000001",
        session_id="SES-0704-001",
        image_front_url="minio://cts/front/SCAN-P3-001.tiff",
        image_rear_url="minio://cts/rear/SCAN-P3-001.tiff",
        pu_id="MUMBAI-MAIN",
        branch_id="BRANCH-ANDHERI-01",
    )
    defaults.update(kwargs)
    return OutwardScanInput(**defaults)


def _make_p3_mocks(
    compliance_ok=True,
    lot_number="LOT-0007",
    vision_match=True,
    vision_mismatch_fields=None,
):
    """Build the Phase 3 mock_results dict with vision_llm entry."""
    vision_mock = MagicMock()
    if vision_match:
        vision_mock.has_mismatch = False
        vision_mock.mismatch_fields = []
        vision_mock.vision_amount_str = "45000.00"
    else:
        vision_mock.has_mismatch = True
        vision_mock.mismatch_fields = vision_mismatch_fields or ["amount_figures"]
        vision_mock.vision_amount_str = "4500.00"

    return {
        "micr": MagicMock(micr_line="123456789", confidence=0.98),
        "compliance": MagicMock(is_compliant=compliance_ok, violations=[]),
        "lot": MagicMock(lot_number=lot_number),
        "vision_llm": vision_mock,
        "audit": MagicMock(audit_event_id="AUD-P3"),
    }


class TestOutwardScanP3Input:
    def test_pu_id_field_accepted(self):
        inp = _make_p3_input()
        assert inp.pu_id == "MUMBAI-MAIN"

    def test_branch_id_field_accepted(self):
        inp = _make_p3_input()
        assert inp.branch_id == "BRANCH-ANDHERI-01"

    def test_pu_id_in_workflow_id(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("saraswat-coop", "SCAN-001", pu_id="MUMBAI-MAIN")
        assert "MUMBAI-MAIN" in wid

    def test_workflow_id_with_pu_format(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("bank-a", "SCAN-001", pu_id="PU-X")
        assert wid == "cts-outscan-bank-a-PU-X-SCAN-001"

    def test_workflow_id_without_pu_backward_compat(self):
        """Calling workflow_id without pu_id still works (backward compat)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("bank-a", "SCAN-001")
        assert "bank-a" in wid
        assert "SCAN-001" in wid


class TestOutwardScanP3VisionMatch:
    @pytest.mark.asyncio
    async def test_vision_match_produces_accepted(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_pu_id_in_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(pu_id="DELHI-MAIN"),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.pu_id == "DELHI-MAIN"

    @pytest.mark.asyncio
    async def test_audit_written_on_vision_match_accepted(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.audit_written is True


class TestOutwardScanP3VisionMismatch:
    @pytest.mark.asyncio
    async def test_vision_mismatch_produces_mismatch_held(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False, vision_mismatch_fields=["amount_figures"]),
        )
        assert result.outcome == "MISMATCH_HELD"

    @pytest.mark.asyncio
    async def test_mismatch_result_has_mismatch_id(self):
        """MISMATCH_HELD result must include the mismatch_id used to spawn child workflow."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result.mismatch_id is not None
        assert len(result.mismatch_id) > 0

    @pytest.mark.asyncio
    async def test_mismatch_id_is_deterministic_from_scan_id(self):
        """Same scan_id → same mismatch_id (idempotent child workflow spawn)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result1 = await wf.run_with_mocks(
            _make_p3_input(scan_id="SCAN-123"),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        result2 = await wf.run_with_mocks(
            _make_p3_input(scan_id="SCAN-123"),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result1.mismatch_id == result2.mismatch_id

    @pytest.mark.asyncio
    async def test_mismatch_fields_in_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False, vision_mismatch_fields=["amount_figures", "amount_words"]),
        )
        assert result.mismatch_fields == ["amount_figures", "amount_words"]

    @pytest.mark.asyncio
    async def test_lot_number_preserved_on_mismatch(self):
        """Lot assignment happens before vision — lot_number should be in result."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(lot_number="LOT-0007", vision_match=False),
        )
        assert result.lot_number == "LOT-0007"

    @pytest.mark.asyncio
    async def test_audit_written_on_mismatch_held(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_cts_rejected_before_lot_skips_vision(self):
        """If CTS-2010 fails, vision LLM is never reached (no vision_llm in mocks needed)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mocks = _make_p3_mocks(compliance_ok=False)
        mocks["compliance"] = MagicMock(is_compliant=False, violations=["MICR_LINE_MISSING"])
        # Remove vision_llm — if workflow tries to access it, it won't crash with KeyError
        mocks.pop("vision_llm", None)
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.outcome == "CTS_REJECTED"


class TestOutwardScanP3MismatchIdGeneration:
    def test_generate_mismatch_id_format(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mid = wf.generate_mismatch_id("saraswat-coop", "SCAN-001")
        assert "saraswat-coop" in mid
        assert "SCAN-001" in mid

    def test_generate_mismatch_id_deterministic(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mid1 = wf.generate_mismatch_id("bank-a", "SCAN-X")
        mid2 = wf.generate_mismatch_id("bank-a", "SCAN-X")
        assert mid1 == mid2

    def test_generate_mismatch_id_unique_per_scan(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        assert (
            wf.generate_mismatch_id("bank-a", "SCAN-1")
            != wf.generate_mismatch_id("bank-a", "SCAN-2")
        )
