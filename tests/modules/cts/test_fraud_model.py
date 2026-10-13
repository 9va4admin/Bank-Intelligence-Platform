"""XGBoost + SHAP fraud model plumbing.

The only model that can exist today is a SYNTHETIC STAND-IN trained on rule-labelled data: it
proves the XGBoost -> SHAP -> score_fraud path end to end, it does not detect real fraud. It must
therefore always identify itself as synthetic in the result.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.fraud_model import FEATURE_NAMES, load_fraud_model, train_standin_model
from modules.cts.workflows.activities.fraud import FraudActivityInput, score_fraud


def _inp(**kw):
    base = dict(instrument_id="I1", bank_id="kbl", amount=100000.0, micr_line="x", ocr_confidence=0.95,
                alteration_detected=False, account_last4="0024")
    base.update(kw)
    return FraudActivityInput(**base)


def _cfg():
    cs = MagicMock()
    cs.get_cts_config = AsyncMock(return_value={"cts.ocr_min_confidence": 0.8, "cts.high_value_amount_threshold": 500000})
    return cs


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("fraud") / "fraud_standin.json"
    train_standin_model(str(p), seed=7)
    return str(p)


class TestTrainAndLoad:
    def test_loaded_model_exposes_the_contract_score_fraud_needs(self, model_path):
        model, explainer = load_fraud_model(model_path)
        assert model is not None and explainer is not None
        assert model.feature_names == FEATURE_NAMES == ["amount", "ocr_confidence", "alteration_flag"]
        proba = model.predict_proba([[100000.0, 0.95, 0.0]])
        assert len(proba) == 1 and len(proba[0]) == 2 and abs(proba[0][0] + proba[0][1] - 1.0) < 1e-6

    def test_model_identifies_itself_as_synthetic(self, model_path):
        model, _ = load_fraud_model(model_path)
        assert model.synthetic is True and model.source == "xgboost_synthetic_standin"

    def test_altered_low_ocr_scores_higher_than_clean(self, model_path):
        model, _ = load_fraud_model(model_path)
        risky = model.predict_proba([[900000.0, 0.40, 1.0]])[0][1]
        clean = model.predict_proba([[50000.0, 0.98, 0.0]])[0][1]
        assert risky > clean + 0.3

    @pytest.mark.parametrize("bad", ["", "/no/such/model.json"])
    def test_missing_or_empty_path_returns_none(self, bad):
        assert load_fraud_model(bad) == (None, None)

    def test_corrupt_file_returns_none_not_raise(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not a model")
        assert load_fraud_model(str(p)) == (None, None)


class TestScoreFraudWithModel:
    @pytest.mark.asyncio
    async def test_real_model_path_not_degraded_with_shap_and_synthetic_label(self, model_path):
        model, explainer = load_fraud_model(model_path)
        res = await score_fraud(_inp(alteration_detected=True, ocr_confidence=0.5), config_service=_cfg(),
                                model=model, explainer=explainer)
        assert res.degraded is False
        assert 0.0 <= res.fraud_score <= 1.0
        assert set(FEATURE_NAMES) <= set(res.shap_values)
        assert res.shap_values["_source"] == "xgboost_synthetic_standin"

    @pytest.mark.asyncio
    async def test_without_model_still_falls_back_to_rules(self):
        res = await score_fraud(_inp(), config_service=_cfg())
        assert res.degraded is True and res.shap_values["_source"] == "rule_based_fallback"
