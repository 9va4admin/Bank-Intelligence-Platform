"""
Tests for modules/msv/enrollment/file_watcher.py — DropZoneHandler.

Covers:
  - atomic rename incoming → processing before any processing
  - success → file moved to processed/{filename}.{timestamp}
  - failure → file moved to failed/{filename} + failed/{filename}.error.txt written
  - orphan recovery: files stranded in processing/ are re-processed at startup
  - _wait_stable: polls file size until stable for 2 consecutive checks
"""
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.msv.enrollment.file_watcher import DropZoneHandler


def _make_processor(success: bool = True):
    """Returns a mock BulkEnrollmentProcessor."""
    from modules.msv.enrollment.bulk_enrollment import BulkEnrollmentSummary
    proc = MagicMock()
    if success:
        proc.process_file = AsyncMock(return_value=BulkEnrollmentSummary(
            job_id="job-001",
            bank_id="kotak-mah",
            total_processed=10,
            enrolled=10,
            skipped=0,
            failed=0,
            total_signatures_enrolled=30,
        ))
    else:
        proc.process_file = AsyncMock(side_effect=RuntimeError("CBS_UNAVAILABLE"))
    return proc


def _make_handler(tmp_path: Path, processor=None, bank_id: str = "kotak-mah") -> DropZoneHandler:
    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    processed = tmp_path / "processed"
    failed = tmp_path / "failed"
    for d in (incoming, processing, processed, failed):
        d.mkdir(parents=True, exist_ok=True)

    proc = processor or _make_processor()
    return DropZoneHandler(
        incoming_dir=incoming,
        processing_dir=processing,
        processed_dir=processed,
        failed_dir=failed,
        processor=proc,
        bank_id=bank_id,
    )


class TestDropZoneHandler:
    @pytest.mark.asyncio
    async def test_atomic_rename_to_processing_before_process_call(self, tmp_path):
        """File must be in processing/ when process_file is called."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "signatories_bulk_20260709.csv.gz"
        test_file.write_bytes(b"fake gzip content")

        captured_path: list[Path] = []

        from modules.msv.enrollment.bulk_enrollment import BulkEnrollmentSummary
        proc = MagicMock()

        async def _capture(file_path, bank_id, job_id):
            captured_path.append(file_path)
            # File must already be in processing/ when this is called
            return BulkEnrollmentSummary(
                job_id=job_id, bank_id=bank_id,
                total_processed=0, enrolled=0, skipped=0, failed=0,
                total_signatures_enrolled=0,
            )
        proc.process_file = AsyncMock(side_effect=_capture)

        handler = _make_handler(tmp_path, processor=proc)
        await handler.handle_new_file(test_file)

        assert len(captured_path) == 1
        processing_dir = tmp_path / "processing"
        assert captured_path[0].parent == processing_dir

    @pytest.mark.asyncio
    async def test_success_moves_to_processed(self, tmp_path):
        """On success, file should move to processed/ and not exist in processing/."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "signatories_bulk_20260709.csv.gz"
        test_file.write_bytes(b"fake gzip content")

        handler = _make_handler(tmp_path, processor=_make_processor(success=True))
        await handler.handle_new_file(test_file)

        processing_dir = tmp_path / "processing"
        processed_dir = tmp_path / "processed"

        # Processing dir should be empty
        assert not list(processing_dir.iterdir())
        # Processed dir should have the file (possibly with timestamp suffix)
        processed_files = list(processed_dir.iterdir())
        assert len(processed_files) == 1
        assert "signatories_bulk_20260709.csv.gz" in processed_files[0].name

    @pytest.mark.asyncio
    async def test_failure_moves_to_failed_with_error_txt(self, tmp_path):
        """On failure, file goes to failed/ AND a .error.txt is written there."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "signatories_bulk_20260709.csv.gz"
        test_file.write_bytes(b"fake gzip content")

        handler = _make_handler(tmp_path, processor=_make_processor(success=False))
        await handler.handle_new_file(test_file)

        processing_dir = tmp_path / "processing"
        failed_dir = tmp_path / "failed"

        # Processing dir should be empty
        assert not list(processing_dir.iterdir())
        # Failed dir should have 2 files: the data file + .error.txt
        failed_files = {f.name for f in failed_dir.iterdir()}
        assert any("signatories_bulk_20260709.csv.gz" in n for n in failed_files)
        assert any(".error.txt" in n for n in failed_files)

    @pytest.mark.asyncio
    async def test_error_txt_contains_exception_message(self, tmp_path):
        """The .error.txt must contain the exception text."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "signatories_bulk_20260709.csv.gz"
        test_file.write_bytes(b"fake gzip content")

        handler = _make_handler(tmp_path, processor=_make_processor(success=False))
        await handler.handle_new_file(test_file)

        failed_dir = tmp_path / "failed"
        error_files = [f for f in failed_dir.iterdir() if f.suffix == ".txt"]
        assert len(error_files) == 1
        content = error_files[0].read_text(encoding="utf-8")
        assert "CBS_UNAVAILABLE" in content

    @pytest.mark.asyncio
    async def test_original_incoming_file_removed_on_success(self, tmp_path):
        """After processing, file must not remain in incoming/."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "signatories_bulk_20260709.csv.gz"
        test_file.write_bytes(b"fake gzip content")

        handler = _make_handler(tmp_path, processor=_make_processor(success=True))
        await handler.handle_new_file(test_file)

        assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_orphan_recovery_reprocesses_stranded_files(self, tmp_path):
        """Files stranded in processing/ at startup are re-processed."""
        processing_dir = tmp_path / "processing"
        processing_dir.mkdir(parents=True)
        # Orphan file from previous crashed session
        orphan = processing_dir / "signatories_bulk_20260708.csv.gz"
        orphan.write_bytes(b"orphan content")

        handler = _make_handler(tmp_path)
        await handler.recover_orphans()

        # After recovery the orphan should either be in processed/ or failed/
        # (not left in processing/)
        remaining = list(processing_dir.iterdir())
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_wait_stable_returns_when_size_stable(self, tmp_path):
        """_wait_stable should poll until size is unchanged for 2 consecutive checks."""
        test_file = tmp_path / "growing.csv.gz"
        test_file.write_bytes(b"x" * 100)

        handler = _make_handler(tmp_path)
        # File already has stable size — should return quickly
        start = time.monotonic()
        await handler._wait_stable(test_file, poll_interval=0.05)
        elapsed = time.monotonic() - start
        # Should not take more than 1 second for a stable file
        assert elapsed < 1.5

    @pytest.mark.asyncio
    async def test_wait_stable_polls_until_stable(self, tmp_path):
        """_wait_stable must detect size change and keep polling."""
        test_file = tmp_path / "growing.csv.gz"
        test_file.write_bytes(b"x" * 100)

        write_count = 0

        handler = _make_handler(tmp_path)

        # Patch asyncio.sleep so we can simulate growing file
        original_sleep = asyncio.sleep

        async def _growing_sleep(seconds):
            nonlocal write_count
            write_count += 1
            if write_count == 1:
                # First poll: grow the file
                test_file.write_bytes(b"x" * 200)
            await original_sleep(0.001)  # don't actually sleep long in test

        with patch("asyncio.sleep", side_effect=_growing_sleep):
            await handler._wait_stable(test_file, poll_interval=0.01)

        # Must have polled at least twice (once on growth, once on stability)
        assert write_count >= 2

    @pytest.mark.asyncio
    async def test_non_gz_files_ignored(self, tmp_path):
        """Non-gzipped files should be ignored without error."""
        incoming = tmp_path / "incoming"
        incoming.mkdir()
        test_file = incoming / "readme.txt"
        test_file.write_text("not a csv", encoding="utf-8")

        handler = _make_handler(tmp_path)
        # Should complete without error and not call processor
        await handler.handle_new_file(test_file)
        handler._processor.process_file.assert_not_called()
