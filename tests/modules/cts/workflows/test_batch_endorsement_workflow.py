"""
Tests for modules/cts/workflows/batch_endorsement_workflow.py

BatchEndorsementWorkflow — stamps all instruments in a sealed lot.
Activities: stamp_endorsement → update_lot_status → write_audit

Terminal states: ENDORSED | ENDORSEMENT_FAILED
"""
import pytest
from unittest.mock import MagicMock


def _make_input(**kwargs):
    from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementInput
    defaults = dict(
        lot_number="LOT_SVCB0000001_20240619_SES01_01",
        bank_id="test-bank",
        bank_ifsc="SVCB0000001",
        session_id="SES01",
        instrument_ids=["OUT-001", "OUT-002", "OUT-003"],
    )
    defaults.update(kwargs)
    return BatchEndorsementInput(**defaults)


def _make_mocks(endorsed_count=3, failed_count=0):
    records = [MagicMock(instrument_id=f"OUT-{i:03d}", endorsed=True) for i in range(1, endorsed_count + 1)]
    failed = [MagicMock(instrument_id=f"OUT-F{i:03d}", endorsed=False, reason="STAMP_ERROR") for i in range(1, failed_count + 1)]
    return {
        "endorsement": MagicMock(records=records + failed, failed_count=failed_count),
        "lot_status": MagicMock(outcome="ENDORSED"),
        "audit": MagicMock(audit_event_id="AUD-001"),
    }


class TestBatchEndorsementInput:
    def test_input_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.lot_number = "changed"

    def test_workflow_id_format(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        wid = wf.workflow_id("test-bank", "LOT_SVCB_20240619_S01_01")
        assert "test-bank" in wid
        assert "LOT_SVCB_20240619_S01_01" in wid

    def test_workflow_id_deterministic(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        assert wf.workflow_id("bank-a", "LOT-1") == wf.workflow_id("bank-a", "LOT-1")


class TestBatchEndorsementResult:
    def test_result_is_frozen(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementResult
        r = BatchEndorsementResult(
            outcome="ENDORSED", lot_number="LOT_1", bank_id="b",
            endorsed_count=3, failed_count=0, audit_written=True,
        )
        with pytest.raises(Exception):
            r.outcome = "changed"


class TestBatchEndorsementHappyPath:
    @pytest.mark.asyncio
    async def test_endorsed_when_all_succeed(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(endorsed_count=3))
        assert result.outcome == "ENDORSED"

    @pytest.mark.asyncio
    async def test_endorsed_count_in_result(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        result = await wf.run_with_mocks(_make_input(instrument_ids=["A", "B"]), mock_results=_make_mocks(endorsed_count=2))
        assert result.endorsed_count == 2

    @pytest.mark.asyncio
    async def test_audit_written_on_endorsed(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks())
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_lot_number_in_result(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        result = await wf.run_with_mocks(
            _make_input(lot_number="LOT_SVCB_20240619_S01_99"),
            mock_results=_make_mocks(),
        )
        assert result.lot_number == "LOT_SVCB_20240619_S01_99"

    @pytest.mark.asyncio
    async def test_zero_failed_on_clean_batch(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_mocks(endorsed_count=3, failed_count=0))
        assert result.failed_count == 0


class TestBatchEndorsementTemporalDecorators:
    def test_workflow_defn_decorator(self):
        """@workflow.defn must be present for Temporal worker registration."""
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        assert hasattr(BatchEndorsementWorkflow, "__temporal_workflow_definition")

    def test_run_method_exists(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        assert callable(getattr(BatchEndorsementWorkflow, "run", None))


class TestBatchEndorsementWriteAuditEvents:
    def test_endorsed_event_type_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_OUT_ENDORSED" in _VALID_EVENT_TYPES

    def test_endorsement_failed_event_type_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_OUT_ENDORSEMENT_FAILED" in _VALID_EVENT_TYPES


class TestBatchEndorsementActivities:
    @pytest.mark.asyncio
    async def test_stamp_endorsement_no_lot_store(self):
        from modules.cts.workflows.activities.batch_endorsement_activities import (
            StampEndorsementInput,
            stamp_endorsement,
        )
        inp = StampEndorsementInput(
            lot_number="LOT-001",
            bank_id="srcb",
            bank_ifsc="SRCB0000001",
            instrument_ids=["INS-001", "INS-002"],
        )
        result = await stamp_endorsement(inp, lot_store=None)
        assert result.endorsed_count == 0
        assert result.failed_count == 2

    @pytest.mark.asyncio
    async def test_update_lot_status_no_db(self):
        from modules.cts.workflows.activities.batch_endorsement_activities import (
            UpdateLotStatusInput,
            update_lot_status,
        )
        inp = UpdateLotStatusInput(
            lot_number="LOT-001",
            bank_id="srcb",
            outcome="ENDORSED",
            endorsed_count=3,
            failed_count=0,
        )
        result = await update_lot_status(inp, db_pool=None)
        assert result.updated is False
        assert result.outcome == "ENDORSED"

    @pytest.mark.asyncio
    async def test_update_lot_status_with_db(self):
        from unittest.mock import AsyncMock, MagicMock
        from modules.cts.workflows.activities.batch_endorsement_activities import (
            UpdateLotStatusInput,
            update_lot_status,
        )
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        inp = UpdateLotStatusInput(
            lot_number="LOT-001",
            bank_id="srcb",
            outcome="ENDORSED",
            endorsed_count=3,
            failed_count=0,
        )
        result = await update_lot_status(inp, db_pool=mock_pool)
        assert result.updated is True
        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args[0]
        assert "srcb" in call_args


class TestBatchEndorsementFailedPath:
    @pytest.mark.asyncio
    async def test_endorsement_failed_when_stamp_fails(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        mock = _make_mocks(endorsed_count=0, failed_count=3)
        mock["endorsement"] = MagicMock(records=[], failed_count=3)
        mock["lot_status"] = MagicMock(outcome="ENDORSEMENT_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.outcome == "ENDORSEMENT_FAILED"

    @pytest.mark.asyncio
    async def test_audit_written_on_failure(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        mock = _make_mocks()
        mock["lot_status"] = MagicMock(outcome="ENDORSEMENT_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_failed_count_propagated(self):
        from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
        wf = BatchEndorsementWorkflow()
        mock = _make_mocks(endorsed_count=1, failed_count=2)
        mock["lot_status"] = MagicMock(outcome="ENDORSEMENT_FAILED")
        mock["endorsement"] = MagicMock(records=[], failed_count=2)
        result = await wf.run_with_mocks(_make_input(), mock_results=mock)
        assert result.failed_count == 2
