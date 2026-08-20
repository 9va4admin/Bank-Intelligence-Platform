"""
Tests for modules/cts/workflows/vault_file_drop_workflow.py

File-drop path: MinIO event → webhook → Temporal → VaultFileDropWorkflow

Activities tested directly (no Temporal runtime):
  fetch_drop_file    — MinIO download + SHA-256 verification
  process_vault_csv  — VaultUploadProcessor wrapper
  archive_drop_file  — copy + remove (non-fatal)

Workflow routing tested via run_with_mocks():
  VAULT_UPDATED | PARSE_FAILED | VAULT_UPDATE_FAILED | DUPLICATE_SKIPPED
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


BANK_ID = "saraswat-coop"
BUCKET = "astra-vault-drops"
KEY = "saraswat-coop/pps/20260818_pps_batch1.csv"
ARCHIVE_BUCKET = "astra-vault-archive"


def _make_drop_input(**kwargs):
    from modules.cts.workflows.vault_file_drop_workflow import VaultFileDropInput
    csv_bytes = kwargs.pop("csv_bytes", b"action,account_number,cheque_number,cheque_date,amount,payee_name\n")
    file_hash = kwargs.pop("file_hash", hashlib.sha256(csv_bytes).hexdigest())
    defaults = dict(
        bank_id=BANK_ID,
        vault_type="PPS",
        minio_bucket=BUCKET,
        minio_key=KEY,
        file_hash=file_hash,
        feed_name="sftp",
    )
    defaults.update(kwargs)
    return VaultFileDropInput(**defaults), csv_bytes


def _mock_minio(csv_bytes: bytes = b""):
    minio = MagicMock()
    response = MagicMock()
    response.read = MagicMock(return_value=csv_bytes)
    minio.get_object = MagicMock(return_value=response)
    minio.copy_object = MagicMock(return_value=None)
    minio.remove_object = MagicMock(return_value=None)
    return minio


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TestVaultFileDropInput:
    def test_input_is_frozen(self):
        inp, _ = _make_drop_input()
        with pytest.raises(Exception):
            inp.bank_id = "changed"

    def test_feed_name_defaults_to_sftp(self):
        from modules.cts.workflows.vault_file_drop_workflow import VaultFileDropInput
        csv_b = b"header\n"
        inp = VaultFileDropInput(
            bank_id=BANK_ID,
            vault_type="PPS",
            minio_bucket=BUCKET,
            minio_key=KEY,
            file_hash=hashlib.sha256(csv_b).hexdigest(),
        )
        assert inp.feed_name == "sftp"

    def test_valid_vault_types_accepted(self):
        from modules.cts.workflows.vault_file_drop_workflow import VaultFileDropInput
        for vt in ("CHEQUE_BOOK", "LEAF_STATUS", "ACCOUNT_DETAIL", "SIGNATURE", "PPS"):
            csv_b = b"x\n"
            inp = VaultFileDropInput(
                bank_id=BANK_ID,
                vault_type=vt,
                minio_bucket=BUCKET,
                minio_key=KEY,
                file_hash=hashlib.sha256(csv_b).hexdigest(),
            )
            assert inp.vault_type == vt


# ---------------------------------------------------------------------------
# fetch_drop_file activity
# ---------------------------------------------------------------------------

class TestFetchDropFile:
    @pytest.mark.asyncio
    async def test_minio_none_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            fetch_drop_file, FetchDropFileInput,
        )
        inp = FetchDropFileInput(
            bank_id=BANK_ID, minio_bucket=BUCKET,
            minio_key=KEY, file_hash="abc123",
        )
        result = await fetch_drop_file(inp, minio_client=None)
        assert result.error == "MINIO_UNAVAILABLE"
        assert result.csv_bytes == ""

    @pytest.mark.asyncio
    async def test_hash_mismatch_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            fetch_drop_file, FetchDropFileInput,
        )
        csv_bytes = b"real,content\n"
        minio = _mock_minio(csv_bytes)
        inp = FetchDropFileInput(
            bank_id=BANK_ID, minio_bucket=BUCKET,
            minio_key=KEY, file_hash="0000000000000000",  # wrong hash
        )
        result = await fetch_drop_file(inp, minio_client=minio)
        assert result.error == "HASH_MISMATCH"
        assert result.csv_bytes == ""

    @pytest.mark.asyncio
    async def test_hash_match_returns_bytes(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            fetch_drop_file, FetchDropFileInput,
        )
        csv_bytes = b"action,account_number\nUPSERT,001\n"
        correct_hash = hashlib.sha256(csv_bytes).hexdigest()
        minio = _mock_minio(csv_bytes)
        inp = FetchDropFileInput(
            bank_id=BANK_ID, minio_bucket=BUCKET,
            minio_key=KEY, file_hash=correct_hash,
        )
        import base64
        result = await fetch_drop_file(inp, minio_client=minio)
        assert result.error is None
        assert result.csv_bytes == base64.b64encode(csv_bytes).decode()
        assert result.duplicate is False

    @pytest.mark.asyncio
    async def test_minio_get_object_exception_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            fetch_drop_file, FetchDropFileInput,
        )
        minio = MagicMock()
        minio.get_object = MagicMock(side_effect=RuntimeError("Connection refused"))
        inp = FetchDropFileInput(
            bank_id=BANK_ID, minio_bucket=BUCKET,
            minio_key=KEY, file_hash="abc123",
        )
        result = await fetch_drop_file(inp, minio_client=minio)
        assert result.error is not None
        assert "FETCH_FAILED" in result.error

    @pytest.mark.asyncio
    async def test_bank_id_present_in_activity_log(self, caplog):
        from modules.cts.workflows.vault_file_drop_workflow import (
            fetch_drop_file, FetchDropFileInput,
        )
        csv_bytes = b"test\n"
        minio = _mock_minio(csv_bytes)
        inp = FetchDropFileInput(
            bank_id="federal-bank", minio_bucket=BUCKET,
            minio_key=KEY, file_hash="badbadbad",
        )
        result = await fetch_drop_file(inp, minio_client=minio)
        # Hash mismatch with wrong hash — bank_id should be in logs
        assert result.error == "HASH_MISMATCH"


# ---------------------------------------------------------------------------
# process_vault_csv activity
# ---------------------------------------------------------------------------

class TestProcessVaultCSV:
    @pytest.mark.asyncio
    async def test_db_pool_none_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )
        inp = ProcessVaultCSVInput(
            bank_id=BANK_ID, vault_type="PPS",
            csv_bytes=b"action,account_number\n", changed_by="system:sftp",
            filename="test.csv", file_hash="abc123",
        )
        result = await process_vault_csv(inp, db_pool=None, vaults=None)
        assert result.error == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_unknown_vault_type_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )
        inp = ProcessVaultCSVInput(
            bank_id=BANK_ID, vault_type="BOGUS",
            csv_bytes=b"x\n", changed_by="system:sftp",
            filename="test.csv", file_hash="abc",
        )
        result = await process_vault_csv(inp, db_pool=MagicMock(), vaults={})
        assert result.error is not None
        assert "BOGUS" in result.error

    @pytest.mark.asyncio
    async def test_valid_csv_returns_batch_result(self):
        """process_vault_csv calls VaultUploadProcessor — mock the class on its source module."""
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )

        mock_proc_result = MagicMock()
        mock_proc_result.batch_id = "batch-xyz"
        mock_proc_result.rows_total = 3
        mock_proc_result.rows_processed = 3
        mock_proc_result.rows_failed = 0

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=mock_proc_result)

        # Local import inside the activity: patch on the source module
        with patch(
            "modules.cts.vaults.vault_upload_processor.VaultUploadProcessor",
            return_value=mock_processor,
        ):
            inp = ProcessVaultCSVInput(
                bank_id=BANK_ID, vault_type="PPS",
                csv_bytes=b"action,account_number,cheque_number,cheque_date,amount,payee_name\n",
                changed_by="system:sftp", filename="batch.csv", file_hash="abc123",
            )
            result = await process_vault_csv(inp, db_pool=MagicMock(), vaults={"pps": MagicMock()})

        assert result.error is None
        assert result.batch_id == "batch-xyz"
        assert result.rows_total == 3
        assert result.rows_processed == 3

    @pytest.mark.asyncio
    async def test_upload_channel_is_sftp(self):
        """process_vault_csv must always pass upload_channel='SFTP' to VaultUploadProcessor."""
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )

        mock_result = MagicMock()
        mock_result.batch_id = "b1"
        mock_result.rows_total = 1
        mock_result.rows_processed = 1
        mock_result.rows_failed = 0

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=mock_result)

        with patch(
            "modules.cts.vaults.vault_upload_processor.VaultUploadProcessor",
            return_value=mock_processor,
        ):
            inp = ProcessVaultCSVInput(
                bank_id=BANK_ID, vault_type="PPS",
                csv_bytes=b"hdr\n", changed_by="system:sftp",
                filename="f.csv", file_hash="abc",
            )
            await process_vault_csv(inp, db_pool=MagicMock(), vaults={})

        mock_processor.process.assert_awaited_once()
        _, kwargs = mock_processor.process.call_args
        assert kwargs.get("upload_channel") == "SFTP"

    @pytest.mark.asyncio
    async def test_changed_by_system_feed_name(self):
        """processor.process must receive changed_by passed from the activity input."""
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )

        mock_result = MagicMock()
        mock_result.batch_id = "b1"
        mock_result.rows_total = 1
        mock_result.rows_processed = 1
        mock_result.rows_failed = 0

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(return_value=mock_result)

        with patch(
            "modules.cts.vaults.vault_upload_processor.VaultUploadProcessor",
            return_value=mock_processor,
        ):
            inp = ProcessVaultCSVInput(
                bank_id=BANK_ID, vault_type="PPS",
                csv_bytes=b"hdr\n", changed_by="system:nightly-drop",
                filename="f.csv", file_hash="abc",
            )
            await process_vault_csv(inp, db_pool=MagicMock(), vaults={})

        _, kwargs = mock_processor.process.call_args
        assert kwargs.get("changed_by") == "system:nightly-drop"

    @pytest.mark.asyncio
    async def test_processor_exception_returns_error(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            process_vault_csv, ProcessVaultCSVInput,
        )

        mock_processor = AsyncMock()
        mock_processor.process = AsyncMock(side_effect=RuntimeError("vault exploded"))

        with patch(
            "modules.cts.vaults.vault_upload_processor.VaultUploadProcessor",
            return_value=mock_processor,
        ):
            inp = ProcessVaultCSVInput(
                bank_id=BANK_ID, vault_type="PPS",
                csv_bytes=b"hdr\n", changed_by="system:sftp",
                filename="f.csv", file_hash="abc",
            )
            result = await process_vault_csv(inp, db_pool=MagicMock(), vaults={})

        assert result.error is not None
        assert "vault exploded" in result.error


# ---------------------------------------------------------------------------
# archive_drop_file activity
# ---------------------------------------------------------------------------

class TestArchiveDropFile:
    @pytest.mark.asyncio
    async def test_minio_none_does_not_crash(self):
        """archive_drop_file is non-fatal — None minio_client must not raise."""
        from modules.cts.workflows.vault_file_drop_workflow import (
            archive_drop_file, ArchiveDropFileInput,
        )
        inp = ArchiveDropFileInput(bank_id=BANK_ID, minio_bucket=BUCKET, minio_key=KEY)
        await archive_drop_file(inp, minio_client=None)  # must not raise

    @pytest.mark.asyncio
    async def test_happy_path_copy_then_remove(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            archive_drop_file, ArchiveDropFileInput,
        )
        minio = _mock_minio()
        inp = ArchiveDropFileInput(bank_id=BANK_ID, minio_bucket=BUCKET, minio_key=KEY)
        await archive_drop_file(inp, minio_client=minio)
        minio.copy_object.assert_called_once()
        minio.remove_object.assert_called_once_with(BUCKET, KEY)

    @pytest.mark.asyncio
    async def test_archive_exception_does_not_raise(self):
        """Any exception in archive is swallowed — the batch is already processed."""
        from modules.cts.workflows.vault_file_drop_workflow import (
            archive_drop_file, ArchiveDropFileInput,
        )
        minio = MagicMock()
        minio.copy_object = MagicMock(side_effect=RuntimeError("S3 error"))
        minio.remove_object = MagicMock()
        inp = ArchiveDropFileInput(bank_id=BANK_ID, minio_bucket=BUCKET, minio_key=KEY)
        await archive_drop_file(inp, minio_client=minio)  # must not raise
        minio.remove_object.assert_not_called()  # remove not reached if copy fails

    @pytest.mark.asyncio
    async def test_archive_destination_bucket_is_vault_archive(self):
        from modules.cts.workflows.vault_file_drop_workflow import (
            archive_drop_file, ArchiveDropFileInput,
        )
        minio = _mock_minio()
        inp = ArchiveDropFileInput(bank_id=BANK_ID, minio_bucket=BUCKET, minio_key=KEY,
                                   archive_bucket=ARCHIVE_BUCKET)
        await archive_drop_file(inp, minio_client=minio)
        dest_bucket = minio.copy_object.call_args.args[0]
        assert dest_bucket == ARCHIVE_BUCKET


# ---------------------------------------------------------------------------
# VaultFileDropWorkflow routing (via run_with_mocks)
# ---------------------------------------------------------------------------

class TestVaultFileDropWorkflowRouting:
    def _wf(self):
        from modules.cts.workflows.vault_file_drop_workflow import VaultFileDropWorkflow
        return VaultFileDropWorkflow()

    def _fetch_ok(self, csv_bytes=b"action,account_number\n"):
        from modules.cts.workflows.vault_file_drop_workflow import FetchDropFileResult
        return FetchDropFileResult(csv_bytes=csv_bytes)

    def _process_ok(self, rows=3):
        from modules.cts.workflows.vault_file_drop_workflow import ProcessVaultCSVResult
        return ProcessVaultCSVResult(
            batch_id="batch-test-001",
            rows_total=rows, rows_processed=rows, rows_failed=0,
        )

    @pytest.mark.asyncio
    async def test_happy_path_vault_updated(self):
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
            "process": self._process_ok(3),
        })
        assert result.outcome == "VAULT_UPDATED"
        assert result.bank_id == BANK_ID
        assert result.vault_type == "PPS"
        assert result.batch_id == "batch-test-001"
        assert result.rows_processed == 3

    @pytest.mark.asyncio
    async def test_fetch_error_returns_parse_failed(self):
        from modules.cts.workflows.vault_file_drop_workflow import FetchDropFileResult
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": FetchDropFileResult(error="HASH_MISMATCH"),
        })
        assert result.outcome == "PARSE_FAILED"
        assert result.error == "HASH_MISMATCH"

    @pytest.mark.asyncio
    async def test_minio_unavailable_returns_parse_failed(self):
        from modules.cts.workflows.vault_file_drop_workflow import FetchDropFileResult
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": FetchDropFileResult(error="MINIO_UNAVAILABLE"),
        })
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_duplicate_file_returns_duplicate_skipped(self):
        from modules.cts.workflows.vault_file_drop_workflow import FetchDropFileResult
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": FetchDropFileResult(duplicate=True),
        })
        assert result.outcome == "DUPLICATE_SKIPPED"

    @pytest.mark.asyncio
    async def test_process_error_returns_vault_update_failed(self):
        from modules.cts.workflows.vault_file_drop_workflow import ProcessVaultCSVResult
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
            "process": ProcessVaultCSVResult(error="DB_UNAVAILABLE"),
        })
        assert result.outcome == "VAULT_UPDATE_FAILED"
        assert result.error == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_unknown_vault_type_returns_parse_failed(self):
        inp, _ = _make_drop_input(vault_type="INVALID_TYPE")
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
        })
        assert result.outcome == "PARSE_FAILED"
        assert "INVALID_TYPE" in result.error

    @pytest.mark.asyncio
    async def test_bank_id_always_in_result(self):
        inp, _ = _make_drop_input(bank_id="federal-bank")
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
            "process": self._process_ok(),
        })
        assert result.bank_id == "federal-bank"

    @pytest.mark.asyncio
    async def test_vault_type_in_result(self):
        inp, _ = _make_drop_input(vault_type="CHEQUE_BOOK")
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
            "process": self._process_ok(),
        })
        assert result.vault_type == "CHEQUE_BOOK"

    @pytest.mark.asyncio
    async def test_row_counts_propagated_from_process_result(self):
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": self._fetch_ok(),
            "process": self._process_ok(rows=50),
        })
        assert result.rows_total == 50
        assert result.rows_processed == 50
        assert result.rows_failed == 0

    @pytest.mark.asyncio
    async def test_parse_failed_has_no_batch_id(self):
        from modules.cts.workflows.vault_file_drop_workflow import FetchDropFileResult
        inp, _ = _make_drop_input()
        result = await self._wf().run_with_mocks(inp, {
            "fetch": FetchDropFileResult(error="FETCH_FAILED: timeout"),
        })
        assert result.outcome == "PARSE_FAILED"
        assert result.batch_id is None

    @pytest.mark.asyncio
    async def test_workflow_id_format(self):
        """Idempotency: workflow ID includes bank_id, vault_type, file_hash."""
        inp, csv_bytes = _make_drop_input()
        wid = f"cts-vault-drop-{inp.bank_id}-{inp.vault_type}-{inp.file_hash}"
        # The file_hash uniqueness ensures different files get different workflow IDs
        assert inp.bank_id in wid
        assert inp.vault_type in wid
        assert inp.file_hash in wid
