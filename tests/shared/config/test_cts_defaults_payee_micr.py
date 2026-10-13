"""Layer 3 defaults for the inward safety gates (2026-10-13)."""
import pytest
from shared.config.config_service import _LAYER3_DEFAULTS


def test_multisignal_rescue_is_off_by_default():
    # An unreadable payee / amount-in-words is called unequivocally: human review.
    assert _LAYER3_DEFAULTS["cts.ocr_multisignal_rescue_enabled"] is False


def test_payee_gate_defaults_present_and_strict():
    assert _LAYER3_DEFAULTS["cts.payee_reread_min_similarity"] == 0.99
    assert _LAYER3_DEFAULTS["cts.payee_reference_min_similarity"] == 0.97
    assert _LAYER3_DEFAULTS["cts.payee_reread_model"] == "qwen3-vl-32b"


def test_micr_branch_master_defaults_to_empty_meaning_disabled():
    assert _LAYER3_DEFAULTS["cts.micr_branch_master"] == []


@pytest.mark.asyncio
async def test_workflow_thresholds_carry_the_new_keys():
    from unittest.mock import AsyncMock
    from shared.config.config_service import ConfigService
    cs = ConfigService.__new__(ConfigService)
    cs.get = AsyncMock(side_effect=lambda k: _LAYER3_DEFAULTS.get(k, 0))
    out = await ConfigService.get_workflow_thresholds(cs)
    assert out["ocr_multisignal_rescue_enabled"] is False
    assert out["payee_reference_min_similarity"] == 0.97
    assert out["micr_branch_master"] == []


def test_signature_and_date_safety_defaults():
    assert _LAYER3_DEFAULTS["cts.signature_absent_action"] == "HUMAN_REVIEW"
    assert _LAYER3_DEFAULTS["cts.date_implausible_age_days"] == 1095
    assert _LAYER3_DEFAULTS["cts.date_implausible_future_days"] == 365


@pytest.mark.asyncio
async def test_workflow_thresholds_carry_signature_and_date_keys():
    from unittest.mock import AsyncMock
    from shared.config.config_service import ConfigService
    cs = ConfigService.__new__(ConfigService)
    cs.get = AsyncMock(side_effect=lambda k: _LAYER3_DEFAULTS.get(k, 0))
    out = await ConfigService.get_workflow_thresholds(cs)
    assert out["signature_absent_action"] == "HUMAN_REVIEW"
    assert out["date_implausible_age_days"] == 1095
