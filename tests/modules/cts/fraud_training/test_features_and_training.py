"""Fraud feature schema, history feature-store interface, and a training pipeline with honest guardrails."""
import math

import numpy as np
import pytest

from modules.cts.fraud_training.features import FEATURES, build_feature_dict, NullFeatureStore
from modules.cts.fraud_training.train import TrainingRefused, train_model
from modules.cts.workflows.activities.fraud import FraudActivityInput


def _inp(**kw):
    base = dict(instrument_id="I1", bank_id="kbl", amount=250000.0, micr_line="x", ocr_confidence=0.9,
                alteration_detected=False, account_last4="0024",
                sig_result={"match_score": 0.93, "verifier_trained": False},
                cbs_result={"available_balance": 1000000.0}, pps_result={"outcome": "FOUND"})
    base.update(kw)
    return FraudActivityInput(**base)


class TestFeatureSchema:
    def test_every_feature_declares_where_it_comes_from(self):
        assert FEATURES and all(f.source in ("pipeline", "history") for f in FEATURES)
        assert len({f.name for f in FEATURES}) == len(FEATURES)

    def test_history_features_need_data_the_bank_holds(self):
        history = {f.name for f in FEATURES if f.source == "history"}
        assert {"amount_vs_account_median", "payee_seen_before", "cheques_last_24h"} <= history


class TestBuildFeatureDict:
    def test_pipeline_features_are_filled_from_the_activity_input(self):
        fd = build_feature_dict(_inp())
        assert fd["amount"] == 250000.0 and fd["ocr_confidence"] == 0.9 and fd["alteration_flag"] == 0.0
        assert fd["signature_match_score"] == 0.93
        assert fd["amount_to_balance_ratio"] == pytest.approx(0.25)

    def test_history_features_are_missing_not_zero_without_a_feature_store(self):
        fd = build_feature_dict(_inp())
        assert fd["payee_seen_before"] is None and fd["cheques_last_24h"] is None

    def test_a_feature_store_supplies_history(self):
        class Store(NullFeatureStore):
            def account_features(self, bank_id, account_last4):
                return {"amount_vs_account_median": 12.5, "cheques_last_24h": 7.0, "payee_seen_before": 0.0}
        fd = build_feature_dict(_inp(), Store())
        assert fd["amount_vs_account_median"] == 12.5 and fd["payee_seen_before"] == 0.0

    def test_missing_upstream_context_gives_missing_features_not_a_crash(self):
        fd = build_feature_dict(_inp(sig_result=None, cbs_result=None, pps_result=None))
        assert fd["signature_match_score"] is None and fd["amount_to_balance_ratio"] is None


def _dataset(n=2000, pos_rate=0.05, seed=1):
    rng = np.random.default_rng(seed)
    X = {f.name: rng.normal(0, 1, n) for f in FEATURES}
    y = (rng.random(n) < pos_rate).astype(int)
    for name in list(X)[:3]:                       # make the first few features informative
        X[name] = X[name] + 2.5 * y
    ts = np.arange(n)                              # time order
    return X, y, ts


class TestTrainingGuardrails:
    def test_trains_and_reports_held_out_metrics(self, tmp_path):
        X, y, ts = _dataset()
        rep = train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False, seed=3)
        assert rep["rows"] == 2000 and rep["positives"] == int(y.sum())
        assert set(rep["test"]) >= {"precision", "recall", "f1", "false_positive_rate", "false_negative_rate"}
        assert rep["test"]["f1"] > 0.5
        assert (tmp_path / "m.json").exists() and (tmp_path / "m.json.meta.json").exists()

    def test_split_is_chronological_so_the_future_never_trains_the_past(self, tmp_path):
        X, y, ts = _dataset()
        rep = train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False, seed=3)
        assert rep["split"]["train_max_ts"] < rep["split"]["val_min_ts"] <= rep["split"]["val_max_ts"] < rep["split"]["test_min_ts"]

    def test_refuses_too_few_positives(self, tmp_path):
        X, y, ts = _dataset(n=2000, pos_rate=0.0)
        with pytest.raises(TrainingRefused):
            train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False)

    def test_refuses_too_few_rows(self, tmp_path):
        X, y, ts = _dataset(n=100, pos_rate=0.3)
        with pytest.raises(TrainingRefused):
            train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False)

    def test_threshold_is_chosen_on_validation_to_cap_false_negatives(self, tmp_path):
        X, y, ts = _dataset()
        rep = train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False, seed=3)
        assert rep["threshold_selection"]["target_false_negative_rate"] == 0.01
        assert rep["threshold_selection"]["validation_false_negative_rate"] <= 0.05

    def test_report_states_whether_the_documented_targets_are_met_with_the_interval(self, tmp_path):
        X, y, ts = _dataset()
        rep = train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False, seed=3)
        assert "meets_nfr" in rep and isinstance(rep["meets_nfr"], bool)
        assert rep["nfr_note"]

    def test_synthetic_data_always_produces_a_synthetic_labelled_model(self, tmp_path):
        import json
        X, y, ts = _dataset()
        train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=True, seed=3)
        meta = json.loads((tmp_path / "m.json.meta.json").read_text())
        assert meta["synthetic"] is True and meta["source"] == "xgboost_synthetic_standin"
        assert meta["feature_names"] == [f.name for f in FEATURES]

    def test_real_data_model_is_labelled_with_its_provenance_not_as_synthetic(self, tmp_path):
        import json
        X, y, ts = _dataset()
        train_model(X, y, ts, out_path=str(tmp_path / "m.json"), synthetic=False, seed=3, data_label="kbl-2026-q3")
        meta = json.loads((tmp_path / "m.json.meta.json").read_text())
        assert meta["synthetic"] is False and meta["data_label"] == "kbl-2026-q3" and meta["source"].startswith("xgboost_trained")
