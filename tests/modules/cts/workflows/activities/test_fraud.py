"""
Tests for modules/cts/workflows/activities/fraud.py

XGBoost ensemble fraud scoring + SHAP explainability.
SHAP values are MANDATORY — no fraud result without them.
Model unavailable → fallback rule-based scorer.
All thresholds from config, never hardcoded.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(
    instrument_id="INST001",
    bank_id="test-bank",
    amount=50000.0,
    micr_line="123456789012345",
    ocr_confidence=0.97,
    alteration_detected=False,
    account_last4="7890",
):
    from modules.cts.workflows.activities.fraud import FraudActivityInput
    return FraudActivityInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        amount=amount,
        micr_line=micr_line,
        ocr_confidence=ocr_confidence,
        alteration_detected=alteration_detected,
        account_last4=account_last4,
    )


class TestFraudInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.activities.fraud import FraudActivityInput
        with pytest.raises(Exception):
            FraudActivityInput(bank_id="b", amount=100.0, micr_line="x",
                               ocr_confidence=0.9, alteration_detected=False, account_last4="1234")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.amount = 99999999.0


class TestFraudScoringHappyPath:
    @pytest.mark.asyncio
    async def test_low_risk_returns_low_score(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.95, 0.05]])
        mock_model.feature_names = ["amount", "ocr_confidence", "alteration_flag"]
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(
            return_value=[[0.01, -0.02, 0.0]]
        )

        result = await score_fraud(
            _make_input(),
            model=mock_model,
            explainer=mock_explainer,
        )
        assert result.fraud_score < 0.5

    @pytest.mark.asyncio
    async def test_result_contains_shap_values(self):
        """SHAP values are mandatory in every fraud result."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.95, 0.05]])
        mock_model.feature_names = ["amount", "ocr_confidence", "alteration_flag"]
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.01, -0.02, 0.0]])

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert result.shap_values is not None
        assert len(result.shap_values) > 0

    @pytest.mark.asyncio
    async def test_shap_values_keyed_by_feature_name(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.9, 0.1]])
        mock_model.feature_names = ["amount", "ocr_confidence", "alteration_flag"]
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.05, -0.03, 0.0]])

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert "amount" in result.shap_values
        assert "ocr_confidence" in result.shap_values

    @pytest.mark.asyncio
    async def test_high_risk_returns_high_score(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.08, 0.92]])
        mock_model.feature_names = ["amount", "alteration_flag"]
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.4, 0.3]])

        result = await score_fraud(_make_input(alteration_detected=True, amount=9000000.0),
                                   model=mock_model, explainer=mock_explainer)
        assert result.fraud_score > 0.5

    @pytest.mark.asyncio
    async def test_result_is_frozen(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.9, 0.1]])
        mock_model.feature_names = ["amount"]
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.1]])

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        with pytest.raises(Exception):
            result.fraud_score = 0.99


class TestFraudScoringDegradation:
    @pytest.mark.asyncio
    async def test_model_unavailable_returns_fallback_score(self):
        """XGBoost down → rule-based fallback, never crashes workflow."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=Exception("model file missing"))
        mock_explainer = MagicMock()

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert result is not None
        assert isinstance(result.fraud_score, float)

    @pytest.mark.asyncio
    async def test_model_unavailable_degraded_flag_set(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=RuntimeError("CUDA OOM"))
        mock_explainer = MagicMock()

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_model_unavailable_still_has_shap_values(self):
        """Even in fallback mode, shap_values field must be populated."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        mock_explainer = MagicMock()

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert result.shap_values is not None

    @pytest.mark.asyncio
    async def test_model_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=ConnectionError("socket closed"))
        mock_explainer = MagicMock()

        result = await score_fraud(_make_input(), model=mock_model, explainer=mock_explainer)
        assert result is not None


class TestFraudFallbackRules:
    @pytest.mark.asyncio
    async def test_fallback_alteration_raises_score(self):
        """Rule-based fallback: alteration_detected bumps score."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        mock_explainer = MagicMock()

        result_clean = await score_fraud(_make_input(alteration_detected=False),
                                         model=mock_model, explainer=mock_explainer)
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        result_altered = await score_fraud(_make_input(alteration_detected=True),
                                           model=mock_model, explainer=mock_explainer)

        assert result_altered.fraud_score > result_clean.fraud_score
