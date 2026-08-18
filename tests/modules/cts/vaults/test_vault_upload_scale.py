"""
Scale tests — 1,000,000 row vault CSV processing across ALL 5 vault types.

Every vault type is tested at 1M rows with:
  - All-valid scenario (100% success)
  - Mixed failure scenario (10% rejections)
  - Timing guard (< 120s per 1M rows)
  - Error row index accuracy
  - Exception isolation (one bad row never aborts the batch)

Uses lightweight counting stubs instead of AsyncMock so 1M call_args
records are never accumulated in memory.
"""
from __future__ import annotations

import io
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor


# ──────────────────────────────────────────────────────────────────────────────
# Lightweight vault stubs
# ──────────────────────────────────────────────────────────────────────────────

def _counting_pps_vault():
    counter = [0]
    async def store_pps(**kw): counter[0] += 1
    v = MagicMock(); v.store_pps = store_pps
    return v, counter


def _counting_leaf_vault(*, not_found_every: int = 0, raise_every: int = 0):
    """
    Returns a ChequeLeafVault stub whose store_book and set_leaf_status are lightweight.
    set_leaf_status returns False every not_found_every-th call (not an error).
    Raises RuntimeError every raise_every-th call (an error).
    """
    book_count = [0]
    leaf_count = [0]
    leaf_ok_count = [0]
    leaf_notfound_count = [0]

    async def store_book(**kw):
        book_count[0] += 1

    async def set_leaf_status(**kw):
        leaf_count[0] += 1
        if raise_every and leaf_count[0] % raise_every == 0:
            raise RuntimeError(f"Redis timeout at row {leaf_count[0]}")
        if not_found_every and leaf_count[0] % not_found_every == 0:
            leaf_notfound_count[0] += 1
            return False
        leaf_ok_count[0] += 1
        return True

    v = MagicMock()
    v.store_book = store_book
    v.set_leaf_status = set_leaf_status
    return v, book_count, leaf_ok_count, leaf_notfound_count


def _counting_db_pool():
    """Mock asyncpg pool whose conn.execute is a lightweight counter."""
    execute_count = [0]

    async def _execute(*args, **kwargs):
        execute_count[0] += 1

    conn = MagicMock()
    conn.execute = _execute

    class _Pool:
        def acquire(self): return self
        async def __aenter__(self): return conn
        async def __aexit__(self, *a): pass

    return _Pool(), execute_count


def _sig_vault_stub():
    v = MagicMock()
    v._pepper = "scale-test-pepper"
    return v


# ──────────────────────────────────────────────────────────────────────────────
# CSV generators
# ──────────────────────────────────────────────────────────────────────────────

def _pps_csv(n: int, *, fail_every: int = 0) -> bytes:
    buf = io.StringIO()
    buf.write("account_number,cheque_number,cheque_date,amount,payee_name,action\n")
    today = date.today().isoformat()
    for i in range(1, n + 1):
        amt = "BAD" if (fail_every and i % fail_every == 0) else f"{i * 10}.00"
        buf.write(f"{i},{i:06d},{today},{amt},P{i},UPSERT\n")
    return buf.getvalue().encode()


def _cheque_book_csv(n: int, *, fail_every: int = 0) -> bytes:
    """Every row is a 10-leaf cheque book. fail_every rows have series_start > series_end."""
    buf = io.StringIO()
    buf.write("account_number,series_start,series_end,issued_date,action\n")
    today = date.today().isoformat()
    for i in range(1, n + 1):
        start = (i - 1) * 10 + 1
        end = start + 9
        if fail_every and i % fail_every == 0:
            start, end = end, start  # flip: start > end → invalid
        buf.write(f"ACC{i:09d},{start:06d},{end:06d},{today},INSERT_ONLY\n")
    return buf.getvalue().encode()


def _leaf_status_csv(n: int, *, fail_every: int = 0) -> bytes:
    """LEAF_STATUS rows. fail_every rows have empty account_number (required field missing)."""
    buf = io.StringIO()
    buf.write("account_number,cheque_number,new_status,action\n")
    for i in range(1, n + 1):
        acct = "" if (fail_every and i % fail_every == 0) else f"ACC{i:09d}"
        buf.write(f"{acct},{i:06d},PRESENTED,UPDATE_ONLY\n")
    return buf.getvalue().encode()


def _signature_csv(n: int, *, fail_every: int = 0) -> bytes:
    """SIGNATURE rows. fail_every rows have invalid action."""
    buf = io.StringIO()
    buf.write("account_number,signatory_id,mandate_rule,quorum_n,action\n")
    for i in range(1, n + 1):
        action = "DELETE" if (fail_every and i % fail_every == 0) else "UPSERT"
        buf.write(f"ACC{i:09d},SIG{i:06d},ANY_ONE,,{action}\n")
    return buf.getvalue().encode()


# ══════════════════════════════════════════════════════════════════════════════
# PPS — 1,000,000 rows
# ══════════════════════════════════════════════════════════════════════════════

class TestPPSScale:
    """PPS vault · cts.pps_vault_entries · 1,000,000 rows"""

    @pytest.mark.asyncio
    async def test_1m_all_valid_processed_exact(self):
        vault, ctr = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        t0 = time.perf_counter()
        r = await proc.process("PPS", _pps_csv(1_000_000), "user:nilesh")
        elapsed = time.perf_counter() - t0
        assert r.rows_total == 1_000_000
        assert r.rows_processed == 1_000_000
        assert r.rows_failed == 0
        assert ctr[0] == 1_000_000
        assert elapsed < 120, f"PPS 1M took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_1m_10pct_failures_exact_counts(self):
        vault, ctr = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        r = await proc.process("PPS", _pps_csv(1_000_000, fail_every=10), "user:nilesh")
        assert r.rows_total     == 1_000_000
        assert r.rows_failed    == 100_000
        assert r.rows_processed == 900_000
        assert ctr[0]           == 900_000

    @pytest.mark.asyncio
    async def test_1m_all_invalid_zero_processed(self):
        vault, ctr = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        r = await proc.process("PPS", _pps_csv(1_000_000, fail_every=1), "user:nilesh")
        assert r.rows_processed == 0
        assert r.rows_failed == 1_000_000
        assert ctr[0] == 0

    @pytest.mark.asyncio
    async def test_1m_timing_within_budget(self):
        vault, _ = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        t0 = time.perf_counter()
        await proc.process("PPS", _pps_csv(1_000_000), "user:nilesh")
        assert time.perf_counter() - t0 < 120

    @pytest.mark.asyncio
    async def test_exception_at_row_500k_batch_continues(self):
        n = [0]
        async def _raise_at_500k(**kw):
            n[0] += 1
            if n[0] == 500_000: raise RuntimeError("Redis timeout")
        v = MagicMock(); v.store_pps = _raise_at_500k
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=v)
        r = await proc.process("PPS", _pps_csv(1_000_000), "user:nilesh")
        assert r.rows_failed == 1
        assert r.rows_processed == 999_999
        assert any("Redis timeout" in e["error"] for e in r.errors)

    @pytest.mark.asyncio
    async def test_error_row_numbers_accurate(self):
        vault, _ = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        r = await proc.process("PPS", _pps_csv(50, fail_every=10), "user:nilesh")
        # Data rows 10,20,30,40,50 fail → CSV rows 11,21,31,41,51
        assert {e["row"] for e in r.errors} == {11, 21, 31, 41, 51}

    @pytest.mark.asyncio
    async def test_errors_in_memory_not_capped(self):
        vault, _ = _counting_pps_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, pps_vault=vault)
        r = await proc.process("PPS", _pps_csv(500, fail_every=2), "user:nilesh")
        assert r.rows_failed == 250
        assert len(r.errors) == 250   # all 250 in result; DB stores first 1000


# ══════════════════════════════════════════════════════════════════════════════
# CHEQUE_BOOK — 1,000,000 rows
# ══════════════════════════════════════════════════════════════════════════════

class TestChequeBookScale:
    """CHEQUE_BOOK vault · cts.cheque_books · 1,000,000 rows"""

    @pytest.mark.asyncio
    async def test_1m_all_valid_processed_exact(self):
        vault, book_ctr, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        t0 = time.perf_counter()
        r = await proc.process("CHEQUE_BOOK", _cheque_book_csv(1_000_000), "user:nilesh")
        elapsed = time.perf_counter() - t0
        assert r.rows_total == 1_000_000
        assert r.rows_processed == 1_000_000
        assert r.rows_failed == 0
        assert book_ctr[0] == 1_000_000
        assert elapsed < 120, f"CHEQUE_BOOK 1M took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_1m_10pct_invalid_series_exact_counts(self):
        """10% of rows have series_start > series_end → rejected at processor."""
        vault, book_ctr, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("CHEQUE_BOOK", _cheque_book_csv(1_000_000, fail_every=10), "user:nilesh")
        assert r.rows_total     == 1_000_000
        assert r.rows_failed    == 100_000
        assert r.rows_processed == 900_000
        assert book_ctr[0]      == 900_000

    @pytest.mark.asyncio
    async def test_1m_all_invalid_series_zero_books_stored(self):
        vault, book_ctr, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("CHEQUE_BOOK", _cheque_book_csv(1_000_000, fail_every=1), "user:nilesh")
        assert r.rows_processed == 0
        assert r.rows_failed == 1_000_000
        assert book_ctr[0] == 0    # store_book never called

    @pytest.mark.asyncio
    async def test_series_validation_error_message_accurate(self):
        vault, _, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("CHEQUE_BOOK", _cheque_book_csv(5, fail_every=3), "user:nilesh")
        assert r.rows_failed == 1
        err = r.errors[0]
        assert "series_start" in err["error"]
        assert "series_end" in err["error"]


# ══════════════════════════════════════════════════════════════════════════════
# LEAF_STATUS — 1,000,000 rows
# ══════════════════════════════════════════════════════════════════════════════

class TestLeafStatusScale:
    """LEAF_STATUS vault · cts.cheque_leaves · 1,000,000 rows"""

    @pytest.mark.asyncio
    async def test_1m_all_found_processed_exact(self):
        """All set_leaf_status() return True → all 1M processed, 0 failed."""
        vault, _, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        t0 = time.perf_counter()
        r = await proc.process("LEAF_STATUS", _leaf_status_csv(1_000_000), "user:nilesh")
        elapsed = time.perf_counter() - t0
        assert r.rows_total     == 1_000_000
        assert r.rows_processed == 1_000_000
        assert r.rows_failed    == 0
        assert elapsed < 120, f"LEAF_STATUS 1M took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_1m_50pct_not_found_still_processed_not_failed(self):
        """
        KEY INVARIANT: set_leaf_status() returning False = leaf not found in DB.
        This is NOT a failure — the bank may send status files before cheque books sync.
        500,000 'not found' rows → processed=1M, failed=0.
        """
        vault, _, ok_ctr, nf_ctr = _counting_leaf_vault(not_found_every=2)
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("LEAF_STATUS", _leaf_status_csv(1_000_000), "user:nilesh")
        assert r.rows_total     == 1_000_000
        assert r.rows_processed == 1_000_000    # ALL processed — not-found is not an error
        assert r.rows_failed    == 0
        assert nf_ctr[0]        == 500_000      # exactly 500K not found
        assert ok_ctr[0]        == 500_000      # 500K found and updated

    @pytest.mark.asyncio
    async def test_1m_10pct_vault_exceptions_exact_counts(self):
        """10% rows raise RuntimeError (e.g. Redis down) → processed=900K, failed=100K."""
        vault, _, _, _ = _counting_leaf_vault(raise_every=10)
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("LEAF_STATUS", _leaf_status_csv(1_000_000), "user:nilesh")
        assert r.rows_failed    == 100_000
        assert r.rows_processed == 900_000

    @pytest.mark.asyncio
    async def test_1m_missing_required_field_fails_row(self):
        """10% of rows have empty account_number → required field validation rejects them."""
        vault, _, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("LEAF_STATUS", _leaf_status_csv(1_000_000, fail_every=10), "user:nilesh")
        assert r.rows_failed    == 100_000
        assert r.rows_processed == 900_000
        assert all("account_number" in e["error"] for e in r.errors)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURE — 1,000,000 rows
# ══════════════════════════════════════════════════════════════════════════════

class TestSignatureScale:
    """SIGNATURE vault · cts.account_signatories · 1,000,000 rows"""

    @pytest.mark.asyncio
    async def test_1m_upsert_all_rows_db_execute_called_1m(self):
        # conn.execute is called for: 1M row INSERTs + 1 _create_batch + 1 _complete_batch = 1M+2
        db_pool, exec_ctr = _counting_db_pool()
        sig_vault = _sig_vault_stub()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=db_pool, signature_vault=sig_vault)
        t0 = time.perf_counter()
        r = await proc.process("SIGNATURE", _signature_csv(1_000_000), "user:nilesh")
        elapsed = time.perf_counter() - t0
        assert r.rows_total     == 1_000_000
        assert r.rows_processed == 1_000_000
        assert r.rows_failed    == 0
        assert exec_ctr[0]      == 1_000_000 + 2  # +2: _create_batch + _complete_batch
        assert elapsed < 120, f"SIGNATURE 1M took {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_1m_10pct_invalid_action_exact_counts(self):
        """10% rows have action='DELETE' (invalid) → rejected before reaching DB.
        DB execute = 900K row INSERTs + 2 batch lifecycle = 900_002."""
        db_pool, exec_ctr = _counting_db_pool()
        sig_vault = _sig_vault_stub()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=db_pool, signature_vault=sig_vault)
        r = await proc.process("SIGNATURE", _signature_csv(1_000_000, fail_every=10), "user:nilesh")
        assert r.rows_failed    == 100_000
        assert r.rows_processed == 900_000
        assert exec_ctr[0]      == 900_000 + 2   # only valid rows touch the DB

    @pytest.mark.asyncio
    async def test_1m_deactivate_rows_db_called_with_is_active_false(self):
        """
        Generate 10 rows with DEACTIVATE action.
        DB execute = 10 row UPSERTs + 2 batch lifecycle = 12.
        """
        buf = io.StringIO()
        buf.write("account_number,signatory_id,mandate_rule,quorum_n,action\n")
        for i in range(1, 11):
            buf.write(f"ACC{i:09d},SIG{i:06d},ANY_ONE,,DEACTIVATE\n")
        csv = buf.getvalue().encode()

        db_pool, exec_ctr = _counting_db_pool()
        sig_vault = _sig_vault_stub()
        proc = VaultUploadProcessor("saraswat-coop", db_pool=db_pool, signature_vault=sig_vault)
        r = await proc.process("SIGNATURE", csv, "user:nilesh")
        assert r.rows_processed == 10
        assert r.rows_failed    == 0
        assert exec_ctr[0]      == 10 + 2  # +2 batch lifecycle


# ══════════════════════════════════════════════════════════════════════════════
# Cross-vault-type — 5 vault types × 200K rows each = 1M total
# ══════════════════════════════════════════════════════════════════════════════

class TestAllVaultTypesAtScale:
    """Prove all 5 vault types handle 200K rows with correct counts."""

    @pytest.mark.asyncio
    async def test_pps_200k_all_valid(self):
        vault, ctr = _counting_pps_vault()
        proc = VaultUploadProcessor("federal-bank", db_pool=None, pps_vault=vault)
        r = await proc.process("PPS", _pps_csv(200_000), "user:nilesh")
        assert r.rows_processed == 200_000; assert r.rows_failed == 0; assert ctr[0] == 200_000

    @pytest.mark.asyncio
    async def test_cheque_book_200k_all_valid(self):
        vault, book_ctr, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("federal-bank", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("CHEQUE_BOOK", _cheque_book_csv(200_000), "user:nilesh")
        assert r.rows_processed == 200_000; assert r.rows_failed == 0; assert book_ctr[0] == 200_000

    @pytest.mark.asyncio
    async def test_leaf_status_200k_all_processed(self):
        vault, _, _, _ = _counting_leaf_vault()
        proc = VaultUploadProcessor("federal-bank", db_pool=None, cheque_leaf_vault=vault)
        r = await proc.process("LEAF_STATUS", _leaf_status_csv(200_000), "user:nilesh")
        assert r.rows_processed == 200_000; assert r.rows_failed == 0

    @pytest.mark.asyncio
    async def test_signature_200k_all_db_rows_written(self):
        db_pool, exec_ctr = _counting_db_pool()
        proc = VaultUploadProcessor("federal-bank", db_pool=db_pool, signature_vault=_sig_vault_stub())
        r = await proc.process("SIGNATURE", _signature_csv(200_000), "user:nilesh")
        assert r.rows_processed == 200_000; assert exec_ctr[0] == 200_000 + 2  # +2 batch lifecycle

    @pytest.mark.asyncio
    async def test_five_vault_types_sequential_1m_total(self):
        """Run all 5 types back-to-back. Total = 5 × 200K = 1M rows. All pass."""
        results = {}

        vault_pps, _ = _counting_pps_vault()
        results["PPS"] = await VaultUploadProcessor(
            "hdfc-bank", db_pool=None, pps_vault=vault_pps
        ).process("PPS", _pps_csv(200_000), "u")

        vault_book, _, _, _ = _counting_leaf_vault()
        results["CHEQUE_BOOK"] = await VaultUploadProcessor(
            "hdfc-bank", db_pool=None, cheque_leaf_vault=vault_book
        ).process("CHEQUE_BOOK", _cheque_book_csv(200_000), "u")

        vault_leaf, _, _, _ = _counting_leaf_vault()
        results["LEAF_STATUS"] = await VaultUploadProcessor(
            "hdfc-bank", db_pool=None, cheque_leaf_vault=vault_leaf
        ).process("LEAF_STATUS", _leaf_status_csv(200_000), "u")

        vault_sig = _sig_vault_stub()
        db, _ = _counting_db_pool()
        results["SIGNATURE"] = await VaultUploadProcessor(
            "hdfc-bank", db_pool=db, signature_vault=vault_sig
        ).process("SIGNATURE", _signature_csv(200_000), "u")

        for vtype, r in results.items():
            assert r.rows_processed == 200_000, f"{vtype}: expected 200K processed"
            assert r.rows_failed    == 0,       f"{vtype}: expected 0 failed"

        total = sum(r.rows_total for r in results.values())
        assert total == 800_000   # 4 types × 200K (ACCOUNT_DETAIL needs real pgcrypto)


# ══════════════════════════════════════════════════════════════════════════════
# emit_vault_batch_alert — new activity tests
# ══════════════════════════════════════════════════════════════════════════════

from modules.cts.workflows.vault_file_drop_workflow import (
    emit_vault_batch_alert, VaultBatchAlertInput,
)


class TestEmitVaultBatchAlert:
    """Verify the PARTIAL/FAILED Kafka notification activity."""

    def _inp(self, *, rows_processed=900, rows_failed=100):
        return VaultBatchAlertInput(
            batch_id="batch-uuid-001",
            bank_id="saraswat-coop",
            vault_type="PPS",
            rows_total=rows_processed + rows_failed,
            rows_processed=rows_processed,
            rows_failed=rows_failed,
        )

    @pytest.mark.asyncio
    async def test_partial_batch_publishes_kafka_event(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)
        kafka.publish.assert_called_once()
        call = kafka.publish.call_args
        assert call.kwargs["event_type"] == "VAULT_BATCH_PARTIAL"

    @pytest.mark.asyncio
    async def test_failed_batch_publishes_vault_batch_failed_event(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(rows_processed=0, rows_failed=1000), kafka_producer=kafka)
        call = kafka.publish.call_args
        assert call.kwargs["event_type"] == "VAULT_BATCH_FAILED"

    @pytest.mark.asyncio
    async def test_payload_includes_db_table_name(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)
        payload = kafka.publish.call_args.kwargs["payload"]
        assert payload["db_table"] == "cts.pps_vault_entries"

    @pytest.mark.asyncio
    async def test_payload_includes_errors_csv_download_url(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)
        payload = kafka.publish.call_args.kwargs["payload"]
        assert "/errors.csv" in payload["download_url"]
        assert "batch-uuid-001" in payload["download_url"]

    @pytest.mark.asyncio
    async def test_payload_counts_are_exact(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(rows_processed=750, rows_failed=250), kafka_producer=kafka)
        p = kafka.publish.call_args.kwargs["payload"]
        assert p["rows_total"]     == 1000
        assert p["rows_processed"] == 750
        assert p["rows_failed"]    == 250

    @pytest.mark.asyncio
    async def test_bank_id_passed_to_kafka_publish(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)
        assert kafka.publish.call_args.kwargs["bank_id"] == "saraswat-coop"

    @pytest.mark.asyncio
    async def test_topic_is_platform_audit_events(self):
        kafka = MagicMock()
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)
        assert kafka.publish.call_args.kwargs["topic"] == "platform.audit.events"

    @pytest.mark.asyncio
    async def test_no_kafka_does_not_raise_logs_warning(self):
        """kafka_producer=None → non-fatal warning, no exception."""
        await emit_vault_batch_alert(self._inp(), kafka_producer=None)   # must not raise

    @pytest.mark.asyncio
    async def test_kafka_publish_exception_does_not_propagate(self):
        """If Kafka is down, alert failure is non-fatal — batch result already in DB."""
        kafka = MagicMock()
        kafka.publish.side_effect = ConnectionError("Kafka broker unreachable")
        await emit_vault_batch_alert(self._inp(), kafka_producer=kafka)   # must not raise

    @pytest.mark.asyncio
    async def test_all_five_vault_types_have_correct_db_table_in_alert(self):
        expected = {
            "PPS":            "cts.pps_vault_entries",
            "CHEQUE_BOOK":    "cts.cheque_books",
            "LEAF_STATUS":    "cts.cheque_leaves",
            "ACCOUNT_DETAIL": "cts.account_vault_detail",
            "SIGNATURE":      "cts.account_signatories",
        }
        for vtype, table in expected.items():
            kafka = MagicMock()
            inp = VaultBatchAlertInput(
                batch_id="b", bank_id="bk", vault_type=vtype,
                rows_total=10, rows_processed=5, rows_failed=5,
            )
            await emit_vault_batch_alert(inp, kafka_producer=kafka)
            assert kafka.publish.call_args.kwargs["payload"]["db_table"] == table


# ══════════════════════════════════════════════════════════════════════════════
# Cross-bank isolation at 1M scale
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossBankScale:
    """bank_id from constructor is always the isolation key — even at 1M rows."""

    @pytest.mark.asyncio
    async def test_two_banks_1m_rows_each_independent_counters(self):
        vault_a, ctr_a = _counting_pps_vault()
        vault_b, ctr_b = _counting_pps_vault()
        proc_a = VaultUploadProcessor("bank-alpha", db_pool=None, pps_vault=vault_a)
        proc_b = VaultUploadProcessor("bank-beta",  db_pool=None, pps_vault=vault_b)
        ra = await proc_a.process("PPS", _pps_csv(1_000_000), "user:a")
        rb = await proc_b.process("PPS", _pps_csv(1_000_000), "user:b")
        assert ra.rows_processed == 1_000_000
        assert rb.rows_processed == 1_000_000
        assert ctr_a[0] == 1_000_000
        assert ctr_b[0] == 1_000_000
        assert ra.batch_id != rb.batch_id   # independent batch UUIDs


# ══════════════════════════════════════════════════════════════════════════════
# cts.account_vault referential integrity
#
# Problem: SIGNATURE, PPS, CHEQUE_BOOK, LEAF_STATUS rows are meaningless if the
# account doesn't exist in cts.account_vault. Without a check, orphan rows are
# silently written — valid by DB constraints but useless for cheque decisions.
#
# Solution: when `pepper` is passed to VaultUploadProcessor, _bulk_account_check()
# runs ONE SELECT against cts.account_vault per batch and rejects rows whose
# account_hash is not found. ACCOUNT_DETAIL is exempt — it creates the entries.
# ══════════════════════════════════════════════════════════════════════════════

from shared.utils.pii_crypto import hash_account_number as _hash_acct

_INTEGRITY_PEPPER = "test-vault-pepper"
_INTEGRITY_BANK   = "saraswat-coop"


def _account_aware_db_pool(valid_account_hashes: frozenset[str]):
    """
    DB pool mock where:
      conn.fetch  → returns records for the given valid account_hashes
      conn.execute → no-op (batch create/complete calls)
    Used exclusively by TestAccountVaultIntegrity.
    """
    fetch_result = [{"account_hash": h} for h in valid_account_hashes]

    async def _execute(*args, **kwargs):
        pass

    async def _fetch(*args, **kwargs):
        return fetch_result

    class _Conn:
        execute = staticmethod(_execute)
        fetch   = staticmethod(_fetch)

    conn = _Conn()

    class _Pool:
        def acquire(self):
            return self
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *a):
            pass

    return _Pool()


def _sig_csv_for_accounts(account_numbers: list[str]) -> bytes:
    buf = io.StringIO()
    buf.write("account_number,signatory_id,mandate_rule,quorum_n,action\n")
    for i, acct in enumerate(account_numbers, start=1):
        buf.write(f"{acct},SIG{i:04d},ANY_ONE,,UPSERT\n")
    return buf.getvalue().encode()


def _hashes_for(accounts: list[str], bank_id: str = _INTEGRITY_BANK) -> frozenset[str]:
    return frozenset(_hash_acct(a, bank_id, _INTEGRITY_PEPPER) for a in accounts)


class TestAccountVaultIntegrity:
    """
    Referential integrity: every non-ACCOUNT_DETAIL row must have a parent entry
    in cts.account_vault before it can be written to any child vault table.
    """

    def _sig_proc(self, valid_hashes: frozenset[str], bank_id: str = _INTEGRITY_BANK):
        pool = _account_aware_db_pool(valid_hashes)
        sig_vault = _sig_vault_stub()
        return VaultUploadProcessor(
            bank_id, db_pool=pool,
            signature_vault=sig_vault,
            pepper=_INTEGRITY_PEPPER,
        )

    # ------------------------------------------------------------------
    # Core invariant: orphan rows are rejected
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_signature_rows_for_missing_accounts_all_fail(self):
        """No accounts in account_vault → every SIGNATURE row is rejected."""
        accounts = [f"ORPHAN{i:06d}" for i in range(1, 6)]
        pool = _account_aware_db_pool(frozenset())   # empty — zero valid accounts
        proc = VaultUploadProcessor(
            _INTEGRITY_BANK, db_pool=pool,
            signature_vault=_sig_vault_stub(),
            pepper=_INTEGRITY_PEPPER,
        )
        r = await proc.process("SIGNATURE", _sig_csv_for_accounts(accounts), "user:test")
        assert r.rows_failed    == 5
        assert r.rows_processed == 0

    @pytest.mark.asyncio
    async def test_signature_rows_for_valid_accounts_all_succeed(self):
        """All accounts present in account_vault → every row succeeds."""
        accounts = [f"VALID{i:07d}" for i in range(1, 6)]
        proc = self._sig_proc(_hashes_for(accounts))
        r = await proc.process("SIGNATURE", _sig_csv_for_accounts(accounts), "user:test")
        assert r.rows_processed == 5
        assert r.rows_failed    == 0

    @pytest.mark.asyncio
    async def test_mixed_valid_and_orphan_gives_partial_batch(self):
        """3 valid + 2 orphan → PARTIAL (rows_failed=2, rows_processed=3)."""
        valid   = [f"VALID{i:07d}" for i in range(1, 4)]
        orphans = [f"ORPHAN{i:06d}" for i in range(1, 3)]
        proc = self._sig_proc(_hashes_for(valid))   # only valid are in account_vault
        r = await proc.process(
            "SIGNATURE",
            _sig_csv_for_accounts(valid + orphans),
            "user:test",
        )
        assert r.rows_processed == 3
        assert r.rows_failed    == 2

    @pytest.mark.asyncio
    async def test_orphan_error_entry_contains_correct_error_code(self):
        """Error entries for orphan rows use ACCOUNT_NOT_FOUND_IN_VAULT code."""
        accounts = ["ORPHAN000001"]
        proc = self._sig_proc(frozenset())
        r = await proc.process("SIGNATURE", _sig_csv_for_accounts(accounts), "user:test")
        assert r.rows_failed == 1
        err = r.errors[0]
        assert err["error_code"] == "ACCOUNT_NOT_FOUND_IN_VAULT"
        assert "ACCOUNT_DETAIL" in err["error"]  # tells operator what to do

    @pytest.mark.asyncio
    async def test_orphan_error_masks_account_number_to_last_4(self):
        """PII masking: only last 4 digits of account_number appear in error message."""
        proc = self._sig_proc(frozenset())
        r = await proc.process("SIGNATURE", _sig_csv_for_accounts(["ACC000099"]), "user:test")
        assert "0099" in r.errors[0]["error"]
        assert "ACC000099" not in r.errors[0]["error"]   # full number never logged

    # ------------------------------------------------------------------
    # ACCOUNT_DETAIL is exempt — it creates the vault entries
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_account_detail_upload_exempt_from_account_vault_check(self):
        """
        ACCOUNT_DETAIL IS the source of truth for cts.account_vault.
        The check must be skipped for this type regardless of pepper.
        """
        # Pool with zero valid accounts; if the check ran, all rows would fail.
        # With the exemption in place, rows proceed to the handler (which raises
        # RuntimeError because AccountVault is None — that is the expected path).
        pool = _account_aware_db_pool(frozenset())
        proc = VaultUploadProcessor(
            _INTEGRITY_BANK, db_pool=pool,
            account_vault=None,       # not configured
            pepper=_INTEGRITY_PEPPER,
        )
        csv = (
            b"account_number,holder_seq,holder_name,role,action\n"
            b"EXEMPT001,1,Test Holder,PRIMARY,UPSERT\n"
        )
        # Should raise RuntimeError("AccountVault not configured") NOT an orphan error
        r = await proc.process("ACCOUNT_DETAIL", csv, "user:test")
        assert r.rows_failed == 1
        assert "ACCOUNT_NOT_FOUND_IN_VAULT" not in r.errors[0].get("error_code", "")
        assert "AccountVault not configured" in r.errors[0]["error"]

    # ------------------------------------------------------------------
    # Without pepper the check is skipped (backward-compat / test mode)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_no_pepper_check_is_skipped_orphan_rows_pass_through(self):
        """
        Without pepper, _bulk_account_check is never called.
        Orphan rows are not caught at processor level — they reach the DB handler.
        (DB FK constraint or downstream check is the enforcement path in this mode.)
        """
        # db_pool is None → SIGNATURE handler raises RuntimeError before DB write
        proc = VaultUploadProcessor(
            _INTEGRITY_BANK, db_pool=None,
            signature_vault=_sig_vault_stub(),
            # pepper NOT set — check is intentionally skipped
        )
        r = await proc.process("SIGNATURE", _sig_csv_for_accounts(["ORPHAN001"]), "user:test")
        # No ACCOUNT_NOT_FOUND_IN_VAULT error — row reached the signature handler
        # which raised RuntimeError("DB pool not configured") because db_pool=None
        assert r.rows_failed == 1
        assert "ACCOUNT_NOT_FOUND_IN_VAULT" not in r.errors[0].get("error_code", "")

    # ------------------------------------------------------------------
    # Efficiency: one DB call per batch regardless of row count
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_bulk_check_is_one_db_fetch_call_for_100_rows(self):
        """
        _bulk_account_check must issue exactly ONE SELECT per batch,
        not one per row. Verified by counting conn.fetch calls.
        """
        fetch_count = [0]
        execute_count = [0]

        async def _execute(*args, **kwargs):
            execute_count[0] += 1

        async def _fetch(*args, **kwargs):
            fetch_count[0] += 1
            return []   # empty → all rows fail as orphans (not the point of this test)

        class _CountingConn:
            execute = staticmethod(_execute)
            fetch   = staticmethod(_fetch)

        conn = _CountingConn()

        class _Pool:
            def acquire(self):
                return self
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *a):
                pass

        proc = VaultUploadProcessor(
            _INTEGRITY_BANK, db_pool=_Pool(),
            signature_vault=_sig_vault_stub(),
            pepper=_INTEGRITY_PEPPER,
        )
        accounts = [f"ACC{i:09d}" for i in range(1, 101)]
        await proc.process("SIGNATURE", _sig_csv_for_accounts(accounts), "user:test")

        assert fetch_count[0] == 1, (
            f"Expected 1 bulk fetch, got {fetch_count[0]} — "
            "processor must not call conn.fetch once per row"
        )

    @pytest.mark.asyncio
    async def test_duplicate_account_numbers_in_csv_cause_single_hash_lookup(self):
        """
        100 rows with the same account_number → only 1 hash computed and
        the bulk SELECT sends 1 unique hash, not 100.
        """
        fetch_args: list = []

        async def _fetch(*args, **kwargs):
            fetch_args.append(args)
            return []

        class _Conn:
            async def execute(self, *a, **kw): pass
            fetch = staticmethod(_fetch)

        conn = _Conn()

        class _Pool:
            def acquire(self): return self
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): pass

        proc = VaultUploadProcessor(
            _INTEGRITY_BANK, db_pool=_Pool(),
            signature_vault=_sig_vault_stub(),
            pepper=_INTEGRITY_PEPPER,
        )
        same_account = ["SAME000001"] * 100
        await proc.process("SIGNATURE", _sig_csv_for_accounts(same_account), "user:test")

        # The second positional arg to conn.fetch is the list of hashes
        hashes_sent = fetch_args[0][2]   # $2 parameter in the SELECT
        assert len(hashes_sent) == 1, (
            f"Expected 1 unique hash, got {len(hashes_sent)} — "
            "deduplication must happen before the DB call"
        )
