"""Fraud model training pipeline with guardrails that keep it honest.

It refuses to train on too little data, splits by time (never random), picks the decision threshold on the
VALIDATION slice only, reports metrics on a held-out TEST slice with intervals, states whether the documented
NFRs (F1 > 0.92, false positive < 3%, false negative < 1%) are met, and labels the artifact with its provenance.
Synthetic data can only ever produce a model labelled synthetic.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import numpy as np

from modules.cts.evaluation.stats import wilson_interval
from modules.cts.fraud_training.features import FEATURES
from shared.messages import get_message

MIN_ROWS = 1000
MIN_POSITIVES = 30
TARGET_FNR = 0.01
TARGET_FPR = 0.03
TARGET_F1 = 0.92


class TrainingRefused(Exception):
    pass


def _matrix(X: dict, names: list[str]) -> np.ndarray:
    n_rows = len(next(iter(X.values())))
    cols = []
    for n in names:
        col = X.get(n)
        cols.append(np.full(n_rows, np.nan) if col is None
                    else np.array([np.nan if v is None else v for v in col], dtype=float))
    return np.column_stack(cols)


def _rates(y: np.ndarray, pred: np.ndarray) -> dict:
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec, "f1": f1,
            "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
            "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0}


def train_model(X: dict, y, timestamps, out_path: str, *, synthetic: bool, seed: int = 7,
                data_label: Optional[str] = None, min_rows: int = MIN_ROWS, min_positives: int = MIN_POSITIVES) -> dict:
    from xgboost import XGBClassifier

    y = np.asarray(y, dtype=int)
    ts = np.asarray(timestamps)
    if len(y) < min_rows:
        raise TrainingRefused(get_message("CTS_ROWS_IS_BELOW_THE_MINIMUM", len=len(y), min_rows=min_rows))
    if int(y.sum()) < min_positives:
        raise TrainingRefused(get_message("CTS_POSITIVE_FRAUD_EXAMPLES_IS_BELOW", int=int(y.sum()), min_positives=min_positives))

    names = [f.name for f in FEATURES]
    M = _matrix(X, names)
    order = np.argsort(ts, kind="stable")                 # chronological: the future never trains the past
    M, y, ts = M[order], y[order], ts[order]
    n = len(y)
    a, b = int(n * 0.6), int(n * 0.8)
    tr, va, te = slice(0, a), slice(a, b), slice(b, n)
    if y[tr].sum() == 0 or y[va].sum() == 0 or y[te].sum() == 0:
        raise TrainingRefused(get_message("CTS_A_TRAIN_VALIDATION_TEST_SLICE"))

    pos, neg = int(y[tr].sum()), int((y[tr] == 0).sum())
    clf = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9,
                        scale_pos_weight=neg / max(pos, 1), eval_metric="logloss", random_state=seed)
    clf.fit(M[tr], y[tr])

    # Threshold on VALIDATION only: the highest threshold whose false-negative rate stays within target
    pv = clf.predict_proba(M[va])[:, 1]
    chosen, vfnr = 0.0, None
    for th in sorted(set(np.round(pv, 4)), reverse=True):
        r = _rates(y[va], (pv >= th).astype(int))
        if r["false_negative_rate"] <= TARGET_FNR:
            chosen, vfnr = float(th), r["false_negative_rate"]
            break
    if vfnr is None:                                       # target unreachable: take the most sensitive threshold
        chosen = float(min(pv))
        vfnr = _rates(y[va], (pv >= chosen).astype(int))["false_negative_rate"]

    pt = clf.predict_proba(M[te])[:, 1]
    test = _rates(y[te], (pt >= chosen).astype(int))
    fn_lo, fn_hi = wilson_interval(test["fn"], test["fn"] + test["tp"])
    fp_lo, fp_hi = wilson_interval(test["fp"], test["fp"] + test["tn"])
    meets = bool(fn_hi <= TARGET_FNR and fp_hi <= TARGET_FPR and test["f1"] > TARGET_F1)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clf.save_model(str(out))
    source = "xgboost_synthetic_standin" if synthetic else f"xgboost_trained:{data_label or 'unlabelled-data'}"
    data_hash = hashlib.sha256(M.tobytes() + y.tobytes()).hexdigest()[:16]
    report = {
        "rows": n, "positives": int(y.sum()), "synthetic": synthetic, "source": source, "data_hash": data_hash,
        "split": {"train_max_ts": float(ts[:a].max()), "val_min_ts": float(ts[a:b].min()), "val_max_ts": float(ts[a:b].max()),
                  "test_min_ts": float(ts[b:].min())},
        "threshold": chosen,
        "threshold_selection": {"target_false_negative_rate": TARGET_FNR, "validation_false_negative_rate": vfnr,
                                "chosen_on": get_message("CTS_VALIDATION_SLICE_ONLY")},
        "test": {**test, "false_negative_interval": [fn_lo, fn_hi], "false_positive_interval": [fp_lo, fp_hi]},
        "meets_nfr": meets,
        "nfr_note": (f"Targets: F1 > {TARGET_F1}, false negative < {TARGET_FNR:.0%}, false positive < {TARGET_FPR:.0%}. "
                     "Meets requires the 95% interval upper bounds to clear the error targets, not just the point estimates."),
    }
    Path(str(out) + ".meta.json").write_text(json.dumps({
        "feature_names": names, "synthetic": synthetic, "source": source, "data_label": data_label,
        "threshold": chosen, "report": report,
    }, indent=1, default=float), encoding="utf-8")
    return report
