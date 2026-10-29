"""
Bucket resolution for inward cheques.

Two questions decide a cheque's bucket:
  1. Did the system decide it, or does it need a human?
  2. What kind of cheque is it (value, account type, customer history)?

  needs a human   -> the first class bucket that fits, in the admin's priority order
                     (HVC high value, CA corporate, IP institution, FCC frequent customer, LVC low value),
                     otherwise HR (general human review)
  system decided  -> SIP_SUCCESS (system confirmed) or SIP_REJECT (system returned)
  VAL             -> the Validation (checker) queue; never produced here: an item moves to it after a maker decides
                     (maker-checker), and checkers are connected to it like any other bucket
  MISC            -> never produced here: it is where an item lands when it is de-allocated or no reviewer is
                     connected to its bucket (see AllocationService)

Every threshold and list comes from Layer 3 config (bare key names, as delivered by config_service.get_cts_config).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CLASS_BUCKETS = ("HVC", "CA", "IP", "FCC", "LVC")
# OUT_* are the buckets of held outward items (see modules/cts/outward_buckets.py); VAL (checker) and MISC are shared.
ALL_BUCKETS = ("HVC", "CA", "IP", "LVC", "FCC", "SIP_SUCCESS", "SIP_REJECT", "HR", "VAL", "MISC",
               "OUT_HV", "OUT_MISMATCH", "OUT_COMPLIANCE", "OUT_REVIEW")

# Safe defaults when a key is absent (the Layer 3 defaults in config_service carry the same values).
_DEFAULT_PRIORITY = ["HVC", "CA", "IP", "FCC", "LVC"]
_DEFAULT_HVC_MIN = 500_000
_DEFAULT_LVC_MAX = 50_000
_DEFAULT_FREQUENT_MIN = 5
_DEFAULT_CORPORATE_TYPES = ["CORPORATE"]
_DEFAULT_INSTITUTION_TYPES = ["INSTITUTION", "GOVERNMENT"]


@dataclass(frozen=True)
class BucketFacts:
    needs_human: bool
    system_decision: Optional[str] = None          # "CONFIRM" | "RETURN" when the system decided
    amount: Optional[float] = None                 # presented amount in rupees
    account_type: Optional[str] = None             # CORPORATE | INSTITUTION | GOVERNMENT | INDIVIDUAL ... (from CBS)
    listed_in: frozenset = field(default_factory=frozenset)   # bank-maintained account lists the account is on (CA / IP)
    recent_cheques: Optional[int] = None           # cheques on this account in bucket_frequent_window_days


def _fits(bucket: str, facts: BucketFacts, cfg: dict) -> bool:
    amount = facts.amount
    if bucket == "HVC":
        return amount is not None and amount >= float(cfg.get("bucket_hvc_min_amount", _DEFAULT_HVC_MIN))
    if bucket == "CA":
        types = {t.upper() for t in cfg.get("bucket_corporate_account_types", _DEFAULT_CORPORATE_TYPES)}
        return (facts.account_type or "").upper() in types or "CA" in facts.listed_in
    if bucket == "IP":
        types = {t.upper() for t in cfg.get("bucket_institution_account_types", _DEFAULT_INSTITUTION_TYPES)}
        return (facts.account_type or "").upper() in types or "IP" in facts.listed_in
    if bucket == "FCC":
        return facts.recent_cheques is not None and facts.recent_cheques >= int(
            cfg.get("bucket_frequent_min_cheques", _DEFAULT_FREQUENT_MIN))
    if bucket == "LVC":
        return amount is not None and amount < float(cfg.get("bucket_lvc_max_amount", _DEFAULT_LVC_MAX))
    return False


def _priority(cfg: dict) -> list[str]:
    return [b for b in cfg.get("bucket_priority", _DEFAULT_PRIORITY) if b in CLASS_BUCKETS]


def matched_buckets(facts: BucketFacts, cfg: dict) -> list[str]:
    """Every class bucket the cheque fits, in priority order (for the admin screen; the first one is the bucket)."""
    return [b for b in _priority(cfg) if _fits(b, facts, cfg)]


def resolve_bucket(facts: BucketFacts, cfg: dict) -> str:
    if not facts.needs_human:
        decision = (facts.system_decision or "").upper()
        if decision == "CONFIRM":
            return "SIP_SUCCESS"
        if decision == "RETURN":
            return "SIP_REJECT"
        return "HR"        # a system outcome we cannot classify is never silently treated as processed
    matched = matched_buckets(facts, cfg)
    return matched[0] if matched else "HR"
