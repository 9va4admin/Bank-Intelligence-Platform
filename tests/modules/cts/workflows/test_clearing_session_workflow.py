"""
Tests for ClearingSessionWorkflow — manages one clearing session per SB.

TDD RED phase: must FAIL before implementation is written.
"""
import pytest
from unittest.mock import AsyncMock

from modules.cts.workflows.clearing_session_workflow import (
    ClearingSessionWorkflow,
    ClearingSessionInput,
    ClearingSessionResult,
    DeploymentMode,
    SessionType,
)


# --------------------------------------------------------------------------- #
# Model tests
# --------------------------------------------------------------------------- #
class TestClearingSessionInput:
    def test_sb_ngch_mode_no_sb_connection_needed(self):
        inp = ClearingSessionInput(
            session_id="sess-001",
            bank_id="saraswat-coop",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-mumbai", "pu-pune"],
        )
        assert inp.deployment_mode == DeploymentMode.SB_NGCH
        assert inp.sb_connection_id is None

    def test_agency_mode_requires_sb_connection_id(self):
        inp = ClearingSessionInput(
            session_id="sess-002",
            bank_id="cosmos-agency",
            clearing_date="2026-07-05",
            session_type=SessionType.AFTERNOON,
            deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
            sb_connection_id="sbconn-saraswat",
            sb_bank_id="saraswat-coop",
            pu_ids=["pu-a", "pu-b"],
        )
        assert inp.sb_connection_id == "sbconn-saraswat"
        assert inp.sb_bank_id == "saraswat-coop"

    def test_frozen(self):
        inp = ClearingSessionInput(
            session_id="s",
            bank_id="b",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-1"],
        )
        with pytest.raises(Exception):
            inp.bank_id = "other"  # type: ignore[misc]


class TestClearingSessionResult:
    def test_submitted_result(self):
        r = ClearingSessionResult(
            outcome="SUBMITTED",
            session_id="sess-001",
            bank_id="saraswat-coop",
            total_instruments=120,
            ngch_reference="NGCH-REF-999",
            audit_written=True,
        )
        assert r.outcome == "SUBMITTED"
        assert r.total_instruments == 120

    def test_exception_result(self):
        r = ClearingSessionResult(
            outcome="EXCEPTION",
            session_id="sess-002",
            bank_id="saraswat-coop",
            total_instruments=0,
            failure_reason="SB_CONNECTOR_FAILED",
            audit_written=True,
        )
        assert r.failure_reason == "SB_CONNECTOR_FAILED"


# --------------------------------------------------------------------------- #
# Workflow ID generation
# --------------------------------------------------------------------------- #
class TestClearingSessionWorkflowId:
    def test_workflow_id_format(self):
        wf = ClearingSessionWorkflow()
        wid = wf.workflow_id("saraswat-coop", "2026-07-05", "MORNING")
        assert wid == "cts-clearsess-saraswat-coop-2026-07-05-MORNING"

    def test_workflow_id_agency_mode(self):
        wf = ClearingSessionWorkflow()
        wid = wf.workflow_id("cosmos-agency", "2026-07-05", "AFTERNOON", sb_bank_id="saraswat-coop")
        assert wid == "cts-clearsess-cosmos-agency-saraswat-coop-2026-07-05-AFTERNOON"

    def test_workflow_id_is_deterministic(self):
        wf = ClearingSessionWorkflow()
        id1 = wf.workflow_id("bank-a", "2026-07-05", "MORNING")
        id2 = wf.workflow_id("bank-a", "2026-07-05", "MORNING")
        assert id1 == id2


# --------------------------------------------------------------------------- #
# SB_NGCH mode — triggers NGCHSubmissionWorkflow
# --------------------------------------------------------------------------- #
class TestClearingSessionWorkflowSBNGCHMode:
    def _make_mocks(self, instrument_count: int = 50) -> dict:
        return {
            "seal_all_lots": [
                {"pu_id": "pu-mumbai", "lot_number": "LOT-001", "instrument_count": 30},
                {"pu_id": "pu-pune",   "lot_number": "LOT-002", "instrument_count": 20},
            ],
            "ngch_submission": {
                "outcome": "SUBMITTED",
                "ngch_reference": "NGCH-2026-0705-001",
            },
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }

    @pytest.mark.asyncio
    async def test_sb_ngch_mode_returns_submitted(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-sb-001",
            bank_id="saraswat-coop",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-mumbai", "pu-pune"],
        )
        result = await wf.run_with_mocks(inp, self._make_mocks())
        assert result.outcome == "SUBMITTED"
        assert result.total_instruments == 50

    @pytest.mark.asyncio
    async def test_sb_ngch_mode_ngch_reference_propagated(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-sb-002",
            bank_id="saraswat-coop",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-1"],
        )
        mocks = {
            "seal_all_lots": [
                {"pu_id": "pu-1", "lot_number": "LOT-A", "instrument_count": 10},
            ],
            "ngch_submission": {"outcome": "SUBMITTED", "ngch_reference": "NGCH-XYZ"},
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.ngch_reference == "NGCH-XYZ"

    @pytest.mark.asyncio
    async def test_ngch_submission_failure_produces_exception_outcome(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-sb-003",
            bank_id="saraswat-coop",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-1"],
        )
        mocks = {
            "seal_all_lots": [
                {"pu_id": "pu-1", "lot_number": "LOT-B", "instrument_count": 5},
            ],
            "ngch_submission": {"outcome": "SUBMISSION_FAILED", "ngch_reference": None},
            "update_session_status": {"status": "EXCEPTION"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "EXCEPTION"
        assert result.failure_reason == "NGCH_SUBMISSION_FAILED"

    @pytest.mark.asyncio
    async def test_audit_always_written_on_sb_ngch_success(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-sb-004",
            bank_id="b",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-x"],
        )
        mocks = {
            "seal_all_lots": [{"pu_id": "pu-x", "lot_number": "L-X", "instrument_count": 1}],
            "ngch_submission": {"outcome": "SUBMITTED", "ngch_reference": "REF-X"},
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.audit_written is True


# --------------------------------------------------------------------------- #
# AGENCY_SB_RELAY mode — triggers AgencyCCWorkflow
# --------------------------------------------------------------------------- #
class TestClearingSessionWorkflowAgencyMode:
    def _inp(self) -> ClearingSessionInput:
        return ClearingSessionInput(
            session_id="sess-agency-001",
            bank_id="cosmos-agency",
            clearing_date="2026-07-05",
            session_type=SessionType.AFTERNOON,
            deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
            sb_connection_id="sbconn-saraswat",
            sb_bank_id="saraswat-coop",
            pu_ids=["pu-thane", "pu-vasai"],
        )

    def _mocks(self) -> dict:
        return {
            "seal_all_lots": [
                {"pu_id": "pu-thane", "lot_number": "LOT-T1", "instrument_count": 40},
                {"pu_id": "pu-vasai", "lot_number": "LOT-V1", "instrument_count": 35},
            ],
            "agency_cc": {
                "outcome": "SUBMITTED_TO_SB",
                "sb_reference": "SB-SFTP-0099",
            },
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }

    @pytest.mark.asyncio
    async def test_agency_mode_returns_submitted_to_sb(self):
        wf = ClearingSessionWorkflow()
        result = await wf.run_with_mocks(self._inp(), self._mocks())
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.total_instruments == 75

    @pytest.mark.asyncio
    async def test_agency_mode_propagates_sb_reference(self):
        wf = ClearingSessionWorkflow()
        result = await wf.run_with_mocks(self._inp(), self._mocks())
        assert result.ngch_reference == "SB-SFTP-0099"

    @pytest.mark.asyncio
    async def test_agency_mode_agency_cc_failure_produces_exception(self):
        wf = ClearingSessionWorkflow()
        mocks = {
            "seal_all_lots": [
                {"pu_id": "pu-thane", "lot_number": "LOT-T2", "instrument_count": 10},
            ],
            "agency_cc": {"outcome": "SB_REJECTED", "sb_reference": None},
            "update_session_status": {"status": "EXCEPTION"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.outcome == "EXCEPTION"
        assert result.failure_reason == "AGENCY_CC_FAILED"

    @pytest.mark.asyncio
    async def test_agency_mode_audit_written_on_failure(self):
        wf = ClearingSessionWorkflow()
        mocks = {
            "seal_all_lots": [{"pu_id": "pu-thane", "lot_number": "L-T", "instrument_count": 5}],
            "agency_cc": {"outcome": "SB_REJECTED", "sb_reference": None},
            "update_session_status": {"status": "EXCEPTION"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_zero_lots_sealed_produces_empty_session_outcome(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-empty",
            bank_id="cosmos-agency",
            clearing_date="2026-07-05",
            session_type=SessionType.EVENING,
            deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
            sb_connection_id="sbconn-x",
            sb_bank_id="sb-x",
            pu_ids=["pu-a"],
        )
        mocks = {
            "seal_all_lots": [],  # no lots
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "EMPTY_SESSION"
        assert result.total_instruments == 0


# --------------------------------------------------------------------------- #
# Instrument count aggregation
# --------------------------------------------------------------------------- #
class TestInstrumentCountAggregation:
    @pytest.mark.asyncio
    async def test_counts_summed_across_all_pu_lots(self):
        wf = ClearingSessionWorkflow()
        inp = ClearingSessionInput(
            session_id="sess-sum",
            bank_id="b",
            clearing_date="2026-07-05",
            session_type=SessionType.MORNING,
            deployment_mode=DeploymentMode.SB_NGCH,
            pu_ids=["pu-1", "pu-2", "pu-3"],
        )
        mocks = {
            "seal_all_lots": [
                {"pu_id": "pu-1", "lot_number": "L1", "instrument_count": 100},
                {"pu_id": "pu-2", "lot_number": "L2", "instrument_count": 200},
                {"pu_id": "pu-3", "lot_number": "L3", "instrument_count": 50},
            ],
            "ngch_submission": {"outcome": "SUBMITTED", "ngch_reference": "R"},
            "update_session_status": {"status": "SUBMITTED"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.total_instruments == 350
