"""Review buckets for held outward items.

Outward items are held for different reasons and at different values, so a bank connects people to the kinds of work they
handle (the same admin screen and subscriptions as inward). A held item's bucket is the first of these that fits, in the
bank's order (cts.outward_bucket_priority):

  OUT_HV          high value: its masked amount range is one of cts.outward_high_value_ranges
  OUT_MISMATCH    held for an amount or name mismatch
  OUT_COMPLIANCE  failed a CTS-2010 compliance or image check, or the processing failed
  OUT_REVIEW      anything else that needs a person (flagged by the checks); also where an unknown reason lands

The scan event keeps the amount only as a masked range, so value is judged on that range, not on rupees.
"""
from __future__ import annotations

from typing import Optional

OUTWARD_BUCKETS = ("OUT_HV", "OUT_MISMATCH", "OUT_COMPLIANCE", "OUT_REVIEW")

_DEFAULT_PRIORITY = list(OUTWARD_BUCKETS)
_DEFAULT_HIGH_RANGES = ["₹[5L-10L]", "₹[10L-1Cr]", "₹[>1Cr]"]
_MISMATCH = {"MISMATCH_HELD"}
_COMPLIANCE = {"CTS_REJECTED", "WORKFLOW_ERROR"}


def _fits(bucket: str, outcome: Optional[str], amount_range: Optional[str], cfg: dict) -> bool:
    if bucket == "OUT_HV":
        return amount_range in (cfg.get("outward_high_value_ranges") or _DEFAULT_HIGH_RANGES)
    if bucket == "OUT_MISMATCH":
        return outcome in _MISMATCH
    if bucket == "OUT_COMPLIANCE":
        return outcome in _COMPLIANCE
    return False


def classify_outward(outcome: Optional[str], amount_range: Optional[str], cfg: dict) -> str:
    order = [b for b in (cfg.get("outward_bucket_priority") or _DEFAULT_PRIORITY) if b in OUTWARD_BUCKETS]
    for bucket in order:
        if bucket != "OUT_REVIEW" and _fits(bucket, outcome, amount_range, cfg):
            return bucket
    return "OUT_REVIEW"
