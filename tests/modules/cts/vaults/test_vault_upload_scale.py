"""
Scale tests — 1,000,000 row vault CSV processing.

PPS vault is used throughout (simplest schema, 5 RBI-mandated fields).
We use a lightweight counting stub instead of AsyncMock for the 1M call
path to avoid storing 1M call_args records in memory.
"""
from __future__ import annotations

import io
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor


# ---------------------------------------------------------------------------
# CSV generator
# ---------------------------------------------------------------------------

def _make_pps_csv(n_rows: int, *, fail_every: int = 0) -> bytes:
    """
    Generate a PPS CSV with n_rows data rows.
    If fail_every > 0, every fail_every-th data row (1-indexed) gets
    amount="NOT_A_NUMBER" → the processor will fail that row.
    """
    buf = io.StringIO()
    buf.write("account_number,cheque_number,cheque_date,amount,payee_name,action\n")
    cheque_date = date.today().isoformat()
    for i in range(1, n_rows + 1):
        amount = "NOT_A_NUMBER" if (fail_every and i % fail_every == 0) else f"{i * 10}.00"
        buf.write(f"{i},{i:06d},{cheque_date},{amount},P{i},UPSERT\n")
    return buf.getvalue().encode("utf-8")


def _lightweight_pps_vault() -> tuple[object, list]:
    """
    Returns (vault_stub, calls_counter) where calls_counter[0] increments
    on every store_pps invocation — no call_args storage overhead.
    """
    counter = [0]

    async def _store_pps(**kwargs):
        counter[0] += 1

    stub = MagicMock()
    stub.store_pps = _store_pps
    return stub, counter


# ---------------------------------------------------------------------------
# 1,000,000-row tests
# ---------------------------------------------------------------------------

class TestVaultUploadScale:
    """All tests use 1,000,000-row PPS CSVs unless noted."""

    @pytest.mark.asyncio
    async def test_1m_all_valid_rows_processed_exact(self):
        """Every row is valid → rows_processed == 1,000,000, rows_failed == 0."""
        csv = _make_pps_csv(1_000_000)
        vault, counter = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_total == 1_000_000
        assert result.rows_processed == 1_000_000
        assert result.rows_failed == 0
        assert result.errors == []
        assert counter[0] == 1_000_000, "store_pps must be called exactly once per row"

    @pytest.mark.asyncio
    async def test_1m_10pct_failures_exact_counts(self):
        """
        Every 10th row has amount=NOT_A_NUMBER.
        1,000,000 / 10 = exactly 100,000 failures.
        """
        csv = _make_pps_csv(1_000_000, fail_every=10)
        vault, counter = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_total == 1_000_000
        assert result.rows_failed == 100_000
        assert result.rows_processed == 900_000
        assert counter[0] == 900_000

    @pytest.mark.asyncio
    async def test_1m_1pct_failures_exact_counts(self):
        """Every 100th row fails → 10,000 failures."""
        csv = _make_pps_csv(1_000_000, fail_every=100)
        vault, counter = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_total == 1_000_000
        assert result.rows_failed == 10_000
        assert result.rows_processed == 990_000

    @pytest.mark.asyncio
    async def test_1m_all_invalid_rows_zero_processed(self):
        """Every row fails → rows_processed == 0, rows_failed == 1,000,000."""
        csv = _make_pps_csv(1_000_000, fail_every=1)
        vault, counter = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_total == 1_000_000
        assert result.rows_processed == 0
        assert result.rows_failed == 1_000_000
        assert counter[0] == 0

    @pytest.mark.asyncio
    async def test_1m_completes_within_120_seconds(self):
        """Performance guard: 1M rows must complete in < 120 seconds."""
        csv = _make_pps_csv(1_000_000)
        vault, _ = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        t0 = time.perf_counter()
        result = await proc.process("PPS", csv, "user:nilesh")
        elapsed = time.perf_counter() - t0

        assert result.rows_processed == 1_000_000
        assert elapsed < 120.0, (
            f"1M-row processing took {elapsed:.2f}s — exceeds 120s budget. "
            "Streaming CSV instead of list() may be needed for production."
        )

    @pytest.mark.asyncio
    async def test_error_row_numbers_accurate_at_scale(self):
        """
        Use 50 rows with every 10th failing.
        Verify the exact CSV row numbers in errors[].
        CSV row 1 = header; data row i → CSV row i+1.
        Failing data rows: 10, 20, 30, 40, 50 → CSV rows 11, 21, 31, 41, 51.
        """
        csv = _make_pps_csv(50, fail_every=10)
        vault, _ = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        failed_row_numbers = {e["row"] for e in result.errors}
        assert failed_row_numbers == {11, 21, 31, 41, 51}
        assert result.rows_failed == 5
        assert result.rows_processed == 45

    @pytest.mark.asyncio
    async def test_error_list_capped_at_50_in_db_but_all_in_result(self):
        """
        errors[] in VaultUploadResult has ALL failures.
        The DB column errors_json caps at 50 (line 473 in vault_upload_processor.py:
        `json.dumps(result.errors[:50])` — only first 50 written to DB).
        This test proves the in-memory result has all errors (production gap documented).
        """
        csv = _make_pps_csv(200, fail_every=2)   # 100 failures
        vault, _ = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_failed == 100
        assert len(result.errors) == 100          # all 100 in memory result
        # DB would only store first 50 — this is the gap the test exposes

    @pytest.mark.asyncio
    async def test_error_messages_contain_rejection_reason(self):
        """
        Every error dict has both "row" (int) and "error" (str describing why).
        Non-numeric amount should include the bad value in the message.
        """
        csv = _make_pps_csv(5, fail_every=3)  # rows 3 fails
        vault, _ = _lightweight_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_failed == 1
        err = result.errors[0]
        assert isinstance(err["row"], int)
        assert isinstance(err["error"], str)
        assert "amount" in err["error"].lower()
        assert "NOT_A_NUMBER" in err["error"]

    @pytest.mark.asyncio
    async def test_bank_id_isolation_at_1m_scale(self):
        """Two 500K-row batches for different banks are independently isolated."""
        csv_a = _make_pps_csv(500_000)
        csv_b = _make_pps_csv(500_000)

        vault_a, counter_a = _lightweight_pps_vault()
        vault_b, counter_b = _lightweight_pps_vault()

        proc_a = VaultUploadProcessor("bank-alpha", db_pool=None, pps_vault=vault_a)
        proc_b = VaultUploadProcessor("bank-beta", db_pool=None, pps_vault=vault_b)

        result_a = await proc_a.process("PPS", csv_a, "user:nilesh")
        result_b = await proc_b.process("PPS", csv_b, "user:nilesh")

        assert result_a.rows_processed == 500_000
        assert result_b.rows_processed == 500_000
        assert counter_a[0] == 500_000
        assert counter_b[0] == 500_000
        # Batch IDs are independent UUIDs
        assert result_a.batch_id != result_b.batch_id

    @pytest.mark.asyncio
    async def test_vault_exception_at_row_500k_does_not_abort_rest(self):
        """
        Vault raises on exactly one row (row 500,000).
        Processing continues; all other 999,999 rows succeed.
        """
        target_row = 500_000
        call_num = [0]

        async def _sometimes_raise(**kwargs):
            call_num[0] += 1
            if call_num[0] == target_row:
                raise RuntimeError(f"Redis timeout at row {target_row}")

        vault = MagicMock()
        vault.store_pps = _sometimes_raise

        csv = _make_pps_csv(1_000_000)
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)

        result = await proc.process("PPS", csv, "user:nilesh")

        assert result.rows_total == 1_000_000
        assert result.rows_failed == 1
        assert result.rows_processed == 999_999
        assert any("Redis timeout" in e["error"] for e in result.errors)
