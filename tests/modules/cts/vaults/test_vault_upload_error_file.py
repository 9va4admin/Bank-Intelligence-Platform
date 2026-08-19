"""
TDD tests for VaultUploadProcessor MinIO error file write.

Design:
  - When rows_failed > 0 and minio_client + error_file_bucket are set:
      * _write_error_file() writes a UTF-8 CSV to MinIO with columns:
        row,error_message,error_code
      * The object key is stored as result.error_file_path
      * _complete_batch() persists error_file_path to cts.vault_upload_batches

  - When minio_client is None or error_file_bucket is None:
      * No MinIO write — result.error_file_path is None
      * No exception raised (MinIO unavailability is non-fatal)

  - When rows_failed == 0 (clean batch):
      * No MinIO write even if minio_client is configured
      * result.error_file_path is None

  - CSV format:
      * Header: row,error_message,error_code
      * error_code defaults to "" when absent from error dict
      * All errors present — no cap (unlike errors_json JSONB)

  - Key pattern: {bank_id}/vault-errors/{batch_id}.csv
"""
from __future__ import annotations

import csv
import io
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor, VaultUploadResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BANK_ID = "saraswat-coop"
BUCKET  = "astra-vault-errors"


def _pps_csv(rows: int = 3, bad_amount_rows: frozenset[int] = frozenset()) -> bytes:
    lines = ["action,account_number,cheque_number,cheque_date,amount,payee_name"]
    for i in range(1, rows + 1):
        amount = "NOT_A_NUMBER" if i in bad_amount_rows else f"{i * 1000}.00"
        lines.append(f"UPSERT,11223344556{i:02d},0001{i:02d},2026-08-20,{amount},Payee {i}")
    return "\n".join(lines).encode("utf-8")


def _mock_minio(bucket: str = BUCKET) -> MagicMock:
    """Returns a mock MinIO client whose put_object records calls."""
    client = MagicMock()
    client.put_object = MagicMock(return_value=None)
    return client


def _counting_pool() -> tuple[MagicMock, list[int]]:
    """Returns a fake DB pool and an execute counter."""
    exec_ctr: list[int] = [0]

    async def _execute(*a, **kw) -> None:
        exec_ctr[0] += 1

    async def _fetch(*a, **kw) -> list:
        return []

    class _Conn:
        execute = staticmethod(_execute)
        fetch = staticmethod(_fetch)

    class _Pool:
        def acquire(self):
            return self
        async def __aenter__(self):
            return _Conn()
        async def __aexit__(self, *a):
            pass

    return _Pool(), exec_ctr


def _make_processor(
    minio_client=None,
    error_file_bucket: str | None = BUCKET,
    pool=None,
) -> VaultUploadProcessor:
    if pool is None:
        pool, _ = _counting_pool()
    pps_vault = MagicMock()
    pps_vault.store_pps = AsyncMock()
    return VaultUploadProcessor(
        bank_id=BANK_ID,
        db_pool=pool,
        pps_vault=pps_vault,
        minio_client=minio_client,
        error_file_bucket=error_file_bucket,
    )


# ---------------------------------------------------------------------------
# TestErrorFileWrite — core behaviour
# ---------------------------------------------------------------------------

class TestErrorFileWrite:

    @pytest.mark.asyncio
    async def test_error_file_path_set_on_partial_batch(self):
        """rows_failed > 0 + minio configured → result.error_file_path is non-None."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(5, bad_amount_rows={2, 4}),
            changed_by="user:nilesh",
        )
        assert result.rows_failed == 2
        assert result.error_file_path is not None

    @pytest.mark.asyncio
    async def test_error_file_path_is_none_on_clean_batch(self):
        """rows_failed == 0 → no MinIO write, error_file_path is None."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3),
            changed_by="user:nilesh",
        )
        assert result.rows_failed == 0
        assert result.error_file_path is None
        minio.put_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_file_path_is_none_when_minio_not_configured(self):
        """minio_client=None → no write, error_file_path=None (non-fatal)."""
        proc = _make_processor(minio_client=None)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        assert result.rows_failed == 1
        assert result.error_file_path is None

    @pytest.mark.asyncio
    async def test_error_file_path_is_none_when_bucket_not_configured(self):
        """error_file_bucket=None → no write even with minio_client present."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio, error_file_bucket=None)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        assert result.rows_failed == 1
        assert result.error_file_path is None
        minio.put_object.assert_not_called()

    @pytest.mark.asyncio
    async def test_minio_put_called_once_with_correct_bucket(self):
        """put_object called exactly once with the configured bucket."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(5, bad_amount_rows={3}),
            changed_by="user:nilesh",
        )
        assert minio.put_object.call_count == 1
        call_kwargs = minio.put_object.call_args
        bucket_arg = call_kwargs[1].get("bucket_name") or call_kwargs[0][0]
        assert bucket_arg == BUCKET

    @pytest.mark.asyncio
    async def test_key_pattern_is_bank_id_slash_vault_errors_slash_batch_id_csv(self):
        """Key must be {bank_id}/vault-errors/{batch_id}.csv."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        call_kwargs = minio.put_object.call_args
        object_key = call_kwargs[1].get("object_name") or call_kwargs[0][1]
        expected_key = f"{BANK_ID}/vault-errors/{result.batch_id}.csv"
        assert object_key == expected_key

    @pytest.mark.asyncio
    async def test_error_file_path_equals_minio_key(self):
        """result.error_file_path must match the key passed to put_object."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={2}),
            changed_by="user:nilesh",
        )
        call_kwargs = minio.put_object.call_args
        object_key = call_kwargs[1].get("object_name") or call_kwargs[0][1]
        assert result.error_file_path == object_key

    @pytest.mark.asyncio
    async def test_minio_exception_does_not_crash_batch(self):
        """MinIO failure is non-fatal — batch still completes, error_file_path=None."""
        minio = MagicMock()
        minio.put_object = MagicMock(side_effect=RuntimeError("MinIO bucket not found"))
        proc = _make_processor(minio_client=minio)
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        # Batch must complete successfully despite MinIO failure
        assert result.rows_failed == 1
        assert result.rows_processed == 2
        assert result.error_file_path is None   # not set when write failed


# ---------------------------------------------------------------------------
# TestErrorFileCsvContent — what is inside the uploaded file
# ---------------------------------------------------------------------------

class TestErrorFileCsvContent:

    def _capture_uploaded_csv(self, minio: MagicMock) -> list[dict]:
        """Extract and parse the CSV bytes passed to put_object."""
        call_kwargs = minio.put_object.call_args
        data_arg = call_kwargs[1].get("data") or call_kwargs[0][2]
        # data is a BytesIO
        raw = data_arg.read() if hasattr(data_arg, "read") else data_arg
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        return list(reader)

    @pytest.mark.asyncio
    async def test_csv_header_is_row_error_message_error_code(self):
        """Header row must be exactly: row,error_message,error_code."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(2, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        rows = self._capture_uploaded_csv(minio)
        assert list(rows[0].keys()) == ["row", "error_message", "error_code"]

    @pytest.mark.asyncio
    async def test_csv_contains_all_failed_rows_no_cap(self):
        """All 50 errors present — no artificial cap."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        bad = frozenset(range(1, 51))   # 50 bad rows out of 60
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(60, bad_amount_rows=bad),
            changed_by="user:nilesh",
        )
        rows = self._capture_uploaded_csv(minio)
        assert len(rows) == 50

    @pytest.mark.asyncio
    async def test_csv_row_number_matches_error_dict(self):
        """row column must match the CSV row index from the error dict."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(5, bad_amount_rows={3}),   # row 4 (1-indexed header=1)
            changed_by="user:nilesh",
        )
        rows = self._capture_uploaded_csv(minio)
        assert len(rows) == 1
        assert rows[0]["row"] == "4"     # header=row1, data starts at row2; bad row is 3rd data = row 4

    @pytest.mark.asyncio
    async def test_csv_error_message_contains_reason(self):
        """error_message column contains the rejection reason text."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(2, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        rows = self._capture_uploaded_csv(minio)
        assert "amount" in rows[0]["error_message"].lower() or "numeric" in rows[0]["error_message"].lower()

    @pytest.mark.asyncio
    async def test_csv_error_code_present_when_set(self):
        """error_code column populated from error dict when present."""
        minio = _mock_minio()
        # Use SIGNATURE type and missing account vault — triggers ACCOUNT_NOT_FOUND_IN_VAULT
        sig_csv = (
            "action,account_number,signatory_id,mandate_rule\n"
            "UPSERT,00112233445566,SIG001,ANY_ONE\n"
        ).encode("utf-8")
        pool, _ = _counting_pool()
        sig_vault = MagicMock()
        sig_vault._pepper = "test-pepper"
        proc = VaultUploadProcessor(
            bank_id=BANK_ID,
            db_pool=pool,
            signature_vault=sig_vault,
            minio_client=minio,
            error_file_bucket=BUCKET,
            pepper="test-pepper",
        )
        # Override _bulk_account_check to return empty frozenset (all orphans)
        async def _no_accounts(rows):
            return frozenset()
        proc._bulk_account_check = _no_accounts

        result = await proc.process(
            vault_type="SIGNATURE",
            csv_content=sig_csv,
            changed_by="user:nilesh",
        )
        assert result.rows_failed == 1
        rows = self._capture_uploaded_csv(minio)
        assert rows[0]["error_code"] == "ACCOUNT_NOT_FOUND_IN_VAULT"

    @pytest.mark.asyncio
    async def test_csv_error_code_empty_string_when_absent(self):
        """error_code column is empty string (not 'None') when error dict has no error_code."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        # Bad amount → no error_code in dict
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(2, bad_amount_rows={1}),
            changed_by="user:nilesh",
        )
        rows = self._capture_uploaded_csv(minio)
        assert rows[0]["error_code"] == ""

    @pytest.mark.asyncio
    async def test_csv_is_valid_utf8(self):
        """Written bytes must decode as UTF-8 without errors."""
        minio = _mock_minio()
        proc = _make_processor(minio_client=minio)
        await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={2}),
            changed_by="user:nilesh",
        )
        call_kwargs = minio.put_object.call_args
        data_arg = call_kwargs[1].get("data") or call_kwargs[0][2]
        raw = data_arg.read() if hasattr(data_arg, "read") else data_arg
        raw.decode("utf-8")   # must not raise


# ---------------------------------------------------------------------------
# TestErrorFileDbPersistence — error_file_path stored in DB
# ---------------------------------------------------------------------------

class TestErrorFileDbPersistence:

    @pytest.mark.asyncio
    async def test_complete_batch_stores_error_file_path_in_db(self):
        """_complete_batch UPDATE must include error_file_path = MinIO key."""
        minio = _mock_minio()

        executed_sqls: list[str] = []
        executed_args: list[tuple] = []

        async def _execute(sql, *args, **kw):
            executed_sqls.append(sql)
            executed_args.append(args)

        async def _fetch(*a, **kw):
            return []

        class _Conn:
            execute = staticmethod(_execute)
            fetch = staticmethod(_fetch)

        class _Pool:
            def acquire(self): return self
            async def __aenter__(self): return _Conn()
            async def __aexit__(self, *a): pass

        pps_vault = MagicMock()
        pps_vault.store_pps = AsyncMock()

        proc = VaultUploadProcessor(
            bank_id=BANK_ID,
            db_pool=_Pool(),
            pps_vault=pps_vault,
            minio_client=minio,
            error_file_bucket=BUCKET,
        )
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3, bad_amount_rows={2}),
            changed_by="user:nilesh",
        )

        # Find the UPDATE statement (last execute call = _complete_batch)
        update_calls = [(s, a) for s, a in zip(executed_sqls, executed_args)
                        if "UPDATE" in s.upper() and "vault_upload_batches" in s]
        assert update_calls, "No UPDATE on vault_upload_batches found"
        update_sql, update_args = update_calls[-1]

        # error_file_path must appear in UPDATE SQL
        assert "error_file_path" in update_sql.lower()
        # And the actual path value must be in the args
        assert result.error_file_path in update_args

    @pytest.mark.asyncio
    async def test_complete_batch_stores_null_error_file_path_on_clean_batch(self):
        """Clean batch → error_file_path=None persisted (or omitted from SET clause)."""
        minio = _mock_minio()

        executed_sqls: list[str] = []
        executed_args: list[tuple] = []

        async def _execute(sql, *args, **kw):
            executed_sqls.append(sql)
            executed_args.append(args)

        async def _fetch(*a, **kw):
            return []

        class _Conn:
            execute = staticmethod(_execute)
            fetch = staticmethod(_fetch)

        class _Pool:
            def acquire(self): return self
            async def __aenter__(self): return _Conn()
            async def __aexit__(self, *a): pass

        pps_vault = MagicMock()
        pps_vault.store_pps = AsyncMock()

        proc = VaultUploadProcessor(
            bank_id=BANK_ID,
            db_pool=_Pool(),
            pps_vault=pps_vault,
            minio_client=minio,
            error_file_bucket=BUCKET,
        )
        result = await proc.process(
            vault_type="PPS",
            csv_content=_pps_csv(3),       # all valid
            changed_by="user:nilesh",
        )

        assert result.error_file_path is None
        minio.put_object.assert_not_called()
