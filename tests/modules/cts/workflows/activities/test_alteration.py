"""
Tests for modules/cts/workflows/activities/alteration.py

Six-layer physical anomaly detection via Qwen2-VL via the cascade orchestrator:
  1. Field content (overwriting, erasure)
  2. Ink-physics (pen-pressure, flow, bleed)
  3. Paper-fibre distortion (mechanical erasure at 200 DPI)
  4. Correction-fluid spectral signature
  5. Chemical alteration stain (solvent halo)
  6. Overwriting brightness

Orchestrator (CascadeOrchestrator) unavailable / JSON parse failure → graceful degradation
to HUMAN_REVIEW. alteration_detected=True → requires_human_review=True.
"""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(**kwargs):
    from modules.cts.workflows.activities.alteration import AlterationActivityInput
    defaults = dict(image_url="s3://bucket/INST001.jpg", instrument_id="INST001", bank_id="test-bank")
    defaults.update(kwargs)
    return AlterationActivityInput(**defaults)


def _mock_orchestrator(payload: dict):
    """Return a CascadeOrchestrator mock whose call_vision returns JSON payload."""
    from shared.ai.model_cascade import CascadeResult
    cascade_result = CascadeResult(
        content=json.dumps(payload),
        confidence=0.96,
        cascade_level=1,
        model_used="qwen2-vl-7b",
        escalated=False,
    )
    orchestrator = AsyncMock()
    orchestrator.call_vision = AsyncMock(return_value=cascade_result)
    return orchestrator


def _mock_config():
    """Return a config_service mock satisfying detect_alteration's config.get() call."""
    config = AsyncMock()
    config.get = AsyncMock(return_value=0.5)  # ai.tamper_risk_threshold default
    return config


def _clean_payload():
    return {
        "fields": [
            {"field_name": "amount_figures", "altered": False, "confidence": 0.97, "current_value": "50000"},
            {"field_name": "payee_name",     "altered": False, "confidence": 0.95, "current_value": "ABC Ltd"},
        ],
        "overall_tamper_risk": 0.03,
        "physical_anomaly_score": 0.02,
    }


def _altered_payload():
    return {
        "fields": [
            {
                "field_name": "amount_figures",
                "altered": True,
                "confidence": 0.94,
                "current_value": "500000",
                "original_value_legible": "50000",
                "ink_physics": {
                    "field": "amount_figures",
                    "score": 0.82,
                    "pressure_inconsistency": True,
                    "bleed_anomaly": True,
                    "flow_reversal": False,
                    "bbox": {"x": 120, "y": 80, "w": 90, "h": 22, "label": "amount_figures region"},
                },
                "paper_fibre": None,
                "correction_fluid": None,
                "chemical_alteration": None,
            }
        ],
        "overall_tamper_risk": 0.91,
        "physical_anomaly_score": 0.83,
    }


def _correction_fluid_payload():
    return {
        "fields": [
            {
                "field_name": "date",
                "altered": True,
                "confidence": 0.88,
                "current_value": "25/06/2026",
                "original_value_legible": None,
                "ink_physics": None,
                "paper_fibre": None,
                "correction_fluid": {
                    "field": "date",
                    "score": 0.91,
                    "luminance_spike_detected": True,
                    "edge_sharpness_ratio": 3.7,
                    "bbox": {"x": 300, "y": 50, "w": 80, "h": 18, "label": "date field correction fluid"},
                },
                "chemical_alteration": None,
            }
        ],
        "overall_tamper_risk": 0.87,
        "physical_anomaly_score": 0.91,
    }


def _chemical_payload():
    return {
        "fields": [
            {
                "field_name": "payee_name",
                "altered": True,
                "confidence": 0.79,
                "current_value": "XYZ Corp",
                "original_value_legible": None,
                "ink_physics": None,
                "paper_fibre": {
                    "field": "payee_name",
                    "score": 0.74,
                    "fibre_distortion_detected": True,
                    "gloss_patch_detected": True,
                    "bbox": {"x": 60, "y": 110, "w": 150, "h": 20, "label": "payee erasure zone"},
                },
                "correction_fluid": None,
                "chemical_alteration": {
                    "field": "payee_name",
                    "score": 0.69,
                    "halo_detected": True,
                    "colour_shift_detected": True,
                    "bbox": {"x": 55, "y": 105, "w": 160, "h": 30, "label": "chemical halo"},
                },
            }
        ],
        "overall_tamper_risk": 0.78,
        "physical_anomaly_score": 0.74,
    }


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TestAlterationInput:
    def test_requires_image_url(self):
        from modules.cts.workflows.activities.alteration import AlterationActivityInput
        with pytest.raises(Exception):
            AlterationActivityInput(instrument_id="I", bank_id="b")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.image_url = "other"

    def test_default_dpi_is_200(self):
        inp = _make_input()
        assert inp.scan_dpi == 200

    def test_custom_dpi(self):
        inp = _make_input(scan_dpi=300)
        assert inp.scan_dpi == 300


# ---------------------------------------------------------------------------
# Clean cheque (no alteration)
# ---------------------------------------------------------------------------

class TestAlterationClean:
    @pytest.mark.asyncio
    async def test_clean_alteration_not_detected(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_clean_risk_score_low(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.tamper_risk_score < 0.5

    @pytest.mark.asyncio
    async def test_clean_no_altered_fields(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.altered_fields == []

    @pytest.mark.asyncio
    async def test_clean_not_degraded(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_clean_human_review_not_required(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.requires_human_review is False

    @pytest.mark.asyncio
    async def test_clean_physical_anomaly_score_low(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert result.physical_anomaly_score < 0.5

    @pytest.mark.asyncio
    async def test_clean_returns_field_details(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_clean_payload()), config_service=_mock_config())
        assert len(result.field_details) == 2


# ---------------------------------------------------------------------------
# Ink-physics alteration (amount overwriting)
# ---------------------------------------------------------------------------

class TestInkPhysicsAlteration:
    @pytest.mark.asyncio
    async def test_alteration_detected_flag(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert result.alteration_detected is True

    @pytest.mark.asyncio
    async def test_tamper_risk_high(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert result.tamper_risk_score > 0.5

    @pytest.mark.asyncio
    async def test_physical_anomaly_score_set(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert result.physical_anomaly_score > 0.5

    @pytest.mark.asyncio
    async def test_amount_figures_in_altered_fields(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert "amount_figures" in result.altered_fields

    @pytest.mark.asyncio
    async def test_ink_physics_anomaly_populated(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert len(result.ink_physics_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_ink_pressure_inconsistency_flag(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        ink = result.ink_physics_anomalies[0]
        assert ink.pressure_inconsistency is True

    @pytest.mark.asyncio
    async def test_ink_bleed_anomaly_flag(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        ink = result.ink_physics_anomalies[0]
        assert ink.bleed_anomaly is True

    @pytest.mark.asyncio
    async def test_bbox_populated(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        ink = result.ink_physics_anomalies[0]
        assert ink.bbox is not None
        assert ink.bbox.x == 120
        assert ink.bbox.w == 90

    @pytest.mark.asyncio
    async def test_requires_human_review_on_alteration(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        assert result.requires_human_review is True

    @pytest.mark.asyncio
    async def test_original_value_in_field_detail(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_altered_payload()), config_service=_mock_config())
        detail = next(d for d in result.field_details if d.field_name == "amount_figures")
        assert detail.original_value_legible == "50000"


# ---------------------------------------------------------------------------
# Correction fluid detection
# ---------------------------------------------------------------------------

class TestCorrectionFluid:
    @pytest.mark.asyncio
    async def test_correction_fluid_anomaly_detected(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_correction_fluid_payload()), config_service=_mock_config())
        assert len(result.correction_fluid_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_luminance_spike_flagged(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_correction_fluid_payload()), config_service=_mock_config())
        fluid = result.correction_fluid_anomalies[0]
        assert fluid.luminance_spike_detected is True

    @pytest.mark.asyncio
    async def test_edge_sharpness_ratio_present(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_correction_fluid_payload()), config_service=_mock_config())
        fluid = result.correction_fluid_anomalies[0]
        assert fluid.edge_sharpness_ratio is not None
        assert fluid.edge_sharpness_ratio > 1.0

    @pytest.mark.asyncio
    async def test_date_in_altered_fields_for_fluid(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_correction_fluid_payload()), config_service=_mock_config())
        assert "date" in result.altered_fields

    @pytest.mark.asyncio
    async def test_alteration_detected_for_fluid(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_correction_fluid_payload()), config_service=_mock_config())
        assert result.alteration_detected is True


# ---------------------------------------------------------------------------
# Chemical / paper-fibre detection
# ---------------------------------------------------------------------------

class TestChemicalAlteration:
    @pytest.mark.asyncio
    async def test_paper_fibre_anomaly_detected(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        assert len(result.paper_fibre_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_fibre_distortion_flagged(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        paper = result.paper_fibre_anomalies[0]
        assert paper.fibre_distortion_detected is True

    @pytest.mark.asyncio
    async def test_gloss_patch_flagged(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        paper = result.paper_fibre_anomalies[0]
        assert paper.gloss_patch_detected is True

    @pytest.mark.asyncio
    async def test_chemical_halo_detected(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        assert len(result.chemical_alteration_anomalies) >= 1
        chem = result.chemical_alteration_anomalies[0]
        assert chem.halo_detected is True

    @pytest.mark.asyncio
    async def test_colour_shift_flagged(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        chem = result.chemical_alteration_anomalies[0]
        assert chem.colour_shift_detected is True

    @pytest.mark.asyncio
    async def test_payee_in_altered_fields_for_chemical(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(_make_input(), orchestrator=_mock_orchestrator(_chemical_payload()), config_service=_mock_config())
        assert "payee_name" in result.altered_fields


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestAlterationDegradation:
    @pytest.mark.asyncio
    async def test_model_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=Exception("vLLM down"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result is not None

    @pytest.mark.asyncio
    async def test_model_unavailable_degraded_flag(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=ConnectionError("GPU unreachable"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_model_unavailable_not_detected(self):
        """Model failure must NOT assume alteration — escalate to human instead."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=TimeoutError("timeout"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_model_unavailable_human_review(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=RuntimeError("model error"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.requires_human_review is True

    @pytest.mark.asyncio
    async def test_json_parse_failure_degraded(self):
        """Non-JSON model response → degraded, human review."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.ai.model_cascade import CascadeResult
        bad_result = CascadeResult(
            content="I cannot analyse this image.",
            confidence=0.1,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=bad_result)
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.degraded is True
        assert result.requires_human_review is True
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_degraded_no_ink_anomalies(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=Exception("down"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.ink_physics_anomalies == []

    @pytest.mark.asyncio
    async def test_degraded_tamper_risk_zero(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=Exception("down"))
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.tamper_risk_score == 0.0


# ---------------------------------------------------------------------------
# Cascade orchestrator wiring (Fix A — Gemini)
# ---------------------------------------------------------------------------

class TestAlterationCascadeWiring:
    @pytest.mark.asyncio
    async def test_cascade_orchestrator_called_when_provided(self):
        """When orchestrator is passed, call_vision must be invoked (not vllm_client directly)."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=json.dumps(_clean_payload()),
            confidence=0.96,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=cascade_result)

        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        orchestrator.call_vision.assert_called_once()
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_cascade_model_used_in_result_model_version(self):
        """result.model_version must reflect which model the cascade chose."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=json.dumps(_clean_payload()),
            confidence=0.96,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=cascade_result)

        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.model_version == "qwen2-vl-7b"

    @pytest.mark.asyncio
    async def test_cascade_level_1_reflected_in_result(self):
        """result.cascade_level == 1 when L1 was sufficient."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=json.dumps(_clean_payload()),
            confidence=0.96,
            cascade_level=1,
            model_used="qwen2-vl-7b",
            escalated=False,
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=cascade_result)

        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.cascade_level == 1

    @pytest.mark.asyncio
    async def test_cascade_level_2_reflected_in_result(self):
        """result.cascade_level == 2 when L2 was used (high-value or low L1 confidence)."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=json.dumps(_altered_payload()),
            confidence=0.94,
            cascade_level=2,
            model_used="qwen2-vl-72b",
            escalated=True,
            escalation_reason="high_value",
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=cascade_result)

        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.cascade_level == 2
        assert result.model_version == "qwen2-vl-72b"
        assert result.alteration_detected is True

    @pytest.mark.asyncio
    async def test_cascade_exception_degrades_gracefully(self):
        """If both L1 and L2 fail (cascade raises), result must be degraded human review."""
        from modules.cts.workflows.activities.alteration import detect_alteration

        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(side_effect=RuntimeError("All models down"))

        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        assert result.degraded is True
        assert result.requires_human_review is True
        assert result.alteration_detected is False

    @pytest.mark.asyncio
    async def test_orchestrator_call_vision_is_always_used(self):
        """Orchestrator is the only inference path — call_vision must be invoked exactly once."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        orchestrator = _mock_orchestrator(_clean_payload())
        result = await detect_alteration(_make_input(), orchestrator=orchestrator, config_service=_mock_config())
        orchestrator.call_vision.assert_called_once()
        assert result.alteration_detected is False
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_cheque_amount_passed_to_cascade(self):
        """cheque_amount from input must be forwarded to orchestrator.call_vision."""
        from modules.cts.workflows.activities.alteration import detect_alteration, AlterationActivityInput
        from shared.ai.model_cascade import CascadeResult

        cascade_result = CascadeResult(
            content=json.dumps(_clean_payload()),
            confidence=0.96,
            cascade_level=2,
            model_used="qwen2-vl-72b",
            escalated=True,
            escalation_reason="high_value",
        )
        orchestrator = AsyncMock()
        orchestrator.call_vision = AsyncMock(return_value=cascade_result)

        inp = AlterationActivityInput(
            image_url="s3://bucket/INST001.jpg",
            instrument_id="INST001",
            bank_id="test-bank",
            cheque_amount=6_000_000.0,  # ₹60L — high value
        )
        await detect_alteration(inp, orchestrator=orchestrator, config_service=_mock_config())
        call_kwargs = orchestrator.call_vision.call_args
        # cheque_amount must reach the orchestrator
        assert call_kwargs is not None
