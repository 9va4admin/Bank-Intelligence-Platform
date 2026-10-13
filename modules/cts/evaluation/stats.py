"""Small-sample statistics for the inward evaluation. Pure, dependency-free."""
from __future__ import annotations

import math

_Z95 = 1.959964


def wilson_interval(k: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials. (0, 1) when n == 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def required_n_for_error_bound(max_error: float, confidence: float = 0.95) -> int:
    """Clean (error-free) samples needed to show the true error rate is below max_error."""
    return math.ceil(math.log(1 - confidence) / math.log(1 - max_error))


def verdict(k: int, n: int, target: float, higher_is_better: bool) -> str:
    """Honest verdict of k/n against a target rate.

    higher_is_better=True : accuracy-style target (rate must be >= target)
    higher_is_better=False: error-style target (rate must be <= target)
    MEETS only when the 95% interval clears the target; a point estimate that meets it on too few samples is
    NOT DEMONSTRABLE, and one that does not is BELOW."""
    if n <= 0:
        return "NOT ASSESSABLE (no data)"
    lo, hi = wilson_interval(k, n)
    rate = k / n
    if higher_is_better:
        if lo >= target:
            return f"MEETS (95% CI lower bound {lo:.1%} >= {target:.1%})"
        if rate >= target:
            return f"NOT DEMONSTRABLE at n={n} (point estimate {rate:.1%} meets {target:.1%}, interval {lo:.1%}-{hi:.1%})"
        return f"BELOW target ({rate:.1%} < {target:.1%}; interval {lo:.1%}-{hi:.1%})"
    if hi <= target:
        return f"MEETS (95% CI upper bound {hi:.1%} <= {target:.1%})"
    if rate <= target:
        return f"NOT DEMONSTRABLE at n={n} (point estimate {rate:.1%} meets {target:.1%}, interval {lo:.1%}-{hi:.1%})"
    return f"BELOW target ({rate:.1%} > {target:.1%}; interval {lo:.1%}-{hi:.1%})"
