"""
Tests for modules/cts/workflows/outward_scan_workflow.py

OutwardScanWorkflow — Presentee Bank outward clearing.
Orchestrates: capture_image → extract_micr → validate_cts2010 → create_lot_entry → write_audit

Terminal states: ACCEPTED | CTS_REJECTED
"""
import pytest
from unittest.mock import MagicMock


def _make_input(**kwargs):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    defaults = dict(
        scan_id="SCAN-001",
        instrument_id="OUT-INST-001",
        bank_id="test-bank",
        bank_ifsc="SVCB0000001",
        session_id="SES-0619-001",
        image_front_url="minio://cts/front/SCAN-001.tiff",
        image_rear_url="minio://cts/rear/SCAN-001.tiff",
    )
    defaults.update(kwargs)
    return from_dict(defaults)


def from_dict(d):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    return OutwardScanInput(**d)


def _make_scan_result(micr="123456789", compliance_ok=True, lot_number="LOT_SVCB0000001_20240619_SES-0619-001_01"):
    return {
        "micr": MagicMock(micr_line=micr, confidence=0.98, outcome="PROCEED"),
        "compliance": MagicMock(is_compliant=compliance_ok, violations=[]),
        "lot": MagicMock(lot_number=lot_number, outcome="ASSIGNED"),
        "audit": MagicMock(audit_event_id="AUD-001"),
    }


class TestOutwardScanInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.scan_id = "changed"

    def test_input_requires_scan_id(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
        with pytest.raises(Exception):
            OutwardScanInput(
                instrument_id="x", bank_id="b", bank_ifsc="SVCB0000001",
                session_id="S", image_front_url="f", image_rear_url="r",
            )

    def test_workflow_id_format(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("test-bank", "SCAN-001")
        assert "test-bank" in wid
        assert "SCAN-001" in wid


class TestOutwardScanResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanResult
        r = OutwardScanResult(
            outcome="ACCEPTED", scan_id="SCAN-001", bank_id="b",
            instrument_id="I", micr_line="123", lot_number="LOT_1", audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"

    def test_result_outcome_values(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanResult
        for outcome in ("ACCEPTED", "CTS_REJECTED"):
            r = OutwardScanResult(
                outcome=outcome, scan_id="S", bank_id="b",
                instrument_id="I", micr_line=None, lot_number=None, audit_written=True,
            )
            assert r.outcome == outcome


class TestOutwardScanHappyPath:
    @pytest.mark.asyncio
    async def test_accepted_when_compliant(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_scan_result(compliance_ok=True),
        )
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_micr_line_propagated_to_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_scan_result(micr="999888777"),
        )
        assert result.micr_line == "999888777"

    @pytest.mark.asyncio
    async def test_lot_number_none_on_accepted(self):
        """Scan workflow no longer assigns lots — lot_number is always None on ACCEPTED.
        Lot assignment happens later in ClearingSessionWorkflow."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_scan_result(),
        )
        assert result.lot_number is None

    @pytest.mark.asyncio
    async def test_audit_written_on_accepted(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            mock_results=_make_scan_result(),
        )
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_instrument_id_in_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_input(instrument_id="OUT-INST-XYZ"),
            mock_results=_make_scan_result(),
        )
        assert result.instrument_id == "OUT-INST-XYZ"


class TestOutwardScanCTSRejected:
    @pytest.mark.asyncio
    async def test_cts_rejected_when_compliance_fails(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mock = _make_scan_result(compliance_ok=False)
        mock["compliance"] = MagicMock(
            is_compliant=False,
            violations=["MICR_LINE_MISSING"],
        )
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.outcome == "CTS_REJECTED"

    @pytest.mark.asyncio
    async def test_audit_written_on_cts_rejected(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mock = _make_scan_result(compliance_ok=False)
        mock["compliance"] = MagicMock(is_compliant=False, violations=["DARK_IMAGE"])
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_violations_in_result_on_rejection(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mock = _make_scan_result()
        mock["compliance"] = MagicMock(is_compliant=False, violations=["OVEREXPOSED"])
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.outcome == "CTS_REJECTED"
        assert result.violations is not None

    @pytest.mark.asyncio
    async def test_no_lot_assigned_on_rejection(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mock = _make_scan_result()
        mock["compliance"] = MagicMock(is_compliant=False, violations=["DARK_IMAGE"])
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.lot_number is None


class TestOutwardScanWorkflowId:
    def test_workflow_id_is_deterministic(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        assert wf.workflow_id("bank-a", "SCAN-1") == wf.workflow_id("bank-a", "SCAN-1")

    def test_workflow_id_unique_per_scan(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        assert wf.workflow_id("bank-a", "SCAN-1") != wf.workflow_id("bank-a", "SCAN-2")
