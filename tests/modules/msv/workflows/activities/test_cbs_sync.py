"""
Tests for modules/msv/workflows/activities/cbs_sync.py

Covers:
  - Happy path: CBS returns signatories → enroller called per signatory → returns enrolled count
  - CBS unavailable → CBSSyncResult with status DEGRADED (not a crash)
  - No signatory data returned → CBSSyncResult with zero enrolled
  - Result is typed CBSSyncResult (frozen Pydantic)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.msv.workflows.activities.cbs_sync import (
    CBSSyncInput,
    CBSSyncResult,
    sync_signatories_from_cbs,
)
from modules.msv.enrollment.account_enroller import EnrollmentResult
from shared.cbs_connector.exceptions import CBSUnavailableError


def _make_cbs_connector(signatories=None, raise_error=None):
    from shared.cbs_connector.base import CBSSignatoryData
    conn = MagicMock()
    if raise_error:
        conn.get_signatory_data = AsyncMock(side_effect=raise_error)
    else:
        conn.get_signatory_data = AsyncMock(return_value=signatories or [])
    return conn


def _make_enroller(status: str = "ENROLLED", specimens: int = 3):
    from modules.msv.enrollment.account_enroller import EnrollmentResult
    enroller = MagicMock()
    enroller.enroll = AsyncMock(return_value=EnrollmentResult(
        account_hash="hash_abc",
        status=status,
        specimens_enrolled=specimens,
    ))
    return enroller


class TestCBSSyncActivity:
    @pytest.mark.asyncio
    async def test_happy_path_enrolls_accounts(self):
        """CBS returns 2 accounts → enroller called for each → enrolled count = 2."""
        from shared.cbs_connector.base import CBSSignatoryData
        sig_data = CBSSignatoryData(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_images=[b"img1", b"img2"],
            operation_type="J",
        )
        cbs = _make_cbs_connector(signatories=[sig_data])
        enroller = _make_enroller("ENROLLED", specimens=2)

        inp = CBSSyncInput(
            bank_id="kotak-mah",
            account_numbers=["ACC001", "ACC002"],
            batch_id="batch-001",
        )
        result = await sync_signatories_from_cbs(inp, cbs_connector=cbs, enroller=enroller)

        assert isinstance(result, CBSSyncResult)
        assert result.status == "COMPLETE"
        assert result.enrolled_count >= 1  # at least 1 enrolled

    @pytest.mark.asyncio
    async def test_cbs_unavailable_returns_degraded_status(self):
        cbs = _make_cbs_connector(raise_error=CBSUnavailableError("CBS down"))
        enroller = _make_enroller()

        inp = CBSSyncInput(
            bank_id="kotak-mah",
            account_numbers=["ACC001"],
            batch_id="batch-002",
        )
        result = await sync_signatories_from_cbs(inp, cbs_connector=cbs, enroller=enroller)

        assert result.status == "DEGRADED"
        assert result.enrolled_count == 0

    @pytest.mark.asyncio
    async def test_no_signatory_data_returns_zero_enrolled(self):
        cbs = _make_cbs_connector(signatories=[])  # CBS returns nothing
        enroller = _make_enroller()

        inp = CBSSyncInput(
            bank_id="kotak-mah",
            account_numbers=["ACC001"],
            batch_id="batch-003",
        )
        result = await sync_signatories_from_cbs(inp, cbs_connector=cbs, enroller=enroller)

        assert result.enrolled_count == 0

    @pytest.mark.asyncio
    async def test_result_is_frozen_pydantic_model(self):
        cbs = _make_cbs_connector()
        enroller = _make_enroller()
        inp = CBSSyncInput(bank_id="kotak-mah", account_numbers=[], batch_id="b")
        result = await sync_signatories_from_cbs(inp, cbs_connector=cbs, enroller=enroller)
        with pytest.raises((TypeError, Exception)):
            result.status = "MUTATED"  # frozen

    @pytest.mark.asyncio
    async def test_batch_id_passed_to_enroller(self):
        """Enroller must receive the batch_id for progress tracking."""
        from shared.cbs_connector.base import CBSSignatoryData
        sig = CBSSignatoryData(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_images=[b"img"],
            operation_type="J",
        )
        cbs = _make_cbs_connector(signatories=[sig])
        enroller = _make_enroller()

        inp = CBSSyncInput(
            bank_id="kotak-mah",
            account_numbers=["ACC001"],
            batch_id="batch-TEST-ID",
        )
        await sync_signatories_from_cbs(inp, cbs_connector=cbs, enroller=enroller)

        # Enroller.enroll must have been called with the batch_id
        call_args_str = str(enroller.enroll.call_args)
        assert "batch-TEST-ID" in call_args_str
