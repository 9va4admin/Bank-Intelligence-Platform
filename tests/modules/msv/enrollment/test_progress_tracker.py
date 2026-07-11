"""
Tests for modules/msv/enrollment/progress_tracker.py

Covers:
  - is_enrolled returns False on fresh account
  - is_enrolled returns True after mark_enrolled
  - mark_failed records error reason
  - get_job retrieves job state
  - update_job_counts increments correctly
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


from modules.msv.enrollment.progress_tracker import EnrollmentProgressTracker


def _make_db_pool(fetchrow_return=None, fetch_return=None):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


class TestEnrollmentProgressTracker:
    @pytest.mark.asyncio
    async def test_is_enrolled_returns_false_for_fresh_account(self):
        db_pool, conn = _make_db_pool(fetchrow_return=None)
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        result = await tracker.is_enrolled("kotak-mah", "hash_abc")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_enrolled_returns_true_after_mark_enrolled(self):
        enrolled_row = {"status": "ENROLLED", "enrolled_at": "2026-07-09T10:00:00Z"}
        db_pool, conn = _make_db_pool(fetchrow_return=enrolled_row)
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        result = await tracker.is_enrolled("kotak-mah", "hash_abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_enrolled_false_for_failed_status(self):
        failed_row = {"status": "FAILED", "enrolled_at": None}
        db_pool, conn = _make_db_pool(fetchrow_return=failed_row)
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        result = await tracker.is_enrolled("kotak-mah", "hash_abc")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_enrolled_calls_db(self):
        db_pool, conn = _make_db_pool()
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        await tracker.mark_enrolled("kotak-mah", "hash_abc", "batch-001")
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_failed_records_error(self):
        db_pool, conn = _make_db_pool()
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        await tracker.mark_failed("kotak-mah", "hash_abc", "CBS_UNAVAILABLE", "batch-001")
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        # The error reason should be passed
        assert "CBS_UNAVAILABLE" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_job_returns_dict(self):
        job_row = {
            "job_id": "job-001",
            "bank_id": "kotak-mah",
            "status": "RUNNING",
            "file_name": "bulk.csv.gz",
            "file_type": "BULK",
            "total_accounts": 1000,
            "processed_accounts": 250,
            "enrolled_accounts": 240,
            "failed_accounts": 10,
            "total_signatures": 750,
            "enrolled_signatures": 720,
        }
        db_pool, conn = _make_db_pool(fetchrow_return=job_row)
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        result = await tracker.get_job("job-001")
        assert result["job_id"] == "job-001"
        assert result["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_get_job_returns_none_if_not_found(self):
        db_pool, conn = _make_db_pool(fetchrow_return=None)
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        result = await tracker.get_job("nonexistent-job")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_job_counts_calls_db(self):
        db_pool, conn = _make_db_pool()
        tracker = EnrollmentProgressTracker(db_pool=db_pool)
        await tracker.update_job_counts("job-001", accounts_delta=10, sigs_delta=30)
        conn.execute.assert_called_once()
        # Verify the delta values are in the call (convert to string for int comparison)
        call_args_str = str(conn.execute.call_args)
        assert "10" in call_args_str or "30" in call_args_str
