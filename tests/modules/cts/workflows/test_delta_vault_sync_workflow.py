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
