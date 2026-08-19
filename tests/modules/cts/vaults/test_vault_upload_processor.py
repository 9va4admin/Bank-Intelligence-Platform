"""
Tests for modules/cts/vaults/vault_upload_processor.py

Covers the UI upload path: POST /v1/cts/vault/upload/{vault_type}
→ VaultUploadProcessor.process()

Both channels produce the same processor call:
  UI:   changed_by="user:{user_id}", upload_channel="UI"
  SFTP: changed_by="system:{feed_name}", upload_channel="SFTP"

bank_id is NEVER in the CSV — always injected at processor construction.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BANK_ID = "saraswat-coop"


def _async_ctx(value=None):
    """Minimal async context manager."""
    class _Ctx:
        async def __aenter__(self):
            return value
        async def __aexit__(self, *_):
            pass
    return _Ctx()


def _mock_conn():
    """Asyncpg-like connection mock."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=_async_ctx(None))
    return conn


def _mock_pool(conn=None):
    if conn is None:
        conn = _mock_conn()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_async_ctx(conn))
    pool._conn = conn
    return pool


def _csv(*lines: str) -> bytes:
    return "\n".join(lines).encode("utf-8")


def _mock_pps_vault():
    v = MagicMock()
    v.store_pps = AsyncMock(return_value=None)
    return v


def _mock_leaf_vault():
    v = MagicMock()
    v.store_book = AsyncMock(return_value=None)
    v.set_leaf_status = AsyncMock(return_value=True)
    return v


def _make_processor(bank_id=BANK_ID, db_pool="default",
                    pps_vault=None, cheque_leaf_vault=None,
                    account_vault=None, signature_vault=None):
    from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor
    pool = _mock_pool() if db_pool == "default" else db_pool
    return VaultUploadProcessor(
        bank_id=bank_id,
        db_pool=pool,
        cheque_leaf_vault=cheque_leaf_vault,
        account_vault=account_vault,
        signature_vault=signature_vault,
        pps_vault=pps_vault,
    )


# ---------------------------------------------------------------------------
# Unknown vault type
# ---------------------------------------------------------------------------

class TestUnknownVaultType:
    @pytest.mark.asyncio
    async def test_unknown_vault_type_raises(self):
        proc = _make_processor()
        with pytest.raises(ValueError, match="Unknown vault_type"):
            await proc.process("BOGUS", b"a,b\n1,2", changed_by="user:ops1")

    @pytest.mark.asyncio
    async def test_all_valid_vault_types_accepted(self):
        """Each valid type must not raise ValueError on a header-only CSV."""
        from modules.cts.vaults.vault_upload_processor import _COLUMNS
        for vt in _COLUMNS:
            header = ",".join(["action"] + _COLUMNS[vt]["required"])
            csv_data = _csv(header)
            proc = _make_processor()
            result = await proc.process(vt, csv_data, changed_by="user:ops1")
            assert result.rows_total == 0


# ---------------------------------------------------------------------------
# Missing required columns
# ---------------------------------------------------------------------------

class TestMissingColumns:
    @pytest.mark.asyncio
    async def test_pps_missing_cheque_number_raises(self):
        proc = _make_processor(pps_vault=_mock_pps_vault())
        csv_data = _csv(
            "action,account_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,2026-08-10,750000.00,Reliance Industries",
        )
        with pytest.raises(ValueError, match="cheque_number"):
            await proc.process("PPS", csv_data, changed_by="user:ops1")

    @pytest.mark.asyncio
    async def test_cheque_book_missing_series_end_raises(self):
        proc = _make_processor(cheque_leaf_vault=_mock_leaf_vault())
        csv_data = _csv(
            "action,account_number,series_start,issued_date",
            "INSERT_ONLY,00112233445566,000001,2026-08-01",
        )
        with pytest.raises(ValueError, match="series_end"):
            await proc.process("CHEQUE_BOOK", csv_data, changed_by="user:it1")

    @pytest.mark.asyncio
    async def test_leaf_status_missing_new_status_raises(self):
        proc = _make_processor(cheque_leaf_vault=_mock_leaf_vault())
        csv_data = _csv(
            "action,account_number,cheque_number",
            "UPDATE_ONLY,00112233445566,000205",
        )
        with pytest.raises(ValueError, match="new_status"):
            await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")


# ---------------------------------------------------------------------------
# Invalid action value
# ---------------------------------------------------------------------------

class TestInvalidAction:
    @pytest.mark.asyncio
    async def test_invalid_action_counted_as_failed_row(self):
        proc = _make_processor(pps_vault=_mock_pps_vault())
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "OBLITERATE,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_failed == 1
        assert result.rows_processed == 0
        assert any("OBLITERATE" in e["error"] for e in result.errors)

    @pytest.mark.asyncio
    async def test_valid_actions_not_flagged_as_invalid(self):
        for action in ("UPSERT", "INSERT_ONLY", "UPDATE_ONLY"):
            leaf = _mock_leaf_vault()
            proc = _make_processor(cheque_leaf_vault=leaf)
            csv_data = _csv(
                "action,account_number,cheque_number,new_status",
                f"{action},00112233445566,000205,CANCELLED",
            )
            result = await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")
            assert result.rows_failed == 0, f"Action {action} should not be counted as invalid"


# ---------------------------------------------------------------------------
# PPS vault — happy paths
# ---------------------------------------------------------------------------

class TestPPSHappyPath:
    @pytest.mark.asyncio
    async def test_upsert_calls_store_pps(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance Industries Ltd",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_processed == 1
        assert result.rows_failed == 0
        pps.store_pps.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bank_id_is_processor_constructor_value(self):
        """bank_id must never come from CSV — it's the processor's _bank_id."""
        proc = _make_processor(bank_id="federal-bank", pps_vault=_mock_pps_vault())
        assert proc._bank_id == "federal-bank"

    @pytest.mark.asyncio
    async def test_amount_converted_to_paise(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,7500.50,Payee Name",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["amount_paise"] == 750050

    @pytest.mark.asyncio
    async def test_whole_rupee_amount_to_paise(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "INSERT_ONLY,00112233445566,000124,2026-08-10,50000.00,TCS Ltd",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["amount_paise"] == 5000000

    @pytest.mark.asyncio
    async def test_deactivate_maps_to_cancel(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "DEACTIVATE,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["action"] == "CANCEL"

    @pytest.mark.asyncio
    async def test_upsert_action_passed_as_upsert(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["action"] == "UPSERT"

    @pytest.mark.asyncio
    async def test_non_numeric_amount_fails_row(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,NOT_A_NUMBER,Payee",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_failed == 1
        assert result.rows_processed == 0
        assert "amount must be numeric" in result.errors[0]["error"]

    @pytest.mark.asyncio
    async def test_multiple_rows_all_processed(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
            "UPSERT,00998877665544,000456,2026-08-15,1500000.00,TCS",
            "UPSERT,00776655443322,000789,2026-08-20,2500000.00,Infosys",
        )
        result = await proc.process("PPS", csv_data, changed_by="system:sftp-feed")
        assert result.rows_total == 3
        assert result.rows_processed == 3
        assert result.rows_failed == 0
        assert pps.store_pps.await_count == 3

    @pytest.mark.asyncio
    async def test_partial_failure_tracked(self):
        pps = _mock_pps_vault()
        pps.store_pps = AsyncMock(side_effect=[None, ValueError("DB error"), None])
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000001,2026-08-10,100000.00,Payee A",
            "UPSERT,00998877665544,000002,2026-08-10,200000.00,Payee B",
            "UPSERT,00776655443322,000003,2026-08-10,300000.00,Payee C",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_processed == 2
        assert result.rows_failed == 1
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_pps_vault_not_configured_fails_row(self):
        proc = _make_processor(pps_vault=None)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_failed == 1
        assert "PPSVault not configured" in result.errors[0]["error"]

    @pytest.mark.asyncio
    async def test_registration_channel_defaults_to_branch_upload(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["registration_channel"] == "BRANCH_UPLOAD"

    @pytest.mark.asyncio
    async def test_registration_channel_from_csv(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name,registration_channel",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance,NET_BANKING",
        )
        await proc.process("PPS", csv_data, changed_by="user:ops1")
        kwargs = pps.store_pps.call_args.kwargs
        assert kwargs["registration_channel"] == "NET_BANKING"


# ---------------------------------------------------------------------------
# CHEQUE_BOOK vault
# ---------------------------------------------------------------------------

class TestChequeBookUpload:
    @pytest.mark.asyncio
    async def test_insert_only_calls_store_book(self):
        leaf = _mock_leaf_vault()
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,series_start,series_end,issued_date",
            "INSERT_ONLY,00112233445566,000001,000050,2026-08-01",
        )
        result = await proc.process("CHEQUE_BOOK", csv_data, changed_by="user:it1")
        assert result.rows_processed == 1
        leaf.store_book.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_series_start_greater_than_end_fails_row(self):
        leaf = _mock_leaf_vault()
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,series_start,series_end,issued_date",
            "INSERT_ONLY,00112233445566,000050,000001,2026-08-01",
        )
        result = await proc.process("CHEQUE_BOOK", csv_data, changed_by="user:it1")
        assert result.rows_failed == 1
        assert result.rows_processed == 0

    @pytest.mark.asyncio
    async def test_equal_series_start_end_valid(self):
        """Single-leaf book (start==end) must succeed."""
        leaf = _mock_leaf_vault()
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,series_start,series_end,issued_date",
            "INSERT_ONLY,00112233445566,000025,000025,2026-08-01",
        )
        result = await proc.process("CHEQUE_BOOK", csv_data, changed_by="user:it1")
        assert result.rows_processed == 1

    @pytest.mark.asyncio
    async def test_cheque_leaf_vault_not_configured_fails_row(self):
        proc = _make_processor(cheque_leaf_vault=None)
        csv_data = _csv(
            "action,account_number,series_start,series_end,issued_date",
            "INSERT_ONLY,00112233445566,000001,000050,2026-08-01",
        )
        result = await proc.process("CHEQUE_BOOK", csv_data, changed_by="user:it1")
        assert result.rows_failed == 1
        assert "ChequeLeafVault not configured" in result.errors[0]["error"]


# ---------------------------------------------------------------------------
# LEAF_STATUS vault
# ---------------------------------------------------------------------------

class TestLeafStatusUpload:
    @pytest.mark.asyncio
    async def test_update_only_calls_set_leaf_status(self):
        leaf = _mock_leaf_vault()
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,cheque_number,new_status",
            "UPDATE_ONLY,00112233445566,000205,CANCELLED",
        )
        result = await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")
        assert result.rows_processed == 1
        leaf.set_leaf_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_leaf_not_found_on_update_only_not_an_error(self):
        """set_leaf_status returns False when leaf not found — row is processed, not failed."""
        leaf = _mock_leaf_vault()
        leaf.set_leaf_status = AsyncMock(return_value=False)
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,cheque_number,new_status",
            "UPDATE_ONLY,00112233445566,999999,CANCELLED",
        )
        result = await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")
        assert result.rows_failed == 0
        assert result.rows_processed == 1

    @pytest.mark.asyncio
    async def test_deactivate_forces_status_to_stopped(self):
        leaf = _mock_leaf_vault()
        proc = _make_processor(cheque_leaf_vault=leaf)
        csv_data = _csv(
            "action,account_number,cheque_number,new_status",
            "DEACTIVATE,00112233445566,000205,CANCELLED",
        )
        await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")
        kwargs = leaf.set_leaf_status.call_args.kwargs
        assert kwargs["new_status"] == "STOPPED"

    @pytest.mark.asyncio
    async def test_leaf_vault_not_configured_fails_row(self):
        proc = _make_processor(cheque_leaf_vault=None)
        csv_data = _csv(
            "action,account_number,cheque_number,new_status",
            "UPDATE_ONLY,00112233445566,000205,CANCELLED",
        )
        result = await proc.process("LEAF_STATUS", csv_data, changed_by="user:ops1")
        assert result.rows_failed == 1
        assert "ChequeLeafVault not configured" in result.errors[0]["error"]


# ---------------------------------------------------------------------------
# SIGNATURE vault
# ---------------------------------------------------------------------------

class TestSignatureUpload:
    def _sig_vault(self, pepper="test-pepper"):
        v = MagicMock()
        v._pepper = pepper
        return v

    @pytest.mark.asyncio
    async def test_insert_only_executes_db_upsert(self):
        conn = _mock_conn()
        pool = _mock_pool(conn)
        sig = self._sig_vault()

        with patch("modules.cts.vaults.vault_upload_processor.hash_account_number",
                   return_value="hashed-acct"):
            proc = _make_processor(signature_vault=sig, db_pool=pool)
            csv_data = _csv(
                "action,account_number,signatory_id,mandate_rule",
                "INSERT_ONLY,00112233445566,PRIMARY,ANY_ONE",
            )
            result = await proc.process("SIGNATURE", csv_data, changed_by="user:it1")

        assert result.rows_processed == 1
        conn.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_signature_vault_not_configured_fails_row(self):
        proc = _make_processor(signature_vault=None)
        csv_data = _csv(
            "action,account_number,signatory_id,mandate_rule",
            "INSERT_ONLY,00112233445566,PRIMARY,ANY_ONE",
        )
        result = await proc.process("SIGNATURE", csv_data, changed_by="user:it1")
        assert result.rows_failed == 1
        assert "SignatureVault not configured" in result.errors[0]["error"]

    @pytest.mark.asyncio
    async def test_deactivate_passes_is_active_false(self):
        conn = _mock_conn()
        pool = _mock_pool(conn)
        sig = self._sig_vault()

        with patch("modules.cts.vaults.vault_upload_processor.hash_account_number",
                   return_value="hashed-acct"):
            proc = _make_processor(signature_vault=sig, db_pool=pool)
            csv_data = _csv(
                "action,account_number,signatory_id,mandate_rule",
                "DEACTIVATE,00112233445566,PRIMARY,ANY_ONE",
            )
            result = await proc.process("SIGNATURE", csv_data, changed_by="user:it1")

        assert result.rows_processed == 1
        call_args = conn.execute.call_args
        assert False in call_args.args


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------

class TestBatchLifecycle:
    @pytest.mark.asyncio
    async def test_batch_id_is_uuid(self):
        import uuid
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert uuid.UUID(result.batch_id)

    @pytest.mark.asyncio
    async def test_no_db_pool_still_processes_rows(self):
        """db_pool=None: batch DB writes skipped but rows are still processed."""
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps, db_pool=None)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_processed == 1

    @pytest.mark.asyncio
    async def test_sftp_channel_accepted(self):
        pps = _mock_pps_vault()
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="system:nightly-sftp",
                                    upload_channel="SFTP")
        assert result.rows_processed == 1

    @pytest.mark.asyncio
    async def test_empty_csv_zero_rows(self):
        """Header-only CSV (no data rows) — rows_total=0, no errors."""
        proc = _make_processor(pps_vault=_mock_pps_vault())
        csv_data = _csv("action,account_number,cheque_number,cheque_date,amount,payee_name")
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.rows_total == 0
        assert result.rows_processed == 0
        assert result.rows_failed == 0

    @pytest.mark.asyncio
    async def test_error_row_index_starts_at_2(self):
        """Row 1 is header; first data row index is 2."""
        pps = _mock_pps_vault()
        pps.store_pps = AsyncMock(side_effect=RuntimeError("vault error"))
        proc = _make_processor(pps_vault=pps)
        csv_data = _csv(
            "action,account_number,cheque_number,cheque_date,amount,payee_name",
            "UPSERT,00112233445566,000123,2026-08-10,750000.00,Reliance",
        )
        result = await proc.process("PPS", csv_data, changed_by="user:ops1")
        assert result.errors[0]["row"] == 2
