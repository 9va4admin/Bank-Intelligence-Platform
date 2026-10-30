"""
XGBoost + SHAP fraud model: training (stand-in) and loading.

HONESTY NOTE: no labelled fraud history exists in dev. The only model this module can train is a
SYNTHETIC STAND-IN, fitted to data labelled by the same rules as the rule-based fallback. It proves the
XGBoost -> SHAP -> score_fraud path works end to end; it does NOT detect real fraud. It labels itself
(`synthetic=True`, `source="xgboost_synthetic_standin"`) and that label is copied into every result's
shap_values["_source"]. Replace the file with a model trained on real labelled cheques before relying on it.

Contract with score_fraud: model.predict_proba(X), model.feature_names, explainer.shap_values(X).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import structlog
from shared.messages import get_message

log = structlog.get_logger()

FEATURE_NAMES = ["amount", "ocr_confidence", "alteration_flag"]
SOURCE_SYNTHETIC = "xgboost_synthetic_standin"


class FraudModel:
    """Thin wrapper over an xgboost.XGBClassifier exposing what score_fraud needs."""

    def __init__(self, clf, feature_names, synthetic: bool, source: str) -> None:
        self._clf = clf
        self.feature_names = list(feature_names)
        self.synthetic = synthetic
        self.source = source

    def predict_proba(self, X):
        return self._clf.predict_proba(np.asarray(X, dtype=float))

    @property
    def booster(self):
        return self._clf.get_booster()


class _Explainer:
    """shap.TreeExplainer adapter returning a plain [row][feature] array for the positive class."""

    def __init__(self, model: FraudModel) -> None:
        import shap
        self._explainer = shap.TreeExplainer(model.booster)

    def shap_values(self, X):
        vals = self._explainer.shap_values(np.asarray(X, dtype=float))
        return np.asarray(vals)


def _synthetic_dataset(n: int, seed: int):
    """Rows labelled by the same logic as the rule-based fallback (plus noise) — NOT real fraud."""
    rng = np.random.default_rng(seed)
    amount = rng.lognormal(mean=11.0, sigma=1.2, size=n)          # ~Rs 60k median, long tail
    ocr = np.clip(rng.normal(0.93, 0.12, size=n), 0.2, 1.0)
    alt = (rng.random(n) < 0.08).astype(float)
    risk = 0.10 + 0.60 * alt + 0.15 * (ocr < 0.80) + 0.05 * (amount > 500000) + rng.normal(0, 0.05, size=n)
    y = (risk > 0.35).astype(int)
    return np.column_stack([amount, ocr, alt]), y


def train_standin_model(path: str, seed: int = 7, n: int = 6000) -> None:
    """Train the synthetic stand-in and write <path> (xgboost JSON) + <path>.meta.json."""
    from xgboost import XGBClassifier
    X, y = _synthetic_dataset(n, seed)
    clf = XGBClassifier(n_estimators=60, max_depth=3, learning_rate=0.15, subsample=0.9,
                        eval_metric="logloss", random_state=seed)
    clf.fit(X, y)
    clf.save_model(path)
    Path(path + ".meta.json").write_text(json.dumps({
        "feature_names": FEATURE_NAMES, "synthetic": True, "source": SOURCE_SYNTHETIC,
        "note": get_message("CTS_TRAINED_ON_RULE_LABELLED_SYNTHETIC"),
    }), encoding="utf-8")


def load_fraud_model(path: Optional[str]):
    """-> (FraudModel, explainer) or (None, None) when absent/corrupt (caller keeps the rule fallback)."""
    if not path or not Path(path).is_file():
        return None, None
    try:
        from xgboost import XGBClassifier
        meta_path = Path(path + ".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        clf = XGBClassifier()
        clf.load_model(path)
        model = FraudModel(
            clf, meta.get("feature_names", FEATURE_NAMES),
            synthetic=bool(meta.get("synthetic", True)),          # unknown provenance is treated as synthetic
            source=meta.get("source", SOURCE_SYNTHETIC),
        )
        return model, _Explainer(model)
    except Exception as exc:
        log.warning("fraud_model.load_failed", error=str(exc))
        return None, None
