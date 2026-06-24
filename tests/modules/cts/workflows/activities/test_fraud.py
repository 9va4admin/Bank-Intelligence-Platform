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

    @pytest.mark.asyncio
    async def test_fallback_low_ocr_confidence_raises_score(self):
        """Rule-based fallback: ocr_confidence < 0.70 bumps score."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        mock_explainer = MagicMock()

        result_good_ocr = await score_fraud(
            _make_input(ocr_confidence=0.95),
            model=mock_model, explainer=mock_explainer,
        )
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        result_bad_ocr = await score_fraud(
            _make_input(ocr_confidence=0.60),
            model=mock_model, explainer=mock_explainer,
        )

        assert result_bad_ocr.fraud_score > result_good_ocr.fraud_score

    @pytest.mark.asyncio
    async def test_fallback_very_high_amount_raises_score(self):
        """Rule-based fallback: amount > 5_000_000 bumps score."""
        from modules.cts.workflows.activities.fraud import score_fraud

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        mock_explainer = MagicMock()

        result_normal = await score_fraud(
            _make_input(amount=50000.0),
            model=mock_model, explainer=mock_explainer,
        )
        mock_model.predict_proba = MagicMock(side_effect=Exception("down"))
        result_huge = await score_fraud(
            _make_input(amount=6_000_000.0),
            model=mock_model, explainer=mock_explainer,
        )

        assert result_huge.fraud_score > result_normal.fraud_score


# ---------------------------------------------------------------------------
# vLLM rationale synthesis path (lines 97, 141-189)
# ---------------------------------------------------------------------------

class TestFraudRationaleSynthesis:
    """Cover the _synthesise_rationale path invoked when vllm_client is provided."""

    def _make_vllm_response(self):
        return {
            "content": "The fraud score is elevated due to signature mismatch and high amount.",
            "usage": {
                "raw_prompt_tokens": 800,
                "compressed_prompt_tokens": 180,
                "reduction_pct": 77.5,
            },
            "latency_ms": {
                "compression": 12,
                "inference": 320,
            },
        }

    def _make_input_with_ocr(self):
        from modules.cts.workflows.activities.fraud import FraudActivityInput
        return FraudActivityInput(
            instrument_id="INST001",
            bank_id="test-bank",
            amount=50000.0,
            micr_line="123456789012345",
            ocr_confidence=0.97,
            alteration_detected=False,
            account_last4="7890",
            ocr_result={"amount": "50000", "confidence": 0.98},
        )

    @pytest.mark.asyncio
    async def test_rationale_populated_when_vllm_client_provided(self):
        """Score fraud with vllm_client → rationale is returned."""
        from modules.cts.workflows.activities.fraud import score_fraud
        from unittest.mock import AsyncMock, MagicMock

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.3, 0.7]])
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.1, -0.2, 0.05, 0.3, -0.15, 0.0]])

        vllm_client = MagicMock()
        vllm_client.chat = AsyncMock(return_value=self._make_vllm_response())

        result = await score_fraud(
            self._make_input_with_ocr(),
            model=mock_model,
            explainer=mock_explainer,
            vllm_client=vllm_client,
        )
        assert result.rationale is not None
        assert len(result.rationale) > 10

    @pytest.mark.asyncio
    async def test_rationale_headroom_reduction_pct_captured(self):
        """headroom_reduction_pct comes from vllm response usage."""
        from modules.cts.workflows.activities.fraud import score_fraud
        from unittest.mock import AsyncMock, MagicMock

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.3, 0.7]])
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.1, -0.2, 0.05, 0.3, -0.15, 0.0]])

        vllm_client = MagicMock()
        vllm_client.chat = AsyncMock(return_value=self._make_vllm_response())

        result = await score_fraud(
            self._make_input_with_ocr(),
            model=mock_model,
            explainer=mock_explainer,
            vllm_client=vllm_client,
        )
        assert result.headroom_reduction_pct == 77.5

    @pytest.mark.asyncio
    async def test_rationale_skipped_when_ocr_result_is_none(self):
        """vllm_client present but ocr_result is None → rationale stays None."""
        from modules.cts.workflows.activities.fraud import score_fraud
        from unittest.mock import AsyncMock, MagicMock

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.3, 0.7]])
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.1, -0.2, 0.05, 0.3, -0.15, 0.0]])

        vllm_client = MagicMock()
        vllm_client.chat = AsyncMock(return_value=self._make_vllm_response())

        result = await score_fraud(
            _make_input(),  # ocr_result=None by default
            model=mock_model,
            explainer=mock_explainer,
            vllm_client=vllm_client,
        )
        vllm_client.chat.assert_not_called()
        assert result.rationale is None

    @pytest.mark.asyncio
    async def test_rationale_uses_cts_reasoning_queue(self):
        """vllm_client.chat must be called with queue='cts-reasoning'."""
        from modules.cts.workflows.activities.fraud import score_fraud
        from unittest.mock import AsyncMock, MagicMock, call

        mock_model = MagicMock()
        mock_model.predict_proba = MagicMock(return_value=[[0.3, 0.7]])
        mock_explainer = MagicMock()
        mock_explainer.shap_values = MagicMock(return_value=[[0.1, -0.2, 0.05, 0.3, -0.15, 0.0]])

        vllm_client = MagicMock()
        vllm_client.chat = AsyncMock(return_value=self._make_vllm_response())

        await score_fraud(
            self._make_input_with_ocr(),
            model=mock_model,
            explainer=mock_explainer,
            vllm_client=vllm_client,
        )
        call_kwargs = vllm_client.chat.call_args.kwargs
        assert call_kwargs.get("queue") == "cts-reasoning"
