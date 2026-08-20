"""
Tests for SBInwardForwardingWorkflow and sb_relay_activities.

Covers:
  SBInwardForwardingWorkflow.run_with_mocks — all routing outcomes
  resolve_crl_batch activity — happy path, DB unavailable, IFSC not found
  publish_to_pu_queues activity — happy path, producer unavailable
  build_lot_package activity — happy path, lot_store unavailable
  sb_submit_lot activity — happy path, connector unavailable, SB rejection
  publish_relay_event activity — happy path, producer unavailable
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


AGENCY_ID  = "saraswat-coop"
SB_BANK_ID = "federal-bank"
SESSION_ID = "sess-20260820-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inp(instruments=None):
    from modules.cts.workflows.sb_inward_forwarding_workflow import SBInwardForwardingInput
    return SBInwardForwardingInput(
        agency_id=AGENCY_ID,
        sb_bank_id=SB_BANK_ID,
        session_id=SESSION_ID,
        instruments=instruments or [],
    )


def _instrument(id_="INS001", ifsc="SRCB0000001"):
    return {"instrument_id": id_, "drawee_ifsc": ifsc, "original_ngch_ts": 1724150400.0}


def _crl_ok(id_="INS001", pu_id="SRCB0000001"):
    return {"instrument_id": id_, "pu_id": pu_id, "success": True}


def _crl_fail(id_="INS001", ifsc="SRCB0000001"):
    return {"instrument_id": id_, "success": False, "error": f"NO_CRL_ENTRY:{ifsc}"}


def _wf():
    from modules.cts.workflows.sb_inward_forwarding_workflow import SBInwardForwardingWorkflow
    return SBInwardForwardingWorkflow()


# ---------------------------------------------------------------------------
# SBInwardForwardingWorkflow routing
# ---------------------------------------------------------------------------

class TestSBInwardForwardingWorkflowRouting:

    @pytest.mark.asyncio
    async def test_empty_instruments_returns_empty(self):
        result = await _wf().run_with_mocks(_inp([]), {"crl_lookups": [], "audit": {}})
        assert result.outcome == "EMPTY"
        assert result.routed_count == 0
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_empty_instruments_writes_audit(self):
        result = await _wf().run_with_mocks(_inp([]), {"crl_lookups": [], "audit": {}})
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_all_success_returns_routed(self):
        instruments = [_instrument("I1"), _instrument("I2")]
        crl = [_crl_ok("I1"), _crl_ok("I2")]
        result = await _wf().run_with_mocks(_inp(instruments), {"crl_lookups": crl, "audit": {}})
        assert result.outcome == "ROUTED"
        assert result.routed_count == 2
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_partial_failure_returns_partial_failure(self):
        instruments = [_instrument("I1"), _instrument("I2")]
        crl = [_crl_ok("I1"), _crl_fail("I2")]
        result = await _wf().run_with_mocks(_inp(instruments), {"crl_lookups": crl, "audit": {}})
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.routed_count == 1
        assert result.failed_count == 1

    @pytest.mark.asyncio
    async def test_all_failed_returns_failed(self):
        instruments = [_instrument("I1"), _instrument("I2")]
        crl = [_crl_fail("I1"), _crl_fail("I2")]
        result = await _wf().run_with_mocks(_inp(instruments), {"crl_lookups": crl, "audit": {}})
        assert result.outcome == "FAILED"
        assert result.routed_count == 0
        assert result.failed_count == 2

    @pytest.mark.asyncio
    async def test_single_instrument_all_routed(self):
        instruments = [_instrument("I1")]
        result = await _wf().run_with_mocks(
            _inp(instruments),
            {"crl_lookups": [_crl_ok("I1")], "audit": {}},
        )
        assert result.outcome == "ROUTED"
        assert result.routed_count == 1

    @pytest.mark.asyncio
    async def test_agency_id_propagated_to_result(self):
        result = await _wf().run_with_mocks(
            _inp([_instrument()]),
            {"crl_lookups": [_crl_ok()], "audit": {}},
        )
        assert result.agency_id == AGENCY_ID

    @pytest.mark.asyncio
    async def test_session_id_propagated_to_result(self):
        result = await _wf().run_with_mocks(
            _inp([_instrument()]),
            {"crl_lookups": [_crl_ok()], "audit": {}},
        )
        assert result.session_id == SESSION_ID

    @pytest.mark.asyncio
    async def test_audit_written_on_routed(self):
        result = await _wf().run_with_mocks(
            _inp([_instrument()]),
            {"crl_lookups": [_crl_ok()], "audit": {}},
        )
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_counts_correct_on_mixed_batch(self):
        instruments = [_instrument(f"I{i}") for i in range(5)]
        crl = [_crl_ok(f"I{i}") if i < 3 else _crl_fail(f"I{i}") for i in range(5)]
        result = await _wf().run_with_mocks(_inp(instruments), {"crl_lookups": crl, "audit": {}})
        assert result.routed_count == 3
        assert result.failed_count == 2
        assert result.outcome == "PARTIAL_FAILURE"

    def test_workflow_id_format(self):
        wf = _wf()
        wf_id = wf.workflow_id(AGENCY_ID, SB_BANK_ID, SESSION_ID)
        assert wf_id == f"cts-sbinward-{AGENCY_ID}-{SB_BANK_ID}-{SESSION_ID}"


# ---------------------------------------------------------------------------
# resolve_crl_batch activity
# ---------------------------------------------------------------------------

class TestResolveCRLBatch:

    @pytest.mark.asyncio
    async def test_db_unavailable_marks_all_failed(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            CRLBatchInput, resolve_crl_batch,
        )
        inp = CRLBatchInput(
            agency_id=AGENCY_ID,
            instruments=[_instrument("I1"), _instrument("I2")],
        )
        result = await resolve_crl_batch(inp, db_pool=None)
        assert all(not r["success"] for r in result.resolved)
        assert all(r["error"] == "DB_UNAVAILABLE" for r in result.resolved)
        assert len(result.resolved) == 2

    @pytest.mark.asyncio
    async def test_db_unavailable_preserves_instrument_ids(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            CRLBatchInput, resolve_crl_batch,
        )
        inp = CRLBatchInput(
            agency_id=AGENCY_ID,
            instruments=[_instrument("INS-AAA"), _instrument("INS-BBB")],
        )
        result = await resolve_crl_batch(inp, db_pool=None)
        ids = {r["instrument_id"] for r in result.resolved}
        assert ids == {"INS-AAA", "INS-BBB"}

    @pytest.mark.asyncio
    async def test_happy_path_resolves_pu_id(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            CRLBatchInput, resolve_crl_batch,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"pu_id": "SRCB0000001"})
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        inp = CRLBatchInput(
            agency_id=AGENCY_ID,
            instruments=[_instrument("I1", "SRCB0000001")],
        )
        result = await resolve_crl_batch(inp, db_pool=mock_pool)
        assert result.resolved[0]["success"] is True
        assert result.resolved[0]["pu_id"] == "SRCB0000001"

    @pytest.mark.asyncio
    async def test_ifsc_not_in_registry_marks_failed(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            CRLBatchInput, resolve_crl_batch,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)   # no row
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        inp = CRLBatchInput(
            agency_id=AGENCY_ID,
            instruments=[_instrument("I1", "UNKN0000001")],
        )
        result = await resolve_crl_batch(inp, db_pool=mock_pool)
        assert result.resolved[0]["success"] is False
        assert "NO_CRL_ENTRY" in result.resolved[0]["error"]


# ---------------------------------------------------------------------------
# publish_to_pu_queues activity
# ---------------------------------------------------------------------------

class TestPublishToPUQueues:

    @pytest.mark.asyncio
    async def test_producer_none_returns_degraded(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            PublishToPUInput, publish_to_pu_queues,
        )
        inp = PublishToPUInput(
            agency_id=AGENCY_ID,
            resolved_instruments=[_crl_ok("I1")],
        )
        result = await publish_to_pu_queues(inp, event_producer=None)
        assert result.degraded is True
        assert result.published_count == 0

    @pytest.mark.asyncio
    async def test_publishes_to_correct_pu_topic(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            PublishToPUInput, publish_to_pu_queues,
        )
        mock_producer = AsyncMock()
        mock_producer.produce = AsyncMock()
        inp = PublishToPUInput(
            agency_id=AGENCY_ID,
            resolved_instruments=[{"instrument_id": "I1", "pu_id": "SRCB0000001", "success": True}],
        )
        result = await publish_to_pu_queues(inp, event_producer=mock_producer)
        assert result.published_count == 1
        assert result.degraded is False
        mock_producer.produce.assert_called_once()
        topic_called = mock_producer.produce.call_args.args[0]
        assert topic_called == "cts.inward.SRCB0000001"

    @pytest.mark.asyncio
    async def test_skips_failed_instruments(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            PublishToPUInput, publish_to_pu_queues,
        )
        mock_producer = AsyncMock()
        mock_producer.produce = AsyncMock()
        inp = PublishToPUInput(
            agency_id=AGENCY_ID,
            resolved_instruments=[
                {"instrument_id": "I1", "pu_id": "SRCB0000001", "success": True},
                {"instrument_id": "I2", "success": False, "error": "NO_CRL_ENTRY"},
            ],
        )
        result = await publish_to_pu_queues(inp, event_producer=mock_producer)
        assert result.published_count == 1   # only the successful one


# ---------------------------------------------------------------------------
# build_lot_package activity
# ---------------------------------------------------------------------------

class TestBuildLotPackage:

    @pytest.mark.asyncio
    async def test_lot_store_unavailable_returns_error(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            BuildLotPackageInput, build_lot_package,
        )
        inp = BuildLotPackageInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            lot_numbers=["LOT-001"], instrument_count=10,
        )
        result = await build_lot_package(inp, lot_store=None)
        assert result.error == "LOT_STORE_UNAVAILABLE"
        assert result.package_path is None

    @pytest.mark.asyncio
    async def test_happy_path_returns_package_path(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            BuildLotPackageInput, build_lot_package,
        )
        mock_store = AsyncMock()
        mock_store.assemble_package = AsyncMock(return_value="/tmp/pkg-001.zip")
        inp = BuildLotPackageInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            lot_numbers=["LOT-001", "LOT-002"], instrument_count=20,
        )
        result = await build_lot_package(inp, lot_store=mock_store)
        assert result.error is None
        assert result.package_path == "/tmp/pkg-001.zip"


# ---------------------------------------------------------------------------
# sb_submit_lot activity
# ---------------------------------------------------------------------------

class TestSBSubmitLot:

    @pytest.mark.asyncio
    async def test_connector_unavailable_returns_error(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            SBSubmitInput, sb_submit_lot,
        )
        inp = SBSubmitInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            package_path="/pkg.zip", instrument_count=5,
            connector_type="SFTP_GENERIC",
        )
        result = await sb_submit_lot(inp, sb_connector=None)
        assert result.success is False
        assert result.error_code == "CONNECTOR_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_happy_path_returns_reference_number(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            SBSubmitInput, sb_submit_lot,
        )
        mock_connector = AsyncMock()
        mock_connector.submit_lot = AsyncMock(
            return_value={"success": True, "reference_number": "SB-REF-001"}
        )
        inp = SBSubmitInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            package_path="/pkg.zip", instrument_count=5,
            connector_type="SFTP_GENERIC",
        )
        result = await sb_submit_lot(inp, sb_connector=mock_connector)
        assert result.success is True
        assert result.reference_number == "SB-REF-001"

    @pytest.mark.asyncio
    async def test_sb_rejection_returns_error_code(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            SBSubmitInput, sb_submit_lot,
        )
        mock_connector = AsyncMock()
        mock_connector.submit_lot = AsyncMock(
            return_value={"success": False, "error_code": "DUPLICATE_SESSION"}
        )
        inp = SBSubmitInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            package_path="/pkg.zip", instrument_count=5,
            connector_type="BANCS_API",
        )
        result = await sb_submit_lot(inp, sb_connector=mock_connector)
        assert result.success is False
        assert result.error_code == "DUPLICATE_SESSION"


# ---------------------------------------------------------------------------
# publish_relay_event activity
# ---------------------------------------------------------------------------

class TestPublishRelayEvent:

    @pytest.mark.asyncio
    async def test_producer_unavailable_does_not_crash(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            PublishRelayInput, publish_relay_event,
        )
        inp = PublishRelayInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            sb_reference="SB-REF-001", instrument_count=5,
        )
        result = await publish_relay_event(inp, event_producer=None)
        assert result.published is False
        assert result.topic is not None

    @pytest.mark.asyncio
    async def test_happy_path_publishes_to_relay_topic(self):
        from modules.cts.workflows.activities.sb_relay_activities import (
            PublishRelayInput, publish_relay_event,
        )
        mock_producer = AsyncMock()
        mock_producer.produce = AsyncMock()
        inp = PublishRelayInput(
            agency_id=AGENCY_ID, sb_bank_id=SB_BANK_ID, session_id=SESSION_ID,
            sb_reference="SB-REF-001", instrument_count=5,
        )
        result = await publish_relay_event(inp, event_producer=mock_producer)
        assert result.published is True
        mock_producer.produce.assert_called_once()
        topic_called = mock_producer.produce.call_args.args[0]
        assert AGENCY_ID in topic_called
        assert SB_BANK_ID in topic_called
