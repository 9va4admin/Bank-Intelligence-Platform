"""
Tests for modules/cts/workflows/activities/decision.py

synthesise_decision takes signals from all upstream activities and produces
a terminal CTS decision: STP_CONFIRM, STP_RETURN, or HUMAN_REVIEW.

All thresholds come from config_service — never hardcoded.
SHAP values must be present in output (required before NGCH filing).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signals(
    fraud_score=0.05,
    ocr_confidence=0.97,
    signature_match=0.95,
    cbs_outcome="PROCEED",
    alteration_detected=False,
    pps_outcome="FOUND",
    available_balance=100000.0,
    amount=50000.0,
):
    from modules.cts.workflows.activities.decision import DecisionInput
    return DecisionInput(
        instrument_id="INST001",
        bank_id="test-bank",
        fraud_score=fraud_score,
        ocr_confidence=ocr_confidence,
        signature_match_score=signature_match,
        cbs_outcome=cbs_outcome,
        alteration_detected=alteration_detected,
        pps_outcome=pps_outcome,
        available_balance=available_balance,
        cheque_amount=amount,
        shap_values={"amount_feature": 0.1, "drawer_history": -0.05},
    )


def _make_config(
    stp_threshold=0.92,
    fraud_threshold=0.72,
    ocr_min_confidence=0.85,
    sig_min_match=0.80,
):
    return {
        "stp_auto_confirm_threshold": stp_threshold,
        "human_review_fraud_threshold": fraud_threshold,
        "ocr_min_confidence": ocr_min_confidence,
        "sig_min_match_score": sig_min_match,
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestDecisionInput:
    def test_requires_shap_values(self):
        from modules.cts.workflows.activities.decision import DecisionInput
        with pytest.raises(Exception):
            DecisionInput(
                instrument_id="I", bank_id="b",
                fraud_score=0.1, ocr_confidence=0.9,
                signature_match_score=0.9, cbs_outcome="PROCEED",
                alteration_detected=False, pps_outcome="FOUND",
                available_balance=100.0, cheque_amount=50.0,
                # missing shap_values
            )

    def test_input_is_frozen(self):
        inp = _make_signals()
        with pytest.raises(Exception):
            inp.fraud_score = 0.99


# ---------------------------------------------------------------------------
# STP_CONFIRM path
# ---------------------------------------------------------------------------

class TestSTPConfirm:
    @pytest.mark.asyncio
    async def test_low_fraud_high_confidence_gives_stp_confirm(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05, ocr_confidence=0.98, signature_match=0.97),
            config=_make_config(stp_threshold=0.92, fraud_threshold=0.72),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_stp_confirm_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05),
            config=_make_config(),
        )
        assert result.decision == "STP_CONFIRM"
        assert result.shap_values is not None
        assert len(result.shap_values) > 0

    @pytest.mark.asyncio
    async def test_stp_confirm_has_rationale(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05),
            config=_make_config(),
        )
        assert result.rationale
        assert isinstance(result.rationale, str)


# ---------------------------------------------------------------------------
# STP_RETURN path
# ---------------------------------------------------------------------------

class TestSTPReturn:
    @pytest.mark.asyncio
    async def test_frozen_account_gives_return(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="RETURN"),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_alteration_detected_gives_return(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(alteration_detected=True),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_return_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="RETURN"),
            config=_make_config(),
        )
        assert result.shap_values is not None


# ---------------------------------------------------------------------------
# HUMAN_REVIEW path
# ---------------------------------------------------------------------------

class TestHumanReview:
    @pytest.mark.asyncio
    async def test_high_fraud_score_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.85),
            config=_make_config(fraud_threshold=0.72),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_ocr_confidence_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(ocr_confidence=0.70),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_signature_match_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(signature_match=0.60),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_gives_human_review(self):
        """CBS unavailable is not a RETURN — it's an escalation."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="CBS_UNAVAILABLE"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_pps_miss_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(pps_outcome="HUMAN_REVIEW"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_human_review_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.85),
            config=_make_config(),
        )
        assert result.shap_values is not None

    @pytest.mark.asyncio
    async def test_dormant_cbs_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="HUMAN_REVIEW"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Thresholds must not be hardcoded
# ---------------------------------------------------------------------------

class TestThresholdsFromConfig:
    @pytest.mark.asyncio
    async def test_different_fraud_threshold_changes_decision(self):
        """Verify threshold is read from config, not hardcoded."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        # With tight threshold (0.50), score 0.60 should trigger human review
        result_tight = await synthesise_decision(
            _make_signals(fraud_score=0.60),
            config=_make_config(fraud_threshold=0.50),
        )
        # With loose threshold (0.90), score 0.60 should proceed
        result_loose = await synthesise_decision(
            _make_signals(fraud_score=0.60),
            config=_make_config(fraud_threshold=0.90, stp_threshold=0.92),
        )
        assert result_tight.decision == "HUMAN_REVIEW"
        assert result_loose.decision != "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_different_stp_threshold_changes_decision(self):
        """STP confirm threshold is configurable per bank."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        # Signals that look good but we set a very high STP threshold
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05, ocr_confidence=0.93, signature_match=0.93),
            config=_make_config(stp_threshold=0.99, fraud_threshold=0.72),
        )
        # Low fraud but STP threshold set impossibly high → human review
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestDecisionOutput:
    @pytest.mark.asyncio
    async def test_output_has_decision_field(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        assert hasattr(result, "decision")

    @pytest.mark.asyncio
    async def test_output_has_instrument_id(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        assert result.instrument_id == "INST001"

    @pytest.mark.asyncio
    async def test_output_is_frozen(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        with pytest.raises(Exception):
            result.decision = "SOMETHING_ELSE"
