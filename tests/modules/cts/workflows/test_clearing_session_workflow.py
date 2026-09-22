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


# --------------------------------------------------------------------------- #
# Real run() — Temporal test environment, real workflow + activity signatures.
# Regression coverage for the live-run defects fixed 2026-09-22:
#   - seal_all_lots is no longer looked up by a scanner/API session id
#   - one NGCH child workflow is started per lot, not one fake "consolidated" lot
#   - update_session_status receives npci_ack_ref (was silently dropped)
#   - successfully filed lots are marked SUBMITTED
# --------------------------------------------------------------------------- #
import asyncio
import uuid

from temporalio import activity as _activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


def _lot(lot_id, count=3):
    return {"lot_id": lot_id, "sequence_number": 1, "instrument_count": count, "branch_id": "br-1",
            "branch_ifsc": "KARB0000001", "pu_id": "KBL-PU-01", "routing_no": "KARB", "zone_id": "CHENNAI"}


def _seal_all_lots_fake(lots):
    @_activity.defn(name="seal_all_lots")
    async def fake(inp):
        from modules.cts.workflows.activities.clearing_session_activities import SealAllLotsResult
        return SealAllLotsResult(sealed_lots=lots, session_uuid="11111111-1111-1111-1111-111111111111",
                                 status="OK")
    return fake


@_activity.defn(name="build_ngch_file")
async def _fake_build_ngch(inp):
    from modules.cts.workflows.activities.ngch_submission_activities import BuildNGCHFileInput, BuildNGCHFileResult
    if isinstance(inp, dict):
        inp = BuildNGCHFileInput(**inp)
    return BuildNGCHFileResult(file_path=f"cxf/{inp.lot_number}", checksum_sha256="deadbeef",
                               instrument_count=inp.instrument_count, cxf_filename="CXF_1", cibf_filename="CIBF_1")


def _submit_to_ngch_fake(outcome_by_lot):
    @_activity.defn(name="submit_to_ngch")
    async def fake(inp):
        from modules.cts.workflows.activities.ngch_submission_activities import SubmitToNGCHInput, SubmitToNGCHResult
        if isinstance(inp, dict):
            inp = SubmitToNGCHInput(**inp)
        ok = outcome_by_lot.get(inp.lot_number, True)
        return SubmitToNGCHResult(submitted=ok, ngch_reference=f"NGCH-{inp.lot_number}" if ok else None,
                                  failure_reason=None if ok else "NGCH_REJECTED")
    return fake


def _confirm_ack_fake(outcome_by_lot):
    @_activity.defn(name="confirm_acknowledgement")
    async def fake(inp):
        from modules.cts.workflows.activities.ngch_submission_activities import (
            ConfirmAcknowledgementInput, ConfirmAcknowledgementResult,
        )
        if isinstance(inp, dict):
            inp = ConfirmAcknowledgementInput(**inp)
        ok = outcome_by_lot.get(inp.lot_number, True)
        return ConfirmAcknowledgementResult(acknowledged=ok, reason=None if ok else "NGCH_REJECTED")
    return fake


@_activity.defn(name="write_audit")
async def _fake_write_audit_cs(inp):
    return None


def _update_status_recorder(calls):
    @_activity.defn(name="update_session_status")
    async def fake(inp):
        from modules.cts.workflows.activities.clearing_session_activities import (
            UpdateSessionStatusInput, UpdateSessionStatusResult,
        )
        if isinstance(inp, dict):
            inp = UpdateSessionStatusInput(**inp)
        calls.append(inp)
        return UpdateSessionStatusResult(updated=True, status=inp.status)
    return fake


def _mark_submitted_recorder(calls):
    @_activity.defn(name="mark_lots_submitted")
    async def fake(inp):
        from modules.cts.workflows.activities.clearing_session_activities import MarkLotsSubmittedInput
        if isinstance(inp, dict):
            inp = MarkLotsSubmittedInput(**inp)
        calls.append(inp)
    return fake


def _cs_worker(env, task_queue, seal_fake, status_calls, submitted_calls, outcome_by_lot):
    from modules.cts.workflows.clearing_session_workflow import ClearingSessionWorkflow
    from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow
    return Worker(
        env.client, task_queue=task_queue,
        workflows=[ClearingSessionWorkflow, NGCHSubmissionWorkflow],
        activities=[
            seal_fake, _update_status_recorder(status_calls), _mark_submitted_recorder(submitted_calls),
            _fake_write_audit_cs, _fake_build_ngch,
            _submit_to_ngch_fake(outcome_by_lot), _confirm_ack_fake(outcome_by_lot),
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )


class TestClearingSessionWorkflowRealRun:
    async def _run(self, lots, outcome_by_lot):
        status_calls, submitted_calls = [], []
        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with _cs_worker(env, task_queue, _seal_all_lots_fake(lots), status_calls, submitted_calls,
                                   outcome_by_lot):
                result = await asyncio.wait_for(env.client.execute_workflow(
                    ClearingSessionWorkflow.run,
                    ClearingSessionInput(session_id="clearsess-xyz", bank_id="kbl", clearing_date="2026-09-21",
                                         session_type=SessionType.MORNING, deployment_mode=DeploymentMode.SB_NGCH,
                                         pu_ids=["KBL-PU-01"]),
                    id=f"cts-clearsess-real-{uuid.uuid4().hex[:8]}", task_queue=task_queue), timeout=60)
        return result, status_calls, submitted_calls

    @pytest.mark.asyncio
    async def test_all_lots_submitted(self):
        lots = [_lot("LOT-1"), _lot("LOT-2")]
        result, status_calls, submitted_calls = await self._run(lots, {"LOT-1": True, "LOT-2": True})
        assert result.outcome == "SUBMITTED"
        assert result.session_id == "11111111-1111-1111-1111-111111111111"
        assert {r["lot_id"] for r in result.lot_results} == {"LOT-1", "LOT-2"}
        assert result.ngch_reference == "NGCH-LOT-1,NGCH-LOT-2"
        # update_session_status must receive the ack refs via npci_ack_ref (was silently dropped before)
        assert status_calls[-1].npci_ack_ref == "NGCH-LOT-1,NGCH-LOT-2"
        assert status_calls[-1].status == "SUBMITTED"
        assert set(submitted_calls[-1].lot_ids) == {"LOT-1", "LOT-2"}

    @pytest.mark.asyncio
    async def test_one_lot_fails_overall_exception_but_good_lot_still_marked_submitted(self):
        lots = [_lot("LOT-1"), _lot("LOT-2")]
        result, status_calls, submitted_calls = await self._run(lots, {"LOT-1": True, "LOT-2": False})
        assert result.outcome == "EXCEPTION"
        assert "LOT-2" in result.failure_reason
        assert submitted_calls[-1].lot_ids == ["LOT-1"]
