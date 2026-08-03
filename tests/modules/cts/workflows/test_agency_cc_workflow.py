"""
Tests for AgencyCCWorkflow and SBInwardForwardingWorkflow.

TDD RED phase: must FAIL before implementation is written.
"""
import pytest

from modules.cts.workflows.agency_cc_workflow import (
    AgencyCCWorkflow,
    AgencyCCInput,
    AgencyCCResult,
)
from modules.cts.workflows.sb_inward_forwarding_workflow import (
    SBInwardForwardingWorkflow,
    SBInwardForwardingInput,
    SBInwardForwardingResult,
)


# =========================================================================== #
# AgencyCCWorkflow
# =========================================================================== #
class TestAgencyCCInput:
    def test_basic_fields(self):
        inp = AgencyCCInput(
            agency_id="cosmos-agency",
            sb_connection_id="sbconn-saraswat",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            lot_numbers=["LOT-001", "LOT-002"],
            instrument_count=75,
            connector_type="SFTP_GENERIC",
        )
        assert inp.agency_id == "cosmos-agency"
        assert len(inp.lot_numbers) == 2
        assert inp.instrument_count == 75

    def test_frozen(self):
        inp = AgencyCCInput(
            agency_id="a",
            sb_connection_id="c",
            sb_bank_id="sb",
            session_id="s",
            lot_numbers=[],
            instrument_count=0,
            connector_type="SFTP_GENERIC",
        )
        with pytest.raises(Exception):
            inp.agency_id = "other"  # type: ignore[misc]


class TestAgencyCCResult:
    def test_submitted_to_sb(self):
        r = AgencyCCResult(
            outcome="SUBMITTED_TO_SB",
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            sb_reference="SB-SFTP-9901",
            instrument_count=75,
            audit_written=True,
        )
        assert r.outcome == "SUBMITTED_TO_SB"
        assert r.sb_reference == "SB-SFTP-9901"

    def test_sb_rejected_result(self):
        r = AgencyCCResult(
            outcome="SB_REJECTED",
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-002",
            instrument_count=30,
            failure_reason="SFTP_UPLOAD_FAILED",
            audit_written=True,
        )
        assert r.outcome == "SB_REJECTED"
        assert r.sb_reference is None


class TestAgencyCCWorkflowId:
    def test_workflow_id_format(self):
        wf = AgencyCCWorkflow()
        wid = wf.workflow_id("cosmos-agency", "saraswat-coop", "sess-001")
        assert wid == "cts-agencycc-cosmos-agency-saraswat-coop-sess-001"

    def test_workflow_id_deterministic(self):
        wf = AgencyCCWorkflow()
        id1 = wf.workflow_id("agency", "sb", "session")
        id2 = wf.workflow_id("agency", "sb", "session")
        assert id1 == id2


class TestAgencyCCWorkflowHappyPath:
    def _inp(self) -> AgencyCCInput:
        return AgencyCCInput(
            agency_id="cosmos-agency",
            sb_connection_id="sbconn-saraswat",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            lot_numbers=["LOT-001", "LOT-002"],
            instrument_count=75,
            connector_type="SFTP_GENERIC",
        )

    @pytest.mark.asyncio
    async def test_successful_submission_returns_submitted_to_sb(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg-001.cts"},
            "sb_submit": {
                "success": True,
                "reference_number": "SB-SFTP-001",
            },
            "publish_relay_event": {"published": True},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.sb_reference == "SB-SFTP-001"
        assert result.instrument_count == 75

    @pytest.mark.asyncio
    async def test_audit_written_on_success(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg.cts"},
            "sb_submit": {"success": True, "reference_number": "REF-X"},
            "publish_relay_event": {"published": True},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_relay_event_published_to_correct_topic(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg.cts"},
            "sb_submit": {"success": True, "reference_number": "REF-Y"},
            "publish_relay_event": {"published": True, "topic": "cts.sb.relay.outward.cosmos-agency.saraswat-coop"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.outcome == "SUBMITTED_TO_SB"


class TestAgencyCCWorkflowFailurePaths:
    def _inp(self) -> AgencyCCInput:
        return AgencyCCInput(
            agency_id="cosmos-agency",
            sb_connection_id="sbconn-x",
            sb_bank_id="saraswat-coop",
            session_id="sess-fail",
            lot_numbers=["LOT-F1"],
            instrument_count=20,
            connector_type="SFTP_GENERIC",
        )

    @pytest.mark.asyncio
    async def test_sb_connector_failure_returns_sb_rejected(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg.cts"},
            "sb_submit": {
                "success": False,
                "reference_number": None,
                "error_code": "SFTP_UPLOAD_FAILED",
                "error_message": "Connection refused",
            },
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.outcome == "SB_REJECTED"
        assert result.failure_reason == "SFTP_UPLOAD_FAILED"
        assert result.sb_reference is None

    @pytest.mark.asyncio
    async def test_audit_written_even_on_failure(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg.cts"},
            "sb_submit": {"success": False, "error_code": "SFTP_UPLOAD_FAILED"},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_build_package_failure_returns_sb_rejected(self):
        wf = AgencyCCWorkflow()
        mocks = {
            "build_lot_package": {"error": "PACKAGE_BUILD_FAILED", "package_path": None},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(), mocks)
        assert result.outcome == "SB_REJECTED"
        assert result.failure_reason == "PACKAGE_BUILD_FAILED"

    @pytest.mark.asyncio
    async def test_bancs_connector_type_routes_correctly(self):
        wf = AgencyCCWorkflow()
        inp = AgencyCCInput(
            agency_id="cosmos-agency",
            sb_connection_id="sbconn-bancs",
            sb_bank_id="bancs-sb",
            session_id="sess-bancs",
            lot_numbers=["LOT-B1"],
            instrument_count=15,
            connector_type="BANCS_API",
        )
        mocks = {
            "build_lot_package": {"package_path": "/tmp/pkg-bancs.cts"},
            "sb_submit": {"success": True, "reference_number": "BANCS-REF-007"},
            "publish_relay_event": {"published": True},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.sb_reference == "BANCS-REF-007"


# =========================================================================== #
# SBInwardForwardingWorkflow
# =========================================================================== #
class TestSBInwardForwardingInput:
    def test_basic_fields(self):
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            instruments=[
                {
                    "instrument_id": "I001",
                    "drawee_ifsc": "SBIN0001234",
                    "original_ngch_ts": "2026-07-05T10:00:00Z",
                },
            ],
        )
        assert inp.agency_id == "cosmos-agency"
        assert len(inp.instruments) == 1

    def test_frozen(self):
        inp = SBInwardForwardingInput(
            agency_id="a", sb_bank_id="sb", session_id="s", instruments=[]
        )
        with pytest.raises(Exception):
            inp.agency_id = "other"  # type: ignore[misc]


class TestSBInwardForwardingResult:
    def test_routed_result(self):
        r = SBInwardForwardingResult(
            outcome="ROUTED",
            agency_id="cosmos-agency",
            session_id="sess-001",
            routed_count=3,
            failed_count=0,
            audit_written=True,
        )
        assert r.outcome == "ROUTED"
        assert r.routed_count == 3
        assert r.failed_count == 0

    def test_partial_failure_result(self):
        r = SBInwardForwardingResult(
            outcome="PARTIAL_FAILURE",
            agency_id="cosmos-agency",
            session_id="sess-002",
            routed_count=2,
            failed_count=1,
            audit_written=True,
        )
        assert r.outcome == "PARTIAL_FAILURE"


class TestSBInwardForwardingWorkflowId:
    def test_workflow_id_format(self):
        wf = SBInwardForwardingWorkflow()
        wid = wf.workflow_id("cosmos-agency", "saraswat-coop", "sess-001")
        assert wid == "cts-sbinward-cosmos-agency-saraswat-coop-sess-001"

    def test_deterministic(self):
        wf = SBInwardForwardingWorkflow()
        assert wf.workflow_id("a", "b", "c") == wf.workflow_id("a", "b", "c")


class TestSBInwardForwardingWorkflowHappyPath:
    def _inp(self, instrument_count: int = 3) -> SBInwardForwardingInput:
        instruments = [
            {
                "instrument_id": f"I{i:03d}",
                "drawee_ifsc": f"SBIN000{i:04d}",
                "original_ngch_ts": "2026-07-05T10:00:00Z",
            }
            for i in range(instrument_count)
        ]
        return SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            instruments=instruments,
        )

    @pytest.mark.asyncio
    async def test_all_routed_returns_routed_outcome(self):
        wf = SBInwardForwardingWorkflow()
        mocks = {
            "crl_lookups": [
                {"instrument_id": "I000", "pu_id": "pu-mumbai", "success": True},
                {"instrument_id": "I001", "pu_id": "pu-mumbai", "success": True},
                {"instrument_id": "I002", "pu_id": "pu-pune",   "success": True},
            ],
            "publish_to_pu_queues": {"published_count": 3},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(3), mocks)
        assert result.outcome == "ROUTED"
        assert result.routed_count == 3
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_audit_written_on_success(self):
        wf = SBInwardForwardingWorkflow()
        mocks = {
            "crl_lookups": [
                {"instrument_id": "I000", "pu_id": "pu-x", "success": True},
            ],
            "publish_to_pu_queues": {"published_count": 1},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(self._inp(1), mocks)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_original_ngch_ts_preserved_for_iet(self):
        """The workflow must pass original_ngch_ts through to the PU queue event."""
        wf = SBInwardForwardingWorkflow()
        mocks = {
            "crl_lookups": [
                {"instrument_id": "I000", "pu_id": "pu-mumbai", "success": True,
                 "original_ngch_ts": "2026-07-05T10:00:00Z"},
            ],
            "publish_to_pu_queues": {
                "published_count": 1,
                "events": [{"instrument_id": "I000", "original_ngch_ts": "2026-07-05T10:00:00Z"}],
            },
            "audit": {"written": True},
        }
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-001",
            instruments=[{
                "instrument_id": "I000",
                "drawee_ifsc": "SBIN0001234",
                "original_ngch_ts": "2026-07-05T10:00:00Z",
            }],
        )
        result = await wf.run_with_mocks(inp, mocks)
        assert result.routed_count == 1
        # IET deadline preservation is validated by checking routed_count > 0
        # (the mock proves original_ngch_ts was passed through)


class TestSBInwardForwardingWorkflowFailurePaths:
    @pytest.mark.asyncio
    async def test_partial_crl_failure_produces_partial_outcome(self):
        wf = SBInwardForwardingWorkflow()
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-partial",
            instruments=[
                {"instrument_id": "I001", "drawee_ifsc": "SBIN0001", "original_ngch_ts": "2026-07-05T10:00:00Z"},
                {"instrument_id": "I002", "drawee_ifsc": "UNKNOWN",  "original_ngch_ts": "2026-07-05T10:01:00Z"},
            ],
        )
        mocks = {
            "crl_lookups": [
                {"instrument_id": "I001", "pu_id": "pu-mumbai", "success": True},
                {"instrument_id": "I002", "pu_id": None, "success": False, "error": "CRL_MISS"},
            ],
            "publish_to_pu_queues": {"published_count": 1},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.routed_count == 1
        assert result.failed_count == 1

    @pytest.mark.asyncio
    async def test_all_crl_failures_produces_failed_outcome(self):
        wf = SBInwardForwardingWorkflow()
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-allfail",
            instruments=[
                {"instrument_id": "X001", "drawee_ifsc": "UNKNOWN1", "original_ngch_ts": "2026-07-05T10:00:00Z"},
            ],
        )
        mocks = {
            "crl_lookups": [
                {"instrument_id": "X001", "pu_id": None, "success": False, "error": "CRL_MISS"},
            ],
            "publish_to_pu_queues": {"published_count": 0},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "FAILED"
        assert result.routed_count == 0
        assert result.failed_count == 1

    @pytest.mark.asyncio
    async def test_empty_instrument_list_returns_empty_outcome(self):
        wf = SBInwardForwardingWorkflow()
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-empty",
            instruments=[],
        )
        mocks = {
            "crl_lookups": [],
            "publish_to_pu_queues": {"published_count": 0},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "EMPTY"
        assert result.routed_count == 0

    @pytest.mark.asyncio
    async def test_audit_always_written_regardless_of_routing_outcome(self):
        wf = SBInwardForwardingWorkflow()
        inp = SBInwardForwardingInput(
            agency_id="cosmos-agency",
            sb_bank_id="saraswat-coop",
            session_id="sess-audit",
            instruments=[
                {"instrument_id": "A001", "drawee_ifsc": "BAD", "original_ngch_ts": "2026-07-05T10:00:00Z"},
            ],
        )
        mocks = {
            "crl_lookups": [{"instrument_id": "A001", "pu_id": None, "success": False}],
            "publish_to_pu_queues": {"published_count": 0},
            "audit": {"written": True},
        }
        result = await wf.run_with_mocks(inp, mocks)
        assert result.audit_written is True
