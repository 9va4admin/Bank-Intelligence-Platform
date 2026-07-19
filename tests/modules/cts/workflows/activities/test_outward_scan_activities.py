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


# ---------------------------------------------------------------------------
# vision_extract_and_check  (CR-120 single-pass Qwen2-VL path)
# ---------------------------------------------------------------------------

def _make_vision_orchestrator(payload: dict):
    """Build a mock CascadeOrchestrator whose call_vision() returns JSON payload."""
    import json
    orch = MagicMock()
    cascade_result = MagicMock(content=json.dumps(payload), cascade_level=1)
    orch.call_vision = AsyncMock(return_value=cascade_result)
    return orch


def _clean_payload(
    *,
    amount_figures: str = "45000.00",
    amount_words: str = "Forty Five Thousand",
    confidence: float = 0.95,
    alteration_detected: bool = False,
    alteration_risk: float = 0.02,
    micr_visual: str | None = None,
    micr_matches_hardware: bool = True,
) -> dict:
    """Build a typical all-clear model response payload."""
    payload: dict = {
        "amount_figures": {"value": amount_figures, "confidence": confidence, "altered": False},
        "amount_words":   {"value": amount_words,   "confidence": confidence, "altered": False},
        "payee":          {"value": "RAMESH KUMAR",  "confidence": confidence, "altered": False},
        "date":           {"value": "2026-07-15",    "confidence": confidence, "altered": False},
        "alteration_detected": alteration_detected,
        "alteration_risk": alteration_risk,
        "tampered_fields": [],
    }
    if micr_visual is not None:
        payload["micr_visual"] = micr_visual
        payload["micr_matches_hardware"] = micr_matches_hardware
    return payload


def _make_config(min_confidence: float = 0.85, alteration_threshold: float = 0.60):
    cfg = MagicMock()
    # get_ai_config is async — must be AsyncMock
    cfg.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": min_confidence,
        "ai.alteration.risk_threshold": alteration_threshold,
    })
    return cfg


class TestVisionExtractAndCheck:
    @pytest.mark.asyncio
    async def test_proceed_clean_cheque(self):
        """All-clear: high confidence, no alteration, matching amounts → PROCEED."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        orch = _make_vision_orchestrator(_clean_payload())
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-001", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.amount_figures == "45000.00"
        assert result.alteration_detected is False
        assert result.micr_validated is False   # no hardware MICR provided

    @pytest.mark.asyncio
    async def test_proceed_with_hardware_micr_validated(self):
        """CR-120 path: hardware MICR matches visual MICR → PROCEED, micr_validated=True."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        orch = _make_vision_orchestrator(_clean_payload(
            micr_visual="000100001234  45000 123456789",
            micr_matches_hardware=True,
        ))
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-002", image_front_url="minio://front.tiff", bank_id="test-bank",
                micr_hardware_raw="000100001234  45000 123456789",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.micr_validated is True
        assert result.micr_mismatch is False

    @pytest.mark.asyncio
    async def test_human_review_low_confidence_field(self):
        """One field below min_confidence threshold → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload()
        payload["amount_figures"]["confidence"] = 0.70   # below 0.85 threshold
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-003", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(min_confidence=0.85),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is False   # model responded — this is not a degraded path

    @pytest.mark.asyncio
    async def test_human_review_alteration_detected(self):
        """alteration_detected=True in model response → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload(alteration_detected=True, alteration_risk=0.85)
        payload["tampered_fields"] = ["amount_figures"]
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-004", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.alteration_detected is True

    @pytest.mark.asyncio
    async def test_human_review_high_alteration_risk_even_without_flag(self):
        """alteration_risk >= threshold with alteration_detected=False still routes to HUMAN_REVIEW."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload(alteration_detected=False, alteration_risk=0.75)
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-005", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(alteration_threshold=0.60),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.alteration_detected is True   # activity sets True when risk >= threshold

    @pytest.mark.asyncio
    async def test_human_review_micr_mismatch(self):
        """Visual MICR doesn't match hardware MICR → HUMAN_REVIEW, micr_mismatch=True."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload(
            micr_visual="000100009999  45000 123456789",   # different account digits
            micr_matches_hardware=False,
        )
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-006", image_front_url="minio://front.tiff", bank_id="test-bank",
                micr_hardware_raw="000100001234  45000 123456789",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.micr_mismatch is True
        assert result.micr_validated is True

    @pytest.mark.asyncio
    async def test_mismatch_amount_figures_vs_words(self):
        """amount_figures and amount_words carry different values → MISMATCH."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload(
            amount_figures="45000.00",
            amount_words="Four Thousand Five Hundred",   # clearly different amount
        )
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-007", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "MISMATCH"
        assert "amount_figures" in result.mismatch_fields
        assert "amount_words" in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_human_review_model_unavailable(self):
        """vLLM down → orchestrator raises → graceful degradation HUMAN_REVIEW, degraded=True."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        orch = MagicMock()
        orch.call_vision = AsyncMock(side_effect=RuntimeError("vLLM unavailable"))
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-008", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_no_micr_validation_when_no_hardware_micr_provided(self):
        """Without micr_hardware_raw, micr_validated must remain False even if model returns micr_visual."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        payload = _clean_payload(micr_visual="somevalue", micr_matches_hardware=True)
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-009", image_front_url="minio://front.tiff", bank_id="test-bank",
                micr_hardware_raw=None,   # explicitly absent
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.micr_validated is False   # no hardware MICR to validate against

    @pytest.mark.asyncio
    async def test_thresholds_come_from_config_not_hardcoded(self):
        """Bank-specific thresholds must be read from config_service, not hardcoded."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        # Use a non-default threshold (0.99) — would catch fields at 0.95 if correctly applied
        cfg = _make_config(min_confidence=0.99)
        payload = _clean_payload(confidence=0.96)   # high but below 0.99 custom threshold
        orch = _make_vision_orchestrator(payload)
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-010", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=cfg,
        )
        # If hardcoded 0.85 were used, outcome would be PROCEED.
        # If config_service 0.99 is correctly applied, outcome must be HUMAN_REVIEW.
        assert result.outcome == "HUMAN_REVIEW", (
            "threshold must come from config_service, not hardcoded — "
            "0.96 confidence should fail at 0.99 threshold"
        )

    @pytest.mark.asyncio
    async def test_all_fields_present_in_proceed_result(self):
        """PROCEED result must populate all extracted field values."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        orch = _make_vision_orchestrator(_clean_payload())
        result = await vision_extract_and_check(
            VisionExtractAndCheckInput(
                instrument_id="OUT-011", image_front_url="minio://front.tiff", bank_id="test-bank",
            ),
            orchestrator=orch,
            config_service=_make_config(),
        )
        assert result.outcome == "PROCEED"
        assert result.amount_figures is not None
        assert result.amount_words is not None
        assert result.payee is not None
        assert result.date is not None
        assert result.overall_confidence > 0.0
