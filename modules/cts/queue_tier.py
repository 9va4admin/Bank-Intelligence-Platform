"""
Queue tier resolution for CTS inward instruments.

Three tiers route instruments to separate Kafka topics and Temporal task queues
so high-value and very-high-value cheques can be processed by dedicated, higher-
capacity workers without competing with standard-value volume.

Tiers:
  standard   — presented_amount < queue_tier_high_value_threshold
  high_value — queue_tier_high_value_threshold <= amount < queue_tier_very_high_threshold
  very_high  — amount >= queue_tier_very_high_threshold

All thresholds come from cts_config (Layer 3, bank-configurable via Admin UI).
Defaults are read from the table below and are safe to use when keys are absent.
Never hardcode threshold values here — banks adjust them without a code change.

Default thresholds (documented; actual defaults live in infra/helm/values/_defaults.yaml):
  queue_tier_high_value_threshold : 100_000.0  (₹1 lakh)
  queue_tier_very_high_threshold  : 1_000_000.0 (₹10 lakh)
"""

_TIER_DEFAULTS = {
    "queue_tier_high_value_threshold": 100_000.0,
    "queue_tier_very_high_threshold": 1_000_000.0,
}

_VALID_TIERS = ("standard", "high_value", "very_high")

_TASK_QUEUE_SUFFIXES = {
    "standard":   "standard",
    "high_value": "high-value",
    "very_high":  "very-high",
}


def resolve_queue_tier(amount: float, cts_config: dict) -> str:
    """Return the queue tier string for a given presented_amount.

    Args:
        amount: cheque presented_amount (float, rupees)
        cts_config: Layer 3 config dict — may be empty; safe defaults applied

    Returns:
        "standard" | "high_value" | "very_high"
    """
    high_threshold = float(
        cts_config.get(
            "queue_tier_high_value_threshold",
            _TIER_DEFAULTS["queue_tier_high_value_threshold"],
        )
    )
    very_high_threshold = float(
        cts_config.get(
            "queue_tier_very_high_threshold",
            _TIER_DEFAULTS["queue_tier_very_high_threshold"],
        )
    )

    if amount >= very_high_threshold:
        return "very_high"
    if amount >= high_threshold:
        return "high_value"
    return "standard"


def task_queue_for_tier(bank_id: str, tier: str) -> str:
    """Return the Temporal task queue name for a given bank and tier.

    Args:
        bank_id: the bank's identifier
        tier: "standard" | "high_value" | "very_high"

    Returns:
        e.g. "cts-processing-saraswat-coop-high-value"

    Raises:
        ValueError: if tier is not one of the three valid tiers
    """
    if tier not in _VALID_TIERS:
        raise ValueError(
            f"Unknown queue tier {tier!r}. Valid tiers: {_VALID_TIERS}"
        )
    suffix = _TASK_QUEUE_SUFFIXES[tier]
    return f"cts-processing-{bank_id}-{suffix}"


def humanreview_task_queue_for_tier(bank_id: str, tier: str) -> str:
    """Return the Temporal task queue name for human review workers for a given tier.

    Standard-tier reviews use the base human review queue.
    High-value and very-high get dedicated queues so a burst of standard-value
    returns never starves a high-value review with a ticking IET clock.

    Args:
        bank_id: the bank's identifier
        tier: "standard" | "high_value" | "very_high"

    Returns:
        e.g. "cts-humanreview-highvalue-saraswat-coop"

    Raises:
        ValueError: if tier is not one of the three valid tiers
    """
    if tier not in _VALID_TIERS:
        raise ValueError(
            f"Unknown queue tier {tier!r}. Valid tiers: {_VALID_TIERS}"
        )
    _HR_SUFFIXES = {
        "standard":   "standard",
        "high_value": "highvalue",
        "very_high":  "veryhigh",
    }
    return f"cts-humanreview-{_HR_SUFFIXES[tier]}-{bank_id}"
