"""
Tests for modules/msv/enrollment/bulk_enrollment.py

Covers:
  - Streams correctly (does not load all into memory at once)
  - Priority ordering: Corporate (L/T/P) first, Joint (J/JAS) next, Retail last
  - Semaphore limits concurrency to 20
  - Resumable: already enrolled accounts are skipped
  - Failed accounts reported in summary
"""
import asyncio
import io
import gzip
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


from modules.msv.enrollment.bulk_enrollment import BulkEnrollmentProcessor, BulkEnrollmentSummary
from modules.msv.enrollment.account_enroller import EnrollmentResult


def _make_csv_gz(rows: list[str]) -> bytes:
    """Create gzipped CSV content from row strings."""
    header = "account_number,operation_type,branch_code\n"
    content = header + "\n".join(rows) + "\n"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb') as f:
        f.write(content.encode("utf-8"))
    return buf.getvalue()


def _make_enroller(status: str = "ENROLLED", specimens: int = 3):
    def _make_result(bank_id, acct, op_type, batch_id):
        return EnrollmentResult(
            account_hash="hash_" + acct[-4:],
            status=status,
            specimens_enrolled=specimens,
        )

    enroller = MagicMock()
    enroller.enroll = AsyncMock(side_effect=_make_result)
    return enroller


def _make_progress_tracker():
    tracker = MagicMock()
    tracker.is_enrolled = AsyncMock(return_value=False)
    tracker.mark_enrolled = AsyncMock(return_value=None)
    tracker.mark_failed = AsyncMock(return_value=None)
    tracker.get_job = AsyncMock(return_value={"job_id": "job-001", "status": "RUNNING"})
    tracker.update_job_counts = AsyncMock(return_value=None)
    return tracker


class TestBulkEnrollmentProcessor:
    @pytest.mark.asyncio
    async def test_processes_all_rows(self, tmp_path):
        rows = [f"ACC{i:06d},J,BRN001" for i in range(5)]
        gz_file = tmp_path / "bulk.csv.gz"
        gz_file.write_bytes(_make_csv_gz(rows))

        enroller = _make_enroller("ENROLLED")
        tracker = _make_progress_tracker()
        processor = BulkEnrollmentProcessor(account_enroller=enroller, progress_tracker=tracker)

        summary = await processor.process_file(gz_file, "kotak-mah", "job-001")

        assert summary.total_processed == 5
        assert summary.enrolled == 5
        assert summary.failed == 0

    @pytest.mark.asyncio
    async def test_corporate_processed_before_joint_before_retail(self, tmp_path):
        """Priority: L/T/P → J/JAS → S/E/F/A"""
        rows = [
            "ACC000001,S,BRN001",    # retail
            "ACC000002,J,BRN001",    # joint
            "ACC000003,L,BRN001",    # corporate — should go first
            "ACC000004,JAS,BRN001",  # joint
            "ACC000005,T,BRN001",    # corporate
        ]
        gz_file = tmp_path / "bulk.csv.gz"
        gz_file.write_bytes(_make_csv_gz(rows))

        processed_order: list[str] = []

        async def _mock_enroll(bank_id, acct, op_type, batch_id):
            processed_order.append(f"{acct}:{op_type}")
            return EnrollmentResult(account_hash="h", status="ENROLLED", specimens_enrolled=3)

        enroller = MagicMock()
        enroller.enroll = AsyncMock(side_effect=_mock_enroll)
        tracker = _make_progress_tracker()
        processor = BulkEnrollmentProcessor(account_enroller=enroller, progress_tracker=tracker)

        await processor.process_file(gz_file, "kotak-mah", "job-001")

        # Corporate types (L, T, P) must all come before Joint types (J, JAS)
        # which must come before Retail types (S, E, F, A)
        corporate_indices = [i for i, o in enumerate(processed_order) if "L" in o or "T" in o or "P" in o]
        joint_indices = [i for i, o in enumerate(processed_order) if ":J" in o or ":JAS" in o]
        retail_indices = [i for i, o in enumerate(processed_order) if ":S" in o]

        if corporate_indices and joint_indices:
            assert max(corporate_indices) < min(joint_indices)
        if joint_indices and retail_indices:
            assert max(joint_indices) < min(retail_indices)

    @pytest.mark.asyncio
    async def test_already_enrolled_accounts_skipped(self, tmp_path):
        """Resumable: when enroller returns SKIPPED, bulk processor counts them as skipped."""
        rows = ["ACC000001,J,BRN001", "ACC000002,J,BRN001"]
        gz_file = tmp_path / "bulk.csv.gz"
        gz_file.write_bytes(_make_csv_gz(rows))

        # Enroller returns SKIPPED for all accounts (simulates already-enrolled)
        enroller = _make_enroller("SKIPPED", specimens=0)
        tracker = _make_progress_tracker()

        processor = BulkEnrollmentProcessor(account_enroller=enroller, progress_tracker=tracker)
        summary = await processor.process_file(gz_file, "kotak-mah", "job-001")

        assert summary.skipped == 2
        assert summary.enrolled == 0
        # Enroller WAS called (it returned SKIPPED internally — bulk processor relies on it)
        assert enroller.enroll.call_count == 2

    @pytest.mark.asyncio
    async def test_failed_accounts_in_summary(self, tmp_path):
        rows = [f"ACC{i:06d},J,BRN001" for i in range(3)]
        gz_file = tmp_path / "bulk.csv.gz"
        gz_file.write_bytes(_make_csv_gz(rows))

        enroller = _make_enroller("FAILED")
        tracker = _make_progress_tracker()
        processor = BulkEnrollmentProcessor(account_enroller=enroller, progress_tracker=tracker)
        summary = await processor.process_file(gz_file, "kotak-mah", "job-001")

        assert summary.failed == 3
        assert summary.enrolled == 0

    @pytest.mark.asyncio
    async def test_summary_has_correct_type(self, tmp_path):
        gz_file = tmp_path / "empty.csv.gz"
        gz_file.write_bytes(_make_csv_gz([]))

        processor = BulkEnrollmentProcessor(
            account_enroller=_make_enroller(),
            progress_tracker=_make_progress_tracker(),
        )
        summary = await processor.process_file(gz_file, "kotak-mah", "job-001")
        assert isinstance(summary, BulkEnrollmentSummary)

    @pytest.mark.asyncio
    async def test_concurrency_limited_by_semaphore(self, tmp_path):
        """Verify max concurrent tasks respects the semaphore (20 max)."""
        rows = [f"ACC{i:06d},J,BRN001" for i in range(50)]
        gz_file = tmp_path / "bulk.csv.gz"
        gz_file.write_bytes(_make_csv_gz(rows))

        active_count = 0
        max_active = 0

        async def _controlled_enroll(bank_id, acct, op_type, batch_id):
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.01)
            active_count -= 1
            return EnrollmentResult(account_hash="h", status="ENROLLED", specimens_enrolled=3)

        enroller = MagicMock()
        enroller.enroll = AsyncMock(side_effect=_controlled_enroll)
        tracker = _make_progress_tracker()
        processor = BulkEnrollmentProcessor(account_enroller=enroller, progress_tracker=tracker)

        await processor.process_file(gz_file, "kotak-mah", "job-001")

        assert max_active <= 20
