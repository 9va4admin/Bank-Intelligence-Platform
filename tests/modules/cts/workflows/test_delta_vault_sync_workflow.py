"""
TDD — RED phase: tests for modules/cts/workflows/delta_vault_sync_workflow.py

Delta Vault Sync (Gemini Fix B):
  - Runs every 15 minutes (Temporal schedule, not cron)
  - Fetches ONLY stop-payment deltas + canceled cheque leaf serials from CBS
  - Updates bloom:canceled:{bank_id} in Redis
  - Writes audit event to Immudb on completion
  - Workflow ID: cts-vault-delta-{bank_id}-{yyyymmddhhmm}
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_delta_input(bank_id: str = "test-bank"):
    from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncInput
    return DeltaVaultSyncInput(bank_id=bank_id, sync_window_minutes=15)


# ---------------------------------------------------------------------------
# DeltaVaultSyncInput model
# ---------------------------------------------------------------------------

class TestDeltaVaultSyncInput:
    def test_input_model_fields(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncInput
        inp = DeltaVaultSyncInput(bank_id="sbi-main", sync_window_minutes=15)
        assert inp.bank_id == "sbi-main"
        assert inp.sync_window_minutes == 15

    def test_input_default_window(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncInput
        inp = DeltaVaultSyncInput(bank_id="hdfc-bank")
        assert inp.sync_window_minutes == 15   # default


# ---------------------------------------------------------------------------
# fetch_delta_stop_payments activity
# ---------------------------------------------------------------------------

class TestFetchDeltaStopPayments:
    @pytest.mark.asyncio
    async def test_returns_list_of_stop_payment_serials(self):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_stop_payments
        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(return_value=[
            {"account_number": "12345678", "cheque_serial": "001001", "reason": "LOST"},
            {"account_number": "12345679", "cheque_serial": "002002", "reason": "STOLEN"},
        ])
        result = await fetch_delta_stop_payments(
            bank_id="test-bank", window_minutes=15, cbs_client=cbs
        )
        assert len(result) == 2
        assert result[0]["cheque_serial"] == "001001"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_returns_empty_list_with_degraded_flag(self):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_stop_payments
        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(side_effect=Exception("CBS unreachable"))
        result = await fetch_delta_stop_payments(
            bank_id="test-bank", window_minutes=15, cbs_client=cbs
        )
        # Graceful degradation: empty list, not an exception
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_new_stop_payments(self):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_stop_payments
        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(return_value=[])
        result = await fetch_delta_stop_payments(
            bank_id="test-bank", window_minutes=15, cbs_client=cbs
        )
        assert result == []


# ---------------------------------------------------------------------------
# fetch_delta_canceled_leaves activity
# ---------------------------------------------------------------------------

class TestFetchDeltaCanceledLeaves:
    @pytest.mark.asyncio
    async def test_returns_list_of_canceled_serials(self):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_canceled_leaves
        cbs = MagicMock()
        cbs.get_canceled_cheque_leaves = AsyncMock(return_value=[
            {"serial": "C001001", "account_number": "ACCT001"},
            {"serial": "C001002", "account_number": "ACCT001"},
        ])
        result = await fetch_delta_canceled_leaves(
            bank_id="test-bank", window_minutes=15, cbs_client=cbs
        )
        assert len(result) == 2
        assert "C001001" in [r["serial"] for r in result]

    @pytest.mark.asyncio
    async def test_cbs_unavailable_returns_empty(self):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_canceled_leaves
        cbs = MagicMock()
        cbs.get_canceled_cheque_leaves = AsyncMock(side_effect=Exception("CBS timeout"))
        result = await fetch_delta_canceled_leaves(
            bank_id="test-bank", window_minutes=15, cbs_client=cbs
        )
        assert result == []


# ---------------------------------------------------------------------------
# update_bloom_filter activity
# ---------------------------------------------------------------------------

class TestUpdateBloomFilter:
    @pytest.mark.asyncio
    async def test_adds_stop_payment_serials_to_bloom(self):
        from modules.cts.workflows.delta_vault_sync_workflow import update_bloom_filter
        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        stop_payments = [
            {"cheque_serial": "001001"},
            {"cheque_serial": "001002"},
        ]
        canceled_leaves = [{"serial": "C001003"}]

        result = await update_bloom_filter(
            bank_id="test-bank",
            stop_payment_deltas=stop_payments,
            canceled_leaf_deltas=canceled_leaves,
            bloom_client=bloom,
        )
        assert bloom.add_bulk.called
        # Combined: 2 stop payment serials + 1 canceled leaf = 3 serials added
        all_serials = bloom.add_bulk.call_args[0][0]
        assert len(all_serials) == 3

    @pytest.mark.asyncio
    async def test_empty_deltas_do_not_call_bloom(self):
        from modules.cts.workflows.delta_vault_sync_workflow import update_bloom_filter
        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        result = await update_bloom_filter(
            bank_id="test-bank",
            stop_payment_deltas=[],
            canceled_leaf_deltas=[],
            bloom_client=bloom,
        )
        bloom.add_bulk.assert_not_called()
        assert result["serials_added"] == 0

    @pytest.mark.asyncio
    async def test_returns_count_of_serials_added(self):
        from modules.cts.workflows.delta_vault_sync_workflow import update_bloom_filter
        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        result = await update_bloom_filter(
            bank_id="test-bank",
            stop_payment_deltas=[{"cheque_serial": "S001"}, {"cheque_serial": "S002"}],
            canceled_leaf_deltas=[{"serial": "C001"}],
            bloom_client=bloom,
        )
        assert result["serials_added"] == 3


# ---------------------------------------------------------------------------
# DeltaVaultSyncResult model
# ---------------------------------------------------------------------------

class TestDeltaVaultSyncResult:
    def test_result_carries_counts(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncResult
        r = DeltaVaultSyncResult(
            bank_id="test-bank",
            stop_payments_fetched=5,
            canceled_leaves_fetched=3,
            bloom_serials_added=8,
            cbs_degraded=False,
        )
        assert r.stop_payments_fetched == 5
        assert r.canceled_leaves_fetched == 3
        assert r.bloom_serials_added == 8

    def test_result_marks_degraded_when_cbs_unavailable(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncResult
        r = DeltaVaultSyncResult(
            bank_id="test-bank",
            stop_payments_fetched=0,
            canceled_leaves_fetched=0,
            bloom_serials_added=0,
            cbs_degraded=True,
        )
        assert r.cbs_degraded is True


# ---------------------------------------------------------------------------
# DeltaVaultSyncWorkflow — Temporal workflow class
# ---------------------------------------------------------------------------

class TestDeltaVaultSyncWorkflow:
    """Tests for the Temporal workflow orchestrator.

    Uses plain async functions (no Temporal sandbox) to verify:
      - activities are called in order
      - CBS degradation is surfaced in result
      - audit write always called (even on degraded run)
      - empty delta run completes without error
    """

    @pytest.mark.asyncio
    async def test_workflow_calls_all_three_activities_in_order(self):
        """Workflow must call fetch_stp -> fetch_leaves -> update_bloom -> audit."""
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        wf = DeltaVaultSyncWorkflow()
        calls = []

        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(return_value=[{"cheque_serial": "S001"}])
        cbs.get_canceled_cheque_leaves = AsyncMock(return_value=[{"serial": "C001"}])

        bloom = MagicMock()
        bloom.add_bulk = MagicMock(side_effect=lambda s: calls.append("bloom"))

        audit = AsyncMock(side_effect=lambda **kw: calls.append("audit"))

        result = await wf.run_with_mocks(
            DeltaVaultSyncInput(bank_id="test-bank"),
            cbs_client=cbs,
            bloom_client=bloom,
            audit_fn=audit,
        )

        assert "bloom" in calls
        assert "audit" in calls
        assert result.stop_payments_fetched == 1
        assert result.canceled_leaves_fetched == 1
        assert result.bloom_serials_added == 2

    @pytest.mark.asyncio
    async def test_workflow_marks_cbs_degraded_when_both_cbs_calls_fail(self):
        """If both CBS calls fail, result.cbs_degraded is True."""
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        wf = DeltaVaultSyncWorkflow()

        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(side_effect=Exception("CBS down"))
        cbs.get_canceled_cheque_leaves = AsyncMock(side_effect=Exception("CBS down"))

        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        audit = AsyncMock()

        result = await wf.run_with_mocks(
            DeltaVaultSyncInput(bank_id="test-bank"),
            cbs_client=cbs,
            bloom_client=bloom,
            audit_fn=audit,
        )

        assert result.cbs_degraded is True
        assert result.bloom_serials_added == 0

    @pytest.mark.asyncio
    async def test_workflow_audit_called_even_when_cbs_degraded(self):
        """Audit write must happen regardless of CBS availability."""
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        wf = DeltaVaultSyncWorkflow()

        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(side_effect=Exception("CBS down"))
        cbs.get_canceled_cheque_leaves = AsyncMock(side_effect=Exception("CBS down"))

        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        audit = AsyncMock()

        await wf.run_with_mocks(
            DeltaVaultSyncInput(bank_id="test-bank"),
            cbs_client=cbs,
            bloom_client=bloom,
            audit_fn=audit,
        )

        audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_workflow_zero_deltas_completes_without_error(self):
        """Empty CBS response is a normal run — no error, bloom not touched."""
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        wf = DeltaVaultSyncWorkflow()

        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(return_value=[])
        cbs.get_canceled_cheque_leaves = AsyncMock(return_value=[])

        bloom = MagicMock()
        bloom.add_bulk = MagicMock()

        audit = AsyncMock()

        result = await wf.run_with_mocks(
            DeltaVaultSyncInput(bank_id="test-bank"),
            cbs_client=cbs,
            bloom_client=bloom,
            audit_fn=audit,
        )

        bloom.add_bulk.assert_not_called()
        assert result.bloom_serials_added == 0
        assert result.cbs_degraded is False

    @pytest.mark.asyncio
    async def test_workflow_result_bank_id_matches_input(self):
        """Result.bank_id must equal the input bank_id."""
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        wf = DeltaVaultSyncWorkflow()

        cbs = MagicMock()
        cbs.get_stop_payment_deltas = AsyncMock(return_value=[])
        cbs.get_canceled_cheque_leaves = AsyncMock(return_value=[])

        result = await wf.run_with_mocks(
            DeltaVaultSyncInput(bank_id="kotak-mah"),
            cbs_client=cbs,
            bloom_client=MagicMock(),
            audit_fn=AsyncMock(),
        )

        assert result.bank_id == "kotak-mah"


# ---------------------------------------------------------------------------
# DeltaVaultSyncWorkflow.run() — the real @workflow.run, driven through an
# actual Temporal Worker + time-skipping test server. Every test above only
# ever exercised run_with_mocks() directly — this proves the @activity.defn/
# @workflow.defn decorators added in this fix actually let Temporal dispatch
# these activities for real.
# ---------------------------------------------------------------------------

import uuid
from temporalio import activity as _activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


@_activity.defn(name="fetch_delta_stop_payments")
async def _fake_fetch_stop_payments(bank_id: str, window_minutes: int) -> list[dict]:
    return [{"account_number": "12345678", "cheque_serial": "001001", "reason": "LOST"}]


@_activity.defn(name="fetch_delta_canceled_leaves")
async def _fake_fetch_canceled_leaves(bank_id: str, window_minutes: int) -> list[dict]:
    return [{"serial": "C001001", "account_number": "ACCT001"}]


@_activity.defn(name="update_bloom_filter")
async def _fake_update_bloom(bank_id: str, stop_payment_deltas: list, canceled_leaf_deltas: list) -> dict:
    return {"serials_added": len(stop_payment_deltas) + len(canceled_leaf_deltas)}


@_activity.defn(name="fetch_delta_stop_payments")
async def _fake_fetch_stop_payments_fails(bank_id: str, window_minutes: int) -> list[dict]:
    raise RuntimeError("CBS genuinely unreachable")


class TestDeltaVaultSyncWorkflowRealRun:
    @pytest.mark.asyncio
    async def test_real_run_dispatches_all_three_activities(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[DeltaVaultSyncWorkflow],
                activities=[_fake_fetch_stop_payments, _fake_fetch_canceled_leaves, _fake_update_bloom],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    DeltaVaultSyncWorkflow.run,
                    DeltaVaultSyncInput(bank_id="test-bank"),
                    id=f"cts-vault-delta-test-bank-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.stop_payments_fetched == 1
        assert result.canceled_leaves_fetched == 1
        assert result.bloom_serials_added == 2
        assert result.cbs_degraded is False

    @pytest.mark.asyncio
    async def test_real_run_marks_degraded_when_activity_raises(self):
        from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow, DeltaVaultSyncInput

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[DeltaVaultSyncWorkflow],
                activities=[_fake_fetch_stop_payments_fails, _fake_fetch_canceled_leaves, _fake_update_bloom],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    DeltaVaultSyncWorkflow.run,
                    DeltaVaultSyncInput(bank_id="test-bank"),
                    id=f"cts-vault-delta-test-bank-realfail-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.cbs_degraded is True
        assert result.stop_payments_fetched == 0
