"""
TDD — UV security analysis activity.

RED step: all tests fail until modules/cts/workflows/activities/uv_security.py
is implemented.

UV scanner produces a UV-wavelength image that reveals three security features
invisible under normal light:
  1. Pentograph (pantograph) — background security pattern; reveals VOID/COPY
     if photocopied; authenticated by UV-ink response pattern
  2. Security thread — embedded plastic/metallic strip in paper; shows as
     bright fluorescent line (UV-reactive) or dark stripe (metallic)
  3. UV watermark — bank-specific ghost image in paper manufacturing; only
     visible under UV light

All three must pass for UV_SECURITY_PASSED=True.
Missing UV image → degraded=True, requires_human_review=True (cannot fail
what wasn't captured, but cannot certify either).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── import guard ────────────────────────────────────────────────────────────

def _import():
    from modules.cts.workflows.activities.uv_security import (
        UVSecurityInput,
        UVSecurityResult,
        analyze_uv_security,
    )
    return UVSecurityInput, UVSecurityResult, analyze_uv_security


# ── model tests ─────────────────────────────────────────────────────────────

def test_uv_security_input_importable():
    UVSecurityInput, _, _ = _import()
    inp = UVSecurityInput(
        instrument_id="CTS-KBL-TEST-001",
        bank_id="kbl",
        uv_image_url="minio://cts-cheques/kbl/outward/SCAN-001/uv.tif",
    )
    assert inp.instrument_id == "CTS-KBL-TEST-001"
    assert inp.cheque_amount == 0.0   # default


def test_uv_security_result_defaults():
    _, UVSecurityResult, _ = _import()
    r = UVSecurityResult()
    assert r.pentograph_authentic is False
    assert r.security_thread_present is False
    assert r.uv_watermark_present is False
    assert r.uv_security_passed is False
    assert r.uv_risk_score == 0.0
    assert r.degraded is False
    assert r.requires_human_review is False


# ── activity — all three checks pass ────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_three_checks_pass_returns_passed():
    UVSecurityInput, UVSecurityResult, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": True, "confidence": 0.96,
                       "notes": "UV-reactive ink pattern consistent with genuine security print"},
        "security_thread": {"present": True, "confidence": 0.98,
                            "position": "vertical_center",
                            "notes": "Bright fluorescent stripe at expected position"},
        "uv_watermark": {"present": True, "confidence": 0.94,
                         "notes": "Bank watermark ghost image clearly visible"},
        "overall_uv_risk_score": 0.03,
        "requires_human_review": False,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    inp = UVSecurityInput(
        instrument_id="INS-001", bank_id="kbl",
        uv_image_url="minio://cts/uv.tif",
    )
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.uv_security_passed is True
    assert result.pentograph_authentic is True
    assert result.pentograph_confidence == pytest.approx(0.96)
    assert result.security_thread_present is True
    assert result.security_thread_confidence == pytest.approx(0.98)
    assert result.uv_watermark_present is True
    assert result.uv_watermark_confidence == pytest.approx(0.94)
    assert result.uv_risk_score == pytest.approx(0.03)
    assert result.requires_human_review is False
    assert result.degraded is False


# ── activity — pentograph fails → not passed ────────────────────────────────

@pytest.mark.asyncio
async def test_pentograph_fail_makes_check_fail():
    UVSecurityInput, _, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": False, "confidence": 0.91,
                       "notes": "UV pattern absent or inconsistent — possible colour photocopy"},
        "security_thread": {"present": True, "confidence": 0.97, "position": "vertical_center",
                            "notes": "Thread present"},
        "uv_watermark": {"present": True, "confidence": 0.93, "notes": "Watermark visible"},
        "overall_uv_risk_score": 0.82,
        "requires_human_review": True,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    inp = UVSecurityInput(instrument_id="INS-002", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.uv_security_passed is False
    assert result.pentograph_authentic is False
    assert result.uv_risk_score == pytest.approx(0.82)
    assert result.requires_human_review is True


# ── activity — security thread missing → not passed ─────────────────────────

@pytest.mark.asyncio
async def test_security_thread_absent_makes_check_fail():
    UVSecurityInput, _, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": True, "confidence": 0.95, "notes": "OK"},
        "security_thread": {"present": False, "confidence": 0.89,
                            "position": None,
                            "notes": "No fluorescent thread detected"},
        "uv_watermark": {"present": True, "confidence": 0.92, "notes": "OK"},
        "overall_uv_risk_score": 0.71,
        "requires_human_review": True,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    inp = UVSecurityInput(instrument_id="INS-003", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.uv_security_passed is False
    assert result.security_thread_present is False
    assert result.requires_human_review is True


# ── activity — watermark missing → not passed ────────────────────────────────

@pytest.mark.asyncio
async def test_uv_watermark_absent_makes_check_fail():
    UVSecurityInput, _, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": True, "confidence": 0.94, "notes": "OK"},
        "security_thread": {"present": True, "confidence": 0.96, "position": "vertical_center",
                            "notes": "OK"},
        "uv_watermark": {"present": False, "confidence": 0.88,
                         "notes": "Watermark area shows uniform fluorescence — likely inkjet print"},
        "overall_uv_risk_score": 0.68,
        "requires_human_review": True,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    inp = UVSecurityInput(instrument_id="INS-004", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.uv_security_passed is False
    assert result.uv_watermark_present is False


# ── activity — no orchestrator → degraded ────────────────────────────────────

@pytest.mark.asyncio
async def test_no_orchestrator_returns_degraded_with_human_review():
    UVSecurityInput, _, analyze_uv_security = _import()

    inp = UVSecurityInput(instrument_id="INS-005", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=None)

    assert result.degraded is True
    assert result.requires_human_review is True
    assert result.uv_security_passed is False


# ── activity — model returns malformed JSON → degraded ───────────────────────

@pytest.mark.asyncio
async def test_malformed_json_returns_degraded():
    UVSecurityInput, _, analyze_uv_security = _import()

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content="NOT VALID JSON {{")
    )

    inp = UVSecurityInput(instrument_id="INS-006", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.degraded is True
    assert result.requires_human_review is True


# ── activity — model call raises exception → degraded ────────────────────────

@pytest.mark.asyncio
async def test_model_exception_returns_degraded():
    UVSecurityInput, _, analyze_uv_security = _import()

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(side_effect=RuntimeError("vLLM timeout"))

    inp = UVSecurityInput(instrument_id="INS-007", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert result.degraded is True
    assert result.requires_human_review is True


# ── uv_risk_score validation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_uv_risk_score_clamped_to_0_1():
    """LLM returning out-of-range score is clamped, not rejected."""
    UVSecurityInput, _, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": True, "confidence": 0.9, "notes": ""},
        "security_thread": {"present": True, "confidence": 0.9, "position": "center", "notes": ""},
        "uv_watermark": {"present": True, "confidence": 0.9, "notes": ""},
        "overall_uv_risk_score": 1.5,   # out of range — must be clamped to 1.0
        "requires_human_review": False,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    inp = UVSecurityInput(instrument_id="INS-008", bank_id="kbl",
                          uv_image_url="minio://cts/uv.tif")
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    assert 0.0 <= result.uv_risk_score <= 1.0


# ── high-value cheque → always routed to human review even if UV passes ──────

@pytest.mark.asyncio
async def test_high_value_always_requires_human_review():
    """cheque_amount above high-value threshold triggers human_review even on UV pass."""
    UVSecurityInput, _, analyze_uv_security = _import()

    model_response = json.dumps({
        "pentograph": {"authentic": True, "confidence": 0.97, "notes": ""},
        "security_thread": {"present": True, "confidence": 0.98, "position": "center", "notes": ""},
        "uv_watermark": {"present": True, "confidence": 0.95, "notes": ""},
        "overall_uv_risk_score": 0.02,
        "requires_human_review": False,
    })

    mock_orchestrator = MagicMock()
    mock_orchestrator.call_vision = AsyncMock(
        return_value=MagicMock(content=model_response)
    )

    # Amount above HIGH_VALUE threshold (500000)
    inp = UVSecurityInput(
        instrument_id="INS-009", bank_id="kbl",
        uv_image_url="minio://cts/uv.tif",
        cheque_amount=750000.0,
    )
    result = await analyze_uv_security(inp, orchestrator=mock_orchestrator)

    # UV passes — but high-value still triggers human review
    assert result.uv_security_passed is True
    assert result.requires_human_review is True
