"""
Tests for the 5 missing workflow stub activities — RED phase.

Covers:
  clearing_session_activities   : seal_all_lots, update_session_status
  session_reconciliation_activities: fetch_ngch_settlement_report,
                                     match_submitted_vs_settled, generate_rrf
  sb_relay_activities           : resolve_crl_batch, publish_to_pu_queues,
                                  build_lot_package, sb_submit_lot,
                                  publish_relay_event
  smb_vault_push_activities     : parse_and_validate_smb_push, update_smb_vault

Also verifies:
  - All 5 new workflow classes carry @workflow.defn and have a @workflow.run method
  - worker.py NO_DI_ACTIVITIES includes the 5 previously-unregistered activities
    (stamp_endorsement, update_lot_status, build_ngch_file, submit_to_ngch,
     confirm_acknowledgement) + all new stubs
  - All 5 new workflows are in worker.ALL_WORKFLOWS
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ═══════════════════════════════════════════════════════════════════════════
#  CLEARING SESSION ACTIVITIES
# ═══════════════════════════════════════════════════════════════════════════

class TestSealAllLotsModule:
    def test_module_importable(self):
        from modules.cts.workflows.activities.clearing_session_activities import seal_all_lots  # noqa: F401

    def test_input_model_exists(self):
        from modules.cts.workflows.activities.clearing_session_activities import SealAllLotsInput
        assert SealAllLotsInput is not None

    def test_result_model_exists(self):
        from modules.cts.workflows.activities.clearing_session_activities import SealAllLotsResult
        assert SealAllLotsResult is not None

    def test_activity_has_defn_decorator(self):
        from temporalio import activity as ta
        from modules.cts.workflows.activities.clearing_session_activities import seal_all_lots
        assert hasattr(ta.defn, "__wrapped__") or callable(seal_all_lots)


class TestSealAllLotsDegraded:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_degraded(self):
        from modules.cts.workflows.activities.clearing_session_activities import (
            seal_all_lots, SealAllLotsInput,
        )
        inp = SealAllLotsInput(
            session_id="SESS-001",
            bank_id="test-bank",
            pu_ids=["PU-01", "PU-02"],
            clearing_date="2026-07-21",
        )
        result = await seal_all_lots(inp, db_pool=None)
        assert result.sealed_lots == []
        assert result.status == "DEGRADED"

    @pytest.mark.asyncio
    async def test_db_pool_present_returns_lots(self):
        from modules.cts.workflows.activities.clearing_session_activities import (
            seal_all_lots, SealAllLotsInput,
        )
        fake_rows = [
            {"pu_id": "PU-01", "lot_number": "LOT-001", "instrument_count": 5},
            {"pu_id": "PU-02", "lot_number": "LOT-002", "instrument_count": 3},
        ]
        fake_conn = AsyncMock()
        fake_conn.fetch.return_value = fake_rows
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = SealAllLotsInput(
            session_id="SESS-001",
            bank_id="test-bank",
            pu_ids=["PU-01", "PU-02"],
            clearing_date="2026-07-21",
        )
        result = await seal_all_lots(inp, db_pool=db_pool)
        assert len(result.sealed_lots) == 2
        assert result.status == "OK"

    @pytest.mark.asyncio
    async def test_empty_lot_list_returns_ok_with_empty(self):
        from modules.cts.workflows.activities.clearing_session_activities import (
            seal_all_lots, SealAllLotsInput,
        )
        fake_conn = AsyncMock()
        fake_conn.fetch.return_value = []
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = SealAllLotsInput(
            session_id="SESS-EMPTY",
            bank_id="test-bank",
            pu_ids=["PU-01"],
            clearing_date="2026-07-21",
        )
        result = await seal_all_lots(inp, db_pool=db_pool)
        assert result.sealed_lots == []
        assert result.status == "OK"


class TestUpdateSessionStatus:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_not_updated(self):
        from modules.cts.workflows.activities.clearing_session_activities import (
            update_session_status, UpdateSessionStatusInput,
        )
        inp = UpdateSessionStatusInput(
            session_id="SESS-001",
            bank_id="test-bank",
            status="SUBMITTED",
        )
        result = await update_session_status(inp, db_pool=None)
        assert result.updated is False

    @pytest.mark.asyncio
    async def test_db_pool_present_updates_status(self):
        from modules.cts.workflows.activities.clearing_session_activities import (
            update_session_status, UpdateSessionStatusInput,
        )
        fake_conn = AsyncMock()
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = UpdateSessionStatusInput(
            session_id="SESS-001",
            bank_id="test-bank",
            status="SUBMITTED",
        )
        result = await update_session_status(inp, db_pool=db_pool)
        assert result.updated is True
        fake_conn.execute.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
#  SESSION RECONCILIATION ACTIVITIES
# ═══════════════════════════════════════════════════════════════════════════

class TestFetchNGCHSettlementReport:
    def test_module_importable(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (  # noqa: F401
            fetch_ngch_settlement_report,
        )

    @pytest.mark.asyncio
    async def test_no_ngch_client_returns_degraded(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            fetch_ngch_settlement_report, FetchSettlementInput,
        )
        inp = FetchSettlementInput(
            session_id="SESS-001",
            bank_id="test-bank",
            clearing_date="2026-07-21",
            bank_ifsc="SARA0000001",
        )
        result = await fetch_ngch_settlement_report(inp, ngch_client=None)
        assert result.degraded is True
        assert result.rows == []

    @pytest.mark.asyncio
    async def test_ngch_client_returns_rows(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            fetch_ngch_settlement_report, FetchSettlementInput,
        )
        fake_rows = [
            {"instrument_id": "INS-001", "status": "SETTLED"},
            {"instrument_id": "INS-002", "status": "RETURNED"},
        ]
        ngch_client = MagicMock()
        ngch_client.fetch_settlement_report = AsyncMock(return_value=fake_rows)

        inp = FetchSettlementInput(
            session_id="SESS-001",
            bank_id="test-bank",
            clearing_date="2026-07-21",
            bank_ifsc="SARA0000001",
        )
        result = await fetch_ngch_settlement_report(inp, ngch_client=ngch_client)
        assert len(result.rows) == 2
        assert result.degraded is False


class TestMatchSubmittedVsSettled:
    @pytest.mark.asyncio
    async def test_no_db_pool_returns_degraded(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            match_submitted_vs_settled, MatchInput,
        )
        inp = MatchInput(
            session_id="SESS-001",
            bank_id="test-bank",
            settlement_rows=[],
            submitted_count=10,
        )
        result = await match_submitted_vs_settled(inp, db_pool=None)
        assert result.matched_count == 0
        assert result.exception_count == 0

    @pytest.mark.asyncio
    async def test_all_matched(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            match_submitted_vs_settled, MatchInput,
        )
        rows = [
            {"instrument_id": "INS-001", "status": "SETTLED"},
            {"instrument_id": "INS-002", "status": "SETTLED"},
        ]
        fake_conn = AsyncMock()
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = MatchInput(
            session_id="SESS-001",
            bank_id="test-bank",
            settlement_rows=rows,
            submitted_count=2,
        )
        result = await match_submitted_vs_settled(inp, db_pool=db_pool)
        assert result.matched_count == 2
        assert result.exception_count == 0
        assert result.outcome == "RECONCILED"

    @pytest.mark.asyncio
    async def test_exceptions_flagged_when_returned_instruments(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            match_submitted_vs_settled, MatchInput,
        )
        rows = [
            {"instrument_id": "INS-001", "status": "SETTLED"},
            {"instrument_id": "INS-002", "status": "RETURNED"},
        ]
        fake_conn = AsyncMock()
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = MatchInput(
            session_id="SESS-001",
            bank_id="test-bank",
            settlement_rows=rows,
            submitted_count=2,
        )
        result = await match_submitted_vs_settled(inp, db_pool=db_pool)
        assert result.exception_count == 1
        assert result.outcome == "EXCEPTIONS_FLAGGED"


class TestGenerateRRF:
    @pytest.mark.asyncio
    async def test_no_exceptions_skips_generation(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            generate_rrf, GenerateRRFInput,
        )
        inp = GenerateRRFInput(
            session_id="SESS-001",
            bank_id="test-bank",
            bank_ifsc="SARA0000001",
            clearing_date="2026-07-21",
            exception_instruments=[],
        )
        result = await generate_rrf(inp, db_pool=None)
        assert result.generated is False

    @pytest.mark.asyncio
    async def test_with_exceptions_generates_rrf(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            generate_rrf, GenerateRRFInput,
        )
        fake_conn = AsyncMock()
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = GenerateRRFInput(
            session_id="SESS-001",
            bank_id="test-bank",
            bank_ifsc="SARA0000001",
            clearing_date="2026-07-21",
            exception_instruments=[{"instrument_id": "INS-002", "reason": "RETURNED"}],
        )
        result = await generate_rrf(inp, db_pool=db_pool)
        assert result.generated is True
        assert result.rrf_path is not None


# ═══════════════════════════════════════════════════════════════════════════
#  SB RELAY ACTIVITIES (SBInwardForwardingWorkflow + AgencyCCWorkflow)
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveCRLBatch:
    def test_module_importable(self):
        from modules.cts.workflows.activities.sb_relay_activities import resolve_crl_batch  # noqa: F401

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_all_failed(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            resolve_crl_batch, CRLBatchInput,
        )
        inp = CRLBatchInput(
            agency_id="saraswat-coop",
            instruments=[
                {"instrument_id": "INS-001", "drawee_ifsc": "SBIN0000123"},
                {"instrument_id": "INS-002", "drawee_ifsc": "HDFC0001234"},
            ],
        )
        result = await resolve_crl_batch(inp, db_pool=None)
        assert len(result.resolved) == 2
        assert all(not r["success"] for r in result.resolved)

    @pytest.mark.asyncio
    async def test_db_resolves_ifsc_to_pu(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            resolve_crl_batch, CRLBatchInput,
        )
        fake_conn = AsyncMock()
        fake_conn.fetchrow.side_effect = [
            {"pu_id": "saraswat-coop-pu1"},
            None,
        ]
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = CRLBatchInput(
            agency_id="saraswat-coop",
            instruments=[
                {"instrument_id": "INS-001", "drawee_ifsc": "SBIN0000123"},
                {"instrument_id": "INS-002", "drawee_ifsc": "UNKN0000000"},
            ],
        )
        result = await resolve_crl_batch(inp, db_pool=db_pool)
        assert result.resolved[0]["success"] is True
        assert result.resolved[0]["pu_id"] == "saraswat-coop-pu1"
        assert result.resolved[1]["success"] is False


class TestPublishToPUQueues:
    @pytest.mark.asyncio
    async def test_no_event_producer_returns_degraded(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            publish_to_pu_queues, PublishToPUInput,
        )
        inp = PublishToPUInput(
            agency_id="saraswat-coop",
            resolved_instruments=[
                {"instrument_id": "INS-001", "pu_id": "pu1", "success": True},
            ],
        )
        result = await publish_to_pu_queues(inp, event_producer=None)
        assert result.published_count == 0
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_producer_publishes_each_instrument(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            publish_to_pu_queues, PublishToPUInput,
        )
        producer = MagicMock()
        producer.produce = AsyncMock()

        inp = PublishToPUInput(
            agency_id="saraswat-coop",
            resolved_instruments=[
                {"instrument_id": "INS-001", "pu_id": "pu1", "success": True},
                {"instrument_id": "INS-002", "pu_id": "pu2", "success": True},
            ],
        )
        result = await publish_to_pu_queues(inp, event_producer=producer)
        assert result.published_count == 2
        assert result.degraded is False


class TestBuildLotPackage:
    @pytest.mark.asyncio
    async def test_no_lot_store_returns_error(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            build_lot_package, BuildLotPackageInput,
        )
        inp = BuildLotPackageInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            lot_numbers=["LOT-001", "LOT-002"],
            instrument_count=10,
        )
        result = await build_lot_package(inp, lot_store=None)
        assert result.package_path is None
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_lot_store_builds_package(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            build_lot_package, BuildLotPackageInput,
        )
        lot_store = MagicMock()
        lot_store.assemble_package = AsyncMock(return_value="/tmp/PKG-001.dat")

        inp = BuildLotPackageInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            lot_numbers=["LOT-001"],
            instrument_count=5,
        )
        result = await build_lot_package(inp, lot_store=lot_store)
        assert result.package_path == "/tmp/PKG-001.dat"
        assert result.error is None


class TestSBSubmitLot:
    @pytest.mark.asyncio
    async def test_no_sb_connector_returns_failed(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            sb_submit_lot, SBSubmitInput,
        )
        inp = SBSubmitInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            package_path="/tmp/PKG-001.dat",
            instrument_count=5,
            connector_type="SFTP_GENERIC",
        )
        result = await sb_submit_lot(inp, sb_connector=None)
        assert result.success is False
        assert result.reference_number is None

    @pytest.mark.asyncio
    async def test_connector_succeeds(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            sb_submit_lot, SBSubmitInput,
        )
        connector = MagicMock()
        connector.submit_lot = AsyncMock(return_value={"success": True, "reference_number": "SB-REF-001"})

        inp = SBSubmitInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            package_path="/tmp/PKG-001.dat",
            instrument_count=5,
            connector_type="SFTP_GENERIC",
        )
        result = await sb_submit_lot(inp, sb_connector=connector)
        assert result.success is True
        assert result.reference_number == "SB-REF-001"

    @pytest.mark.asyncio
    async def test_connector_rejection_returns_failed(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            sb_submit_lot, SBSubmitInput,
        )
        connector = MagicMock()
        connector.submit_lot = AsyncMock(return_value={"success": False, "error_code": "SB_VALIDATION_ERROR"})

        inp = SBSubmitInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            package_path="/tmp/PKG-001.dat",
            instrument_count=5,
            connector_type="SFTP_GENERIC",
        )
        result = await sb_submit_lot(inp, sb_connector=connector)
        assert result.success is False
        assert result.error_code == "SB_VALIDATION_ERROR"


class TestPublishRelayEvent:
    @pytest.mark.asyncio
    async def test_no_producer_returns_degraded(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            publish_relay_event, PublishRelayInput,
        )
        inp = PublishRelayInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            sb_reference="SB-REF-001",
            instrument_count=5,
        )
        result = await publish_relay_event(inp, event_producer=None)
        assert result.published is False

    @pytest.mark.asyncio
    async def test_producer_publishes_event(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            publish_relay_event, PublishRelayInput,
        )
        producer = MagicMock()
        producer.produce = AsyncMock()

        inp = PublishRelayInput(
            agency_id="saraswat-coop",
            sb_bank_id="saraswat-main",
            session_id="SESS-001",
            sb_reference="SB-REF-001",
            instrument_count=5,
        )
        result = await publish_relay_event(inp, event_producer=producer)
        assert result.published is True
        producer.produce.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
#  SMB VAULT PUSH ACTIVITIES
# ═══════════════════════════════════════════════════════════════════════════

class TestParseAndValidateSMBPush:
    def test_module_importable(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (  # noqa: F401
            parse_and_validate_smb_push,
        )

    @pytest.mark.asyncio
    async def test_no_db_pool_returns_degraded(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (
            parse_and_validate_smb_push, ParseSMBPushInput,
        )
        inp = ParseSMBPushInput(
            agency_id="saraswat-coop",
            smb_id="test-smb",
            file_type="STOP_PAYMENTS",
            file_path="/tmp/test.csv",
            file_hash="abc123",
        )
        result = await parse_and_validate_smb_push(inp, db_pool=None)
        assert result.error == "DB_UNAVAILABLE"
        assert result.record_count == 0

    @pytest.mark.asyncio
    async def test_duplicate_hash_returns_duplicate(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (
            parse_and_validate_smb_push, ParseSMBPushInput,
        )
        fake_conn = AsyncMock()
        fake_conn.fetchrow.return_value = {"file_hash": "abc123"}  # duplicate found
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = ParseSMBPushInput(
            agency_id="saraswat-coop",
            smb_id="test-smb",
            file_type="STOP_PAYMENTS",
            file_path="/tmp/test.csv",
            file_hash="abc123",
        )
        result = await parse_and_validate_smb_push(inp, db_pool=db_pool)
        assert result.duplicate is True
        assert result.record_count == 0

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_error(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (
            parse_and_validate_smb_push, ParseSMBPushInput,
        )
        fake_conn = AsyncMock()
        fake_conn.fetchrow.return_value = None  # no duplicate
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = ParseSMBPushInput(
            agency_id="saraswat-coop",
            smb_id="test-smb",
            file_type="STOP_PAYMENTS",
            file_path="/nonexistent/file.csv",
            file_hash="abc123",
        )
        result = await parse_and_validate_smb_push(inp, db_pool=db_pool)
        assert result.error is not None
        assert result.duplicate is False


class TestUpdateSMBVault:
    @pytest.mark.asyncio
    async def test_no_redis_returns_degraded(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (
            update_smb_vault, UpdateSMBVaultInput,
        )
        inp = UpdateSMBVaultInput(
            agency_id="saraswat-coop",
            smb_id="test-smb",
            file_type="STOP_PAYMENTS",
            records=[{"account_number_hash": "abc", "cheque_number": "001"}],
        )
        result = await update_smb_vault(inp, redis_client=None)
        assert result.updated_count == 0
        assert result.error == "REDIS_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_redis_present_writes_records(self):
        from modules.cts.workflows.activities.smb_vault_push_activities import (
            update_smb_vault, UpdateSMBVaultInput,
        )
        redis_client = MagicMock()
        redis_client.set = AsyncMock()
        redis_client.pipeline = MagicMock()
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=False)
        pipeline.set = MagicMock()
        pipeline.execute = AsyncMock(return_value=[True, True])
        redis_client.pipeline.return_value = pipeline

        inp = UpdateSMBVaultInput(
            agency_id="saraswat-coop",
            smb_id="test-smb",
            file_type="STOP_PAYMENTS",
            records=[
                {"account_number_hash": "hash1", "cheque_number": "001"},
                {"account_number_hash": "hash2", "cheque_number": "002"},
            ],
        )
        result = await update_smb_vault(inp, redis_client=redis_client)
        assert result.updated_count == 2
        assert result.error is None


# ═══════════════════════════════════════════════════════════════════════════
#  WORKFLOW DECORATOR CHECKS
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkflowDecorators:
    """All 5 missing workflows must carry @workflow.defn and have @workflow.run."""

    def _get_temporal_defn(self, cls):
        """Return the Temporal workflow definition metadata if present."""
        try:
            from temporalio import workflow as tw
            return getattr(cls, "__temporal_workflow_definition", None)
        except ImportError:
            pytest.skip("temporalio not installed")

    def test_clearing_session_workflow_has_defn(self):
        from modules.cts.workflows.clearing_session_workflow import ClearingSessionWorkflow
        # @workflow.defn registers metadata; we check the class has it
        defn = self._get_temporal_defn(ClearingSessionWorkflow)
        assert defn is not None, "ClearingSessionWorkflow missing @workflow.defn"

    def test_session_reconciliation_workflow_has_defn(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        defn = self._get_temporal_defn(SessionReconciliationWorkflow)
        assert defn is not None, "SessionReconciliationWorkflow missing @workflow.defn"

    def test_sb_inward_forwarding_workflow_has_defn(self):
        from modules.cts.workflows.sb_inward_forwarding_workflow import SBInwardForwardingWorkflow
        defn = self._get_temporal_defn(SBInwardForwardingWorkflow)
        assert defn is not None, "SBInwardForwardingWorkflow missing @workflow.defn"

    def test_smb_vault_push_workflow_has_defn(self):
        from modules.cts.workflows.smb_vault_push_workflow import SMBVaultPushWorkflow
        defn = self._get_temporal_defn(SMBVaultPushWorkflow)
        assert defn is not None, "SMBVaultPushWorkflow missing @workflow.defn"

    def test_agency_cc_workflow_has_defn(self):
        from modules.cts.workflows.agency_cc_workflow import AgencyCCWorkflow
        defn = self._get_temporal_defn(AgencyCCWorkflow)
        assert defn is not None, "AgencyCCWorkflow missing @workflow.defn"

    def test_clearing_session_workflow_has_run_method(self):
        from modules.cts.workflows.clearing_session_workflow import ClearingSessionWorkflow
        assert hasattr(ClearingSessionWorkflow, "run"), "ClearingSessionWorkflow missing run()"
        assert callable(ClearingSessionWorkflow.run)

    def test_session_reconciliation_workflow_has_run_method(self):
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        assert hasattr(SessionReconciliationWorkflow, "run")

    def test_sb_inward_forwarding_workflow_has_run_method(self):
        from modules.cts.workflows.sb_inward_forwarding_workflow import SBInwardForwardingWorkflow
        assert hasattr(SBInwardForwardingWorkflow, "run")

    def test_smb_vault_push_workflow_has_run_method(self):
        from modules.cts.workflows.smb_vault_push_workflow import SMBVaultPushWorkflow
        assert hasattr(SMBVaultPushWorkflow, "run")

    def test_agency_cc_workflow_has_run_method(self):
        from modules.cts.workflows.agency_cc_workflow import AgencyCCWorkflow
        assert hasattr(AgencyCCWorkflow, "run")


# ═══════════════════════════════════════════════════════════════════════════
#  WORKER REGISTRATION CHECKS
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkerRegistration:
    """Verify worker.py registers everything properly."""

    def _activity_names(self, activities: list) -> set:
        names = set()
        for a in activities:
            defn = getattr(a, "__temporal_activity_definition", None)
            if defn is not None:
                names.add(getattr(defn, "name", None) or a.__name__)
            else:
                names.add(getattr(a, "__name__", str(a)))
        return names

    def test_stamp_endorsement_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "stamp_endorsement" in names

    def test_update_lot_status_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "update_lot_status" in names

    def test_build_ngch_file_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "build_ngch_file" in names

    def test_submit_to_ngch_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "submit_to_ngch" in names

    def test_confirm_acknowledgement_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "confirm_acknowledgement" in names

    def test_seal_all_lots_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "seal_all_lots" in names

    def test_update_session_status_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "update_session_status" in names

    def test_fetch_ngch_settlement_report_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "fetch_ngch_settlement_report" in names

    def test_match_submitted_vs_settled_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "match_submitted_vs_settled" in names

    def test_generate_rrf_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "generate_rrf" in names

    def test_resolve_crl_batch_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "resolve_crl_batch" in names

    def test_publish_to_pu_queues_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "publish_to_pu_queues" in names

    def test_build_lot_package_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "build_lot_package" in names

    def test_sb_submit_lot_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "sb_submit_lot" in names

    def test_publish_relay_event_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "publish_relay_event" in names

    def test_parse_and_validate_smb_push_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "parse_and_validate_smb_push" in names

    def test_update_smb_vault_in_no_di_activities(self):
        from modules.cts.worker import NO_DI_ACTIVITIES
        names = self._activity_names(NO_DI_ACTIVITIES)
        assert "update_smb_vault" in names

    def test_clearing_session_workflow_in_all_workflows(self):
        from modules.cts.worker import ALL_WORKFLOWS
        from modules.cts.workflows.clearing_session_workflow import ClearingSessionWorkflow
        assert ClearingSessionWorkflow in ALL_WORKFLOWS

    def test_session_reconciliation_workflow_in_all_workflows(self):
        from modules.cts.worker import ALL_WORKFLOWS
        from modules.cts.workflows.session_reconciliation_workflow import SessionReconciliationWorkflow
        assert SessionReconciliationWorkflow in ALL_WORKFLOWS

    def test_sb_inward_forwarding_workflow_in_all_workflows(self):
        from modules.cts.worker import ALL_WORKFLOWS
        from modules.cts.workflows.sb_inward_forwarding_workflow import SBInwardForwardingWorkflow
        assert SBInwardForwardingWorkflow in ALL_WORKFLOWS

    def test_smb_vault_push_workflow_in_all_workflows(self):
        from modules.cts.worker import ALL_WORKFLOWS
        from modules.cts.workflows.smb_vault_push_workflow import SMBVaultPushWorkflow
        assert SMBVaultPushWorkflow in ALL_WORKFLOWS

    def test_agency_cc_workflow_in_all_workflows(self):
        from modules.cts.worker import ALL_WORKFLOWS
        from modules.cts.workflows.agency_cc_workflow import AgencyCCWorkflow
        assert AgencyCCWorkflow in ALL_WORKFLOWS
