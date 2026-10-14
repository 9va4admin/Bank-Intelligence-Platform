"""Statistics behind 'does this meet the bank's bar'. With small samples a point estimate proves nothing."""
import math

import pytest

from modules.cts.evaluation.stats import wilson_interval, required_n_for_error_bound, verdict


def test_wilson_interval_known_values():
    lo, hi = wilson_interval(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)


def test_wilson_interval_perfect_score_still_has_uncertainty():
    lo, hi = wilson_interval(70, 70)
    assert hi == pytest.approx(1.0, abs=1e-9) and 0.94 < lo < 0.96        # 70/70 does NOT demonstrate 99%


def test_wilson_interval_empty_sample_is_uninformative():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_required_sample_size_for_99_percent_with_zero_errors():
    # rule of three: to show error < 1% at 95% confidence with no errors you need ~299 clean samples
    assert 295 <= required_n_for_error_bound(0.01) <= 300


def test_required_sample_size_scales_inversely_with_the_error_bound():
    assert required_n_for_error_bound(0.03) < required_n_for_error_bound(0.01) < required_n_for_error_bound(0.001)


@pytest.mark.parametrize("k,n,target,expected", [
    (700, 700, 0.99, "MEETS"),                 # lower bound above target
    (69, 70, 0.99, "NOT DEMONSTRABLE"),        # point estimate 98.6% < 99%: honest "below"? -> below point estimate
])
def test_verdict_higher_is_better(k, n, target, expected):
    v = verdict(k, n, target, higher_is_better=True)
    assert v.startswith("MEETS") if expected == "MEETS" else v.startswith(("BELOW", "NOT DEMONSTRABLE"))


def test_verdict_point_estimate_meets_but_interval_too_wide():
    assert verdict(70, 70, 0.99, higher_is_better=True).startswith("NOT DEMONSTRABLE")


def test_verdict_clearly_below_target():
    assert verdict(50, 100, 0.99, higher_is_better=True).startswith("BELOW")


def test_verdict_lower_is_better_for_error_rates():
    assert verdict(0, 1000, 0.01, higher_is_better=False).startswith("MEETS")
    assert verdict(50, 100, 0.03, higher_is_better=False).startswith("BELOW")


def test_verdict_with_no_data_is_not_assessable():
    assert verdict(0, 0, 0.99, higher_is_better=True).startswith("NOT ASSESSABLE")
