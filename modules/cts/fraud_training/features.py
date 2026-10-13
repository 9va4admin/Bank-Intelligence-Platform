"""Fraud feature schema, builder, and the history feature-store interface.

Two kinds of feature:
  pipeline : computable from what the inward workflow already has for this instrument
  history  : needs the bank's own account history (typical amounts, known payees, velocity). Supplied by a
             FeatureStore the bank implements against its data; without one these are MISSING (None),
             never 0, because a zero would claim knowledge we do not have.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class Feature:
    name: str
    source: str              # "pipeline" | "history"
    description: str


FEATURES: list[Feature] = [
    Feature("amount", "pipeline", "presented amount in rupees"),
    Feature("ocr_confidence", "pipeline", "overall OCR confidence for the instrument"),
    Feature("alteration_flag", "pipeline", "1 if alteration was detected on the image"),
    Feature("signature_match_score", "pipeline", "similarity to the account's enrolled specimens (meaningful only with a trained verifier)"),
    Feature("amount_to_balance_ratio", "pipeline", "presented amount / available balance"),
    Feature("pps_found", "pipeline", "1 if a positive-pay entry matched, 0 if not"),
    Feature("amount_vs_account_median", "history", "amount divided by the account's median cheque amount over 90 days"),
    Feature("payee_seen_before", "history", "1 if this payee has been paid from the account before"),
    Feature("cheques_last_24h", "history", "number of cheques presented on the account in the last 24 hours"),
    Feature("days_since_account_opened", "history", "account age in days"),
]


class FeatureStore(Protocol):
    def account_features(self, bank_id: str, account_last4: str) -> dict[str, Optional[float]]: ...


class NullFeatureStore:
    """No bank history available: every history feature is missing."""

    def account_features(self, bank_id: str, account_last4: str) -> dict[str, Optional[float]]:
        return {}


def _get(d: Any, key: str) -> Any:
    if d is None:
        return None
    return d.get(key) if isinstance(d, dict) else getattr(d, key, None)


def build_feature_dict(inp: Any, store: Optional[FeatureStore] = None) -> dict[str, Optional[float]]:
    """Feature name -> value (None when unknown). Pure; never raises on missing upstream context."""
    store = store or NullFeatureStore()
    bal = _get(inp.cbs_result, "available_balance")
    pps = _get(inp.pps_result, "outcome")
    fd: dict[str, Optional[float]] = {
        "amount": float(inp.amount),
        "ocr_confidence": float(inp.ocr_confidence),
        "alteration_flag": 1.0 if inp.alteration_detected else 0.0,
        "signature_match_score": _get(inp.sig_result, "match_score"),
        "amount_to_balance_ratio": (float(inp.amount) / float(bal)) if bal else None,
        "pps_found": None if pps is None else (1.0 if pps == "FOUND" else 0.0),
    }
    hist = store.account_features(inp.bank_id, inp.account_last4) or {}
    for f in FEATURES:
        if f.source == "history":
            fd[f.name] = hist.get(f.name)
    return fd
