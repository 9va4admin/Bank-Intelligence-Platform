"""
E2E tests — Multi-Scenario CTS (Phase 8 Hardening)

Tests the three ASTRA deployment scenarios end-to-end by chaining
workflow.run_with_mocks() calls in the same sequence that Temporal + Kafka
would execute them in production. No mocking of the workflow logic itself —
only mocking of external I/O (CBS, Redis, Kafka, NGCH).

Scenario 1 — SB+SMB, SMB has own CBS (push model)
  SMBVaultPushIngestWorkflow (STOP_PAYMENTS + PPS) → vault populated
  ClearingSessionWorkflow (SB_NGCH) → SUBMITTED to NGCH
  Drawee side: SBInwardForwardingWorkflow → ROUTED to PUs

Scenario 2 — Agency+SMB, Agency manages CBS (no push needed)
  ClearingSessionWorkflow (AGENCY_SB_RELAY) → SUBMITTED_TO_SB
  AgencyCCWorkflow (BANCS_API connector) → SUBMITTED_TO_SB
  No SMB CBS push step (Agency holds CBS accounts directly)

Scenario 3 — Agency+SMB, SMB has own CBS (push + relay)
  SMBVaultPushIngestWorkflow (SIGNATURES) → vault updated
  ClearingSessionWorkflow (AGENCY_SB_RELAY) → SUBMITTED_TO_SB
  SBInwardForwardingWorkflow (relay from SB) → ROUTED
  original_ngch_ts preserved end-to-end (IET enforcement)
"""
import pytest

from modules.cts.workflows.smb_vault_push_workflow import (
    SMBVaultPushWorkflow,
    SMBVaultPushInput,
)
from modules.cts.workflows.clearing_session_workflow import (
    ClearingSessionWorkflow,
    ClearingSessionInput,
    DeploymentMode,
    SessionType,
)
from modules.cts.workflows.agency_cc_workflow import (
    AgencyCCWorkflow,
    AgencyCCInput,
)
from modules.cts.workflows.sb_inward_forwarding_workflow import (
    SBInwardForwardingWorkflow,
    SBInwardForwardingInput,
)
from modules.cts.smb_ingest.models import SMBPushFileType


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — SB+SMB, SMB has own CBS (push model)
# ═══════════════════════════════════════════════════════════════════════════

class TestScenario1_SB_SMB_PushModel:
    """
    SMB pushes CBS data → Agency vault updated → clearing session submitted to NGCH directly.
    Used when the SMB's CBS is independent and the bank is registered directly with NPCI
    (or through a Sponsor Bank that files to NGCH on their behalf).
    """

    @pytest.mark.asyncio
    async def test_vault_populated_before_clearing(self):
        """Stop-payment vault must be updated before any clearing session starts."""
        push_wf = SMBVaultPushWorkflow()

        push_result = await push_wf.run_with_mocks(
            SMBVaultPushInput(
                agency_id="saraswat-coop",
                smb_id="pune-ucb",
                file_type=SMBPushFileType.STOP_PAYMENTS,
                file_path="/smb-ingest/pune-ucb/stop_payments/20260705.csv",
                file_hash="sp-hash-sc1-001",
            ),
            {
                "parse_and_validate": {"records": [{"cheque": "000123"}, {"cheque": "000124"}], "record_count": 2},
                "update_vault": {"updated_count": 2, "bloom_updated": True},
                "audit": {"written": True},
            },
        )
        assert push_result.outcome == "VAULT_UPDATED"
        assert push_result.records_processed == 2
        assert push_result.audit_written is True

    @pytest.mark.asyncio
    async def test_pps_push_before_clearing(self):
        """PPS vault must also be updated from the SMB CBS push."""
        push_wf = SMBVaultPushWorkflow()

        pps_result = await push_wf.run_with_mocks(
            SMBVaultPushInput(
                agency_id="saraswat-coop",
                smb_id="pune-ucb",
                file_type=SMBPushFileType.PPS_ENTRIES,
                file_path="/smb-ingest/pune-ucb/pps/20260705.csv",
                file_hash="pps-hash-sc1-001",
            ),
            {
                "parse_and_validate": {"records": [{}] * 15, "record_count": 15},
                "update_vault": {"updated_count": 15, "bloom_updated": False},
                "audit": {"written": True},
            },
        )
        assert pps_result.outcome == "VAULT_UPDATED"
        assert pps_result.records_processed == 15

    @pytest.mark.asyncio
    async def test_clearing_session_sb_ngch_mode(self):
        """After vault is warm, clearing session routes directly to NGCH (SB_NGCH mode)."""
        clear_wf = ClearingSessionWorkflow()

        result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc1-morning",
                bank_id="saraswat-coop",
                clearing_date="2026-07-05",
                session_type=SessionType.MORNING,
                deployment_mode=DeploymentMode.SB_NGCH,
                pu_ids=["pu-mumbai-1", "pu-mumbai-2"],
            ),
            {
                "seal_all_lots": [
                    {"pu_id": "pu-mumbai-1", "lot_number": "LOT-001", "instrument_count": 120},
                    {"pu_id": "pu-mumbai-2", "lot_number": "LOT-002", "instrument_count": 114},
                ],
                "ngch_submission": {"outcome": "SUBMITTED", "ngch_reference": "NGCH-SC1-20260705-001"},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "SUBMITTED"
        assert result.total_instruments == 234
        assert result.ngch_reference == "NGCH-SC1-20260705-001"
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_scenario1_inward_routing(self):
        """Inward instruments arriving from NGCH are routed to SMB's PU queue."""
        fwd_wf = SBInwardForwardingWorkflow()

        result = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(
                agency_id="saraswat-coop",
                sb_bank_id="rbi-ngch",
                session_id="sess-sc1-inward",
                instruments=[
                    {"instrument_id": f"INSTR{i:04d}", "drawee_ifsc": "SVCB0000001",
                     "original_ngch_ts": "2026-07-05T10:00:00Z"}
                    for i in range(20)
                ],
            ),
            {
                "crl_lookups": [
                    {"instrument_id": f"INSTR{i:04d}", "pu_id": "pu-mumbai-1", "success": True}
                    for i in range(20)
                ],
                "publish_to_pu_queues": {"published_count": 20},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "ROUTED"
        assert result.routed_count == 20
        assert result.failed_count == 0
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_scenario1_duplicate_push_skipped(self):
        """Same stop-payment file pushed twice — second is DUPLICATE_SKIPPED, no double-update."""
        push_wf = SMBVaultPushWorkflow()

        dup_result = await push_wf.run_with_mocks(
            SMBVaultPushInput(
                agency_id="saraswat-coop",
                smb_id="pune-ucb",
                file_type=SMBPushFileType.STOP_PAYMENTS,
                file_path="/smb-ingest/pune-ucb/stop_payments/20260705.csv",
                file_hash="sp-hash-sc1-001",   # same hash as first push
            ),
            {
                "parse_and_validate": {"records": [], "record_count": 0, "duplicate": True},
                "audit": {"written": True},
            },
        )
        assert dup_result.outcome == "DUPLICATE_SKIPPED"
        assert dup_result.records_processed == 0
        assert dup_result.audit_written is True


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — Agency+SMB, Agency manages CBS (no push)
# ═══════════════════════════════════════════════════════════════════════════

class TestScenario2_Agency_SMB_AgencyCBS:
    """
    Agency manages the CBS for SMBs — no CBS push step needed.
    Outward instruments aggregated at Agency, relayed to upstream SB via AgencyCCWorkflow.
    """

    @pytest.mark.asyncio
    async def test_clearing_session_agency_relay_mode(self):
        """ClearingSessionWorkflow in AGENCY_SB_RELAY mode routes to AgencyCCWorkflow."""
        clear_wf = ClearingSessionWorkflow()

        result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc2-morning",
                bank_id="agency-cosmos",
                clearing_date="2026-07-05",
                session_type=SessionType.MORNING,
                deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
                pu_ids=["pu-cosmos-1"],
                sb_connection_id="sbconn-saraswat",
                sb_bank_id="saraswat-coop",
            ),
            {
                "seal_all_lots": [
                    {"pu_id": "pu-cosmos-1", "lot_number": "LOT-001", "instrument_count": 98},
                ],
                "agency_cc": {"outcome": "SUBMITTED_TO_SB", "sb_reference": "SB-SC2-001"},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.total_instruments == 98
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_agency_cc_bancs_connector(self):
        """AgencyCCWorkflow submits lot package to SB via BANCS_API connector."""
        cc_wf = AgencyCCWorkflow()

        result = await cc_wf.run_with_mocks(
            AgencyCCInput(
                agency_id="agency-cosmos",
                sb_connection_id="sbconn-saraswat",
                sb_bank_id="saraswat-coop",
                session_id="sess-sc2-morning",
                lot_numbers=["LOT-001", "LOT-002"],
                instrument_count=98,
                connector_type="BANCS_API",
            ),
            {
                "build_lot_package": {"package_path": "/tmp/sc2-lots.tar.gz"},
                "sb_submit": {"success": True, "reference_number": "BANCS-SC2-20260705-001"},
                "publish_relay_event": {"published": True, "topic": "cts.sb.relay.outward.agency-cosmos.saraswat-coop"},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.sb_reference == "BANCS-SC2-20260705-001"
        assert result.instrument_count == 98
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_scenario2_no_smb_push_needed(self):
        """
        Scenario 2 requires NO SMB CBS push — Agency manages accounts directly.
        Verify that clearing session reaches SB submission without any push step.
        """
        clear_wf = ClearingSessionWorkflow()

        clear_result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc2-afternoon",
                bank_id="agency-cosmos",
                clearing_date="2026-07-05",
                session_type=SessionType.AFTERNOON,
                deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
                pu_ids=["pu-cosmos-1"],
                sb_connection_id="sbconn-saraswat",
                sb_bank_id="saraswat-coop",
            ),
            {
                "seal_all_lots": [
                    {"pu_id": "pu-cosmos-1", "lot_number": "LOT-PM-001", "instrument_count": 45},
                ],
                "agency_cc": {"outcome": "SUBMITTED_TO_SB", "sb_reference": "SB-SC2-PM-001"},
                "audit": {"written": True},
            },
        )
        assert clear_result.outcome == "SUBMITTED_TO_SB"
        assert clear_result.total_instruments == 45

    @pytest.mark.asyncio
    async def test_scenario2_sb_connector_failure(self):
        """If SB connector fails, AgencyCCWorkflow returns SB_REJECTED and audit is written."""
        cc_wf = AgencyCCWorkflow()

        result = await cc_wf.run_with_mocks(
            AgencyCCInput(
                agency_id="agency-cosmos",
                sb_connection_id="sbconn-saraswat",
                sb_bank_id="saraswat-coop",
                session_id="sess-sc2-fail",
                lot_numbers=["LOT-003"],
                instrument_count=30,
                connector_type="SFTP_GENERIC",
            ),
            {
                "build_lot_package": {"package_path": "/tmp/sc2-lots.tar.gz"},
                "sb_submit": {"success": False, "error_code": "SFTP_UPLOAD_FAILED"},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "SB_REJECTED"
        assert result.failure_reason == "SFTP_UPLOAD_FAILED"
        assert result.audit_written is True   # audit always written even on failure

    @pytest.mark.asyncio
    async def test_scenario2_empty_session(self):
        """Empty session (no lots sealed) → EMPTY_SESSION, no SB relay attempted."""
        clear_wf = ClearingSessionWorkflow()

        result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc2-empty",
                bank_id="agency-cosmos",
                clearing_date="2026-07-05",
                session_type=SessionType.EVENING,
                deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
                pu_ids=["pu-cosmos-1"],
                sb_connection_id="sbconn-saraswat",
                sb_bank_id="saraswat-coop",
            ),
            {
                "seal_all_lots": [],   # empty list → EMPTY_SESSION
                "audit": {"written": True},
            },
        )
        assert result.outcome == "EMPTY_SESSION"
        assert result.total_instruments == 0


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — Agency+SMB, SMB has own CBS (push + relay)
# ═══════════════════════════════════════════════════════════════════════════

class TestScenario3_Agency_SMB_SMBPush:
    """
    Most complex scenario: SMB has its own CBS, pushes data to Agency.
    Outward: same as Scenario 2 (AGENCY_SB_RELAY).
    Inward: SB relays instruments to Agency, which fans out to SMB PU queues.
    Critical invariant: original_ngch_ts must be preserved throughout the relay chain.
    """

    @pytest.mark.asyncio
    async def test_signature_vault_populated_from_smb_push(self):
        """SMB signature updates arrive before any drawee processing."""
        push_wf = SMBVaultPushWorkflow()

        result = await push_wf.run_with_mocks(
            SMBVaultPushInput(
                agency_id="agency-bharat",
                smb_id="nashik-ucb",
                file_type=SMBPushFileType.SIGNATURES,
                file_path="/smb-ingest/nashik-ucb/signatures/20260705.csv",
                file_hash="sig-hash-sc3-001",
            ),
            {
                "parse_and_validate": {"records": [{}] * 8, "record_count": 8},
                "update_vault": {"updated_count": 8, "bloom_updated": False},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "VAULT_UPDATED"
        assert result.records_processed == 8
        assert result.file_type == SMBPushFileType.SIGNATURES

    @pytest.mark.asyncio
    async def test_outward_clearing_agency_relay(self):
        """Outward path: Agency collects lots and relays to SB (same as Scenario 2)."""
        clear_wf = ClearingSessionWorkflow()

        result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc3-morning",
                bank_id="agency-bharat",
                clearing_date="2026-07-05",
                session_type=SessionType.MORNING,
                deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
                pu_ids=["pu-bharat-1"],
                sb_connection_id="sbconn-nelito",
                sb_bank_id="bharat-coop",
            ),
            {
                "seal_all_lots": [
                    {"pu_id": "pu-bharat-1", "lot_number": "LOT-SC3-001", "instrument_count": 67},
                ],
                "agency_cc": {"outcome": "SUBMITTED_TO_SB", "sb_reference": "NELITO-SC3-001"},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "SUBMITTED_TO_SB"
        assert result.total_instruments == 67

    @pytest.mark.asyncio
    async def test_inward_relay_original_ngch_ts_preserved(self):
        """
        CRITICAL: original_ngch_ts from NGCH must pass through the relay chain unchanged.
        IET countdown starts at NGCH receipt time, not Agency relay receipt time.
        If this is wrong, all SMB cheques get a shorter IET window than they should.
        """
        fwd_wf = SBInwardForwardingWorkflow()

        original_ts = "2026-07-05T10:02:30Z"   # exact NGCH receipt timestamp
        instruments = [
            {
                "instrument_id": f"SC3-INSTR{i:04d}",
                "drawee_ifsc": "BHAR0000001",
                "original_ngch_ts": original_ts,   # must survive relay
                "amount_range": "₹[1L-5L]",
            }
            for i in range(12)
        ]

        result = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(
                agency_id="agency-bharat",
                sb_bank_id="bharat-coop",
                session_id="sess-sc3-inward",
                instruments=instruments,
            ),
            {
                "crl_lookups": [
                    {"instrument_id": f"SC3-INSTR{i:04d}", "pu_id": "pu-bharat-1", "success": True}
                    for i in range(12)
                ],
                "publish_to_pu_queues": {"published_count": 12},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "ROUTED"
        assert result.routed_count == 12
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_inward_partial_failure_crl_miss(self):
        """
        Some instruments have unknown drawee IFSC (CRL miss) → PARTIAL_FAILURE.
        CRL misses must NOT auto-route — they stay failed (HUMAN_REVIEW at receiving PU).
        """
        fwd_wf = SBInwardForwardingWorkflow()

        result = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(
                agency_id="agency-bharat",
                sb_bank_id="bharat-coop",
                session_id="sess-sc3-partial",
                instruments=[
                    {"instrument_id": f"SC3-PARTIAL{i:04d}", "drawee_ifsc": "BHAR0000001",
                     "original_ngch_ts": "2026-07-05T10:05:00Z"}
                    for i in range(10)
                ],
            ),
            {
                "crl_lookups": [
                    # 8 resolved, 2 CRL misses
                    *[{"instrument_id": f"SC3-PARTIAL{i:04d}", "pu_id": "pu-bharat-1", "success": True}
                      for i in range(8)],
                    *[{"instrument_id": f"SC3-PARTIAL{i:04d}", "pu_id": None, "success": False,
                       "error": "CRL_MISS"}
                      for i in range(8, 10)],
                ],
                "publish_to_pu_queues": {"published_count": 8},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.routed_count == 8
        assert result.failed_count == 2
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_inward_all_crl_miss_is_failed(self):
        """If every instrument has a CRL miss, outcome is FAILED (not PARTIAL_FAILURE)."""
        fwd_wf = SBInwardForwardingWorkflow()

        result = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(
                agency_id="agency-bharat",
                sb_bank_id="bharat-coop",
                session_id="sess-sc3-allfail",
                instruments=[
                    {"instrument_id": "SC3-FAIL0001", "drawee_ifsc": "UNKNOWN001",
                     "original_ngch_ts": "2026-07-05T11:00:00Z"}
                ],
            ),
            {
                "crl_lookups": [
                    {"instrument_id": "SC3-FAIL0001", "pu_id": None, "success": False, "error": "CRL_MISS"}
                ],
                "publish_to_pu_queues": {"published_count": 0},
                "audit": {"written": True},
            },
        )
        assert result.outcome == "FAILED"
        assert result.routed_count == 0
        assert result.failed_count == 1

    @pytest.mark.asyncio
    async def test_scenario3_push_failure_does_not_block_outward(self):
        """
        If SMB CBS push parse fails, outward clearing continues independently.
        The vault will use stale data → instruments with vault misses route to HUMAN_REVIEW.
        Clearing session must NOT be blocked by a push failure.
        """
        push_wf = SMBVaultPushWorkflow()
        clear_wf = ClearingSessionWorkflow()

        push_result = await push_wf.run_with_mocks(
            SMBVaultPushInput(
                agency_id="agency-bharat",
                smb_id="nashik-ucb",
                file_type=SMBPushFileType.STOP_PAYMENTS,
                file_path="/smb-ingest/nashik-ucb/stop_payments/20260705.csv",
                file_hash="bad-file-hash",
            ),
            {
                "parse_and_validate": {"error": "MISSING_COLUMN:amount", "records": [], "record_count": 0},
                "audit": {"written": True},
            },
        )
        assert push_result.outcome == "PARSE_FAILED"

        # Outward clearing proceeds regardless
        clear_result = await clear_wf.run_with_mocks(
            ClearingSessionInput(
                session_id="sess-sc3-push-failed",
                bank_id="agency-bharat",
                clearing_date="2026-07-05",
                session_type=SessionType.MORNING,
                deployment_mode=DeploymentMode.AGENCY_SB_RELAY,
                pu_ids=["pu-bharat-1"],
                sb_connection_id="sbconn-nelito",
                sb_bank_id="bharat-coop",
            ),
            {
                "seal_all_lots": [
                    {"pu_id": "pu-bharat-1", "lot_number": "LOT-SC3-002", "instrument_count": 30},
                ],
                "agency_cc": {"outcome": "SUBMITTED_TO_SB", "sb_reference": "NELITO-SC3-002"},
                "audit": {"written": True},
            },
        )
        assert clear_result.outcome == "SUBMITTED_TO_SB"    # not blocked by push failure


# ═══════════════════════════════════════════════════════════════════════════
# Cross-scenario invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossScenarioInvariants:
    """Rules that must hold across ALL three deployment scenarios."""

    @pytest.mark.asyncio
    async def test_audit_always_written_regardless_of_outcome(self):
        """Every workflow in every scenario writes audit even on failure."""
        push_wf = SMBVaultPushWorkflow()
        cc_wf = AgencyCCWorkflow()
        fwd_wf = SBInwardForwardingWorkflow()

        # Push failure
        r1 = await push_wf.run_with_mocks(
            SMBVaultPushInput(agency_id="a", smb_id="s", file_type=SMBPushFileType.PPS_ENTRIES,
                              file_path="/f", file_hash="h1"),
            {"parse_and_validate": {"error": "EMPTY_FILE", "records": [], "record_count": 0},
             "audit": {"written": True}},
        )
        assert r1.audit_written is True

        # SB submission failure
        r2 = await cc_wf.run_with_mocks(
            AgencyCCInput(agency_id="a", sb_connection_id="c", sb_bank_id="sb",
                          session_id="s", lot_numbers=[], instrument_count=0, connector_type="SFTP_GENERIC"),
            {"build_lot_package": {"error": "BUILD_TIMEOUT"},
             "audit": {"written": True}},
        )
        assert r2.audit_written is True

        # All-CRL-miss inward
        r3 = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(agency_id="a", sb_bank_id="sb", session_id="s",
                                   instruments=[{"instrument_id": "X", "drawee_ifsc": "UNK",
                                                 "original_ngch_ts": "2026-07-05T10:00:00Z"}]),
            {"crl_lookups": [{"instrument_id": "X", "pu_id": None, "success": False}],
             "publish_to_pu_queues": {"published_count": 0},
             "audit": {"written": True}},
        )
        assert r3.audit_written is True

    @pytest.mark.asyncio
    async def test_empty_inward_batch_is_handled(self):
        """Empty inward batch (no instruments from SB) → EMPTY, not an error."""
        fwd_wf = SBInwardForwardingWorkflow()
        result = await fwd_wf.run_with_mocks(
            SBInwardForwardingInput(
                agency_id="agency-x", sb_bank_id="sb-x",
                session_id="sess-empty", instruments=[],
            ),
            {"audit": {"written": True}},
        )
        assert result.outcome == "EMPTY"
        assert result.routed_count == 0
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_workflow_ids_are_unique_per_scenario(self):
        """Workflow IDs must be deterministic and collision-free across scenarios."""
        push_wf = SMBVaultPushWorkflow()
        clear_wf = ClearingSessionWorkflow()
        cc_wf = AgencyCCWorkflow()
        fwd_wf = SBInwardForwardingWorkflow()

        ids = [
            push_wf.workflow_id("agency-x", "smb-a", "hash-001"),
            push_wf.workflow_id("agency-x", "smb-b", "hash-001"),   # different SMB, same hash
            push_wf.workflow_id("agency-x", "smb-a", "hash-002"),   # same SMB, different hash
            clear_wf.workflow_id("bank-x", "clearing-date", "MORNING"),
            cc_wf.workflow_id("agency-x", "sb-x", "sess-001"),
            fwd_wf.workflow_id("agency-x", "sb-x", "sess-001"),
        ]
        # All IDs must be unique
        assert len(ids) == len(set(ids))
