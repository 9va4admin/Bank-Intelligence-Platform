"""Tests for modules/cts/workflows/activities/outward_scan_activities.py"""
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# validate_cts2010
# ---------------------------------------------------------------------------

def _compliant_metrics(**overrides) -> dict:
    defaults = dict(
        front_dpi=203, rear_dpi=203,
        front_colour_depth=24, rear_colour_depth=24,
        front_file_size_kb=40.0, rear_file_size_kb=30.0,
        front_iqa_score=0.95, rear_iqa_score=0.92,
        micr_band_score=0.90,
    )
    defaults.update(overrides)
    return defaults


class TestValidateCTS2010:
    @pytest.mark.asyncio
    async def test_compliant_image_passes(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-001", cheque_number="000123", **_compliant_metrics(),
        ))
        assert result.is_compliant is True
        assert result.violations == []

    @pytest.mark.asyncio
    async def test_low_dpi_fails(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-002", cheque_number="000124",
            **_compliant_metrics(front_dpi=100),
        ))
        assert result.is_compliant is False
        assert "front_dpi" in result.violations

    @pytest.mark.asyncio
    async def test_low_micr_band_score_fails(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-003", cheque_number="000125",
            **_compliant_metrics(micr_band_score=0.5),
        ))
        assert result.is_compliant is False
        assert "micr_band_score" in result.violations

    @pytest.mark.asyncio
    async def test_oversized_file_fails(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-004", cheque_number="000126",
            **_compliant_metrics(front_file_size_kb=200.0),
        ))
        assert result.is_compliant is False
        assert "front_file_size_kb" in result.violations

    @pytest.mark.asyncio
    async def test_missing_metrics_fails_closed_not_open(self):
        """Missing image metrics must never silently pass — fail closed."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-005", cheque_number="000127",
        ))
        assert result.is_compliant is False
        assert result.violations == ["MISSING_IMAGE_METRICS"]

    @pytest.mark.asyncio
    async def test_partially_missing_metrics_also_fails_closed(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        metrics = _compliant_metrics()
        metrics.pop("micr_band_score")
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-006", cheque_number="000128", **metrics,
        ))
        assert result.is_compliant is False
        assert result.violations == ["MISSING_IMAGE_METRICS"]

    @pytest.mark.asyncio
    async def test_multiple_violations_all_reported(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
        )
        result = await validate_cts2010(CTS2010ValidationInput(
            instrument_id="OUT-007", cheque_number="000129",
            **_compliant_metrics(front_dpi=100, rear_dpi=100, front_colour_depth=8),
        ))
        assert set(result.violations) >= {"front_dpi", "rear_dpi", "front_colour_depth"}


# ---------------------------------------------------------------------------
# create_lot_entry
# ---------------------------------------------------------------------------

class TestCreateLotEntry:
    @pytest.mark.asyncio
    async def test_assigns_to_new_lot(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            create_lot_entry, LotAssignmentInput,
        )
        from modules.cts.lot.manager import LotManager
        import datetime

        mgr = LotManager(bank_ifsc="SVCB0000001", session_id="SES-001", session_date=datetime.datetime(2026, 7, 14))
        result = await create_lot_entry(LotAssignmentInput(instrument_id="OUT-001"), lot_manager=mgr)
        assert result.lot_number.startswith("LOT_SVCB0000001_")

    @pytest.mark.asyncio
    async def test_second_instrument_joins_same_lot_until_full(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            create_lot_entry, LotAssignmentInput,
        )
        from modules.cts.lot.manager import LotManager
        import datetime

        mgr = LotManager(bank_ifsc="SVCB0000001", session_id="SES-001", session_date=datetime.datetime(2026, 7, 14))
        r1 = await create_lot_entry(LotAssignmentInput(instrument_id="OUT-001"), lot_manager=mgr)
        r2 = await create_lot_entry(LotAssignmentInput(instrument_id="OUT-002"), lot_manager=mgr)
        assert r1.lot_number == r2.lot_number

    @pytest.mark.asyncio
    async def test_lot_rolls_over_when_full(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            create_lot_entry, LotAssignmentInput,
        )
        from modules.cts.lot.manager import LotManager
        import datetime

        mgr = LotManager(
            bank_ifsc="SVCB0000001", session_id="SES-001",
            session_date=datetime.datetime(2026, 7, 14), max_instruments_per_lot=1,
        )
        r1 = await create_lot_entry(LotAssignmentInput(instrument_id="OUT-001"), lot_manager=mgr)
        r2 = await create_lot_entry(LotAssignmentInput(instrument_id="OUT-002"), lot_manager=mgr)
        assert r1.lot_number != r2.lot_number


# ---------------------------------------------------------------------------
# run_vision_presentment_check
# ---------------------------------------------------------------------------

def _make_orchestrator(vision_amount: str | None):
    import json
    orch = MagicMock()
    if vision_amount is None:
        content = json.dumps({"amount_figures": None})
    else:
        content = json.dumps({"amount_figures": vision_amount})
    cascade_result = MagicMock(content=content, cascade_level=1)
    orch.call_vision = AsyncMock(return_value=cascade_result)
    return orch


class TestRunVisionPresentmentCheck:
    @pytest.mark.asyncio
    async def test_matching_amounts_no_mismatch(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            run_vision_presentment_check, VisionPresentmentCheckInput,
        )
        orch = _make_orchestrator("45000.00")
        result = await run_vision_presentment_check(
            VisionPresentmentCheckInput(
                instrument_id="OUT-001", image_front_url="minio://front.tiff",
                scanner_amount_str="45000.00", cheque_amount=45000.0, bank_id="test-bank",
            ),
            orchestrator=orch,
        )
        assert result.has_mismatch is False
        assert result.mismatch_fields == []

    @pytest.mark.asyncio
    async def test_differing_amounts_produces_mismatch(self):
        from modules.cts.workflows.activities.outward_scan_activities import (
            run_vision_presentment_check, VisionPresentmentCheckInput,
        )
        orch = _make_orchestrator("4500.00")
        result = await run_vision_presentment_check(
            VisionPresentmentCheckInput(
                instrument_id="OUT-002", image_front_url="minio://front.tiff",
                scanner_amount_str="45000.00", cheque_amount=45000.0, bank_id="test-bank",
            ),
            orchestrator=orch,
        )
        assert result.has_mismatch is True
        assert result.mismatch_fields == ["amount_figures"]
        assert result.vision_amount_str == "4500.00"

    @pytest.mark.asyncio
    async def test_within_tolerance_no_mismatch(self):
        """Sub-paisa rounding differences must not trigger a mismatch hold."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            run_vision_presentment_check, VisionPresentmentCheckInput,
        )
        orch = _make_orchestrator("45000.005")
        result = await run_vision_presentment_check(
            VisionPresentmentCheckInput(
                instrument_id="OUT-003", image_front_url="minio://front.tiff",
                scanner_amount_str="45000.00", cheque_amount=45000.0, bank_id="test-bank",
            ),
            orchestrator=orch,
        )
        assert result.has_mismatch is False

    @pytest.mark.asyncio
    async def test_vision_unreadable_degrades_to_no_mismatch(self):
        """Vision failing to read the amount is not the same as a confirmed
        mismatch — scanner stays authoritative for presentment."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            run_vision_presentment_check, VisionPresentmentCheckInput,
        )
        orch = _make_orchestrator(None)
        result = await run_vision_presentment_check(
            VisionPresentmentCheckInput(
                instrument_id="OUT-004", image_front_url="minio://front.tiff",
                scanner_amount_str="45000.00", cheque_amount=45000.0, bank_id="test-bank",
            ),
            orchestrator=orch,
        )
        assert result.has_mismatch is False
        assert result.vision_amount_str is None
