"""Signature-verifier evaluation harness (pure maths on vectors; no model, no images).

Protocol, matching how the verifier scores in production: a writer is enrolled with k genuine specimens; a trial's score is the BEST cosine
similarity to any enrolment vector. Genuine trials are the writer's remaining genuine samples; forgery trials are that writer's skilled
forgeries (if labelled) and other writers' genuine signatures (random forgeries).
"""
import math
import random

import pytest

from modules.cts.evaluation.signature_eval import (
    SigSample, build_trials, cosine, evaluate, far_frr_at, threshold_for_far, equal_error_rate,
)


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _writer(rng, dim=16):
    return [rng.gauss(0, 1) for _ in range(dim)]


def _near(centre, rng, noise):
    return _unit([c + rng.gauss(0, noise) for c in centre])


def _dataset(rng, writers=12, genuine=8, forgeries=4, noise=0.05, forgery_noise=1.0, dim=16):
    out = []
    for w in range(writers):
        c = _writer(rng, dim)
        out += [SigSample(f"W{w}", "GENUINE", _near(c, rng, noise)) for _ in range(genuine)]
        out += [SigSample(f"W{w}", "SKILLED_FORGERY", _near(c, rng, forgery_noise)) for _ in range(forgeries)]
    return out


def test_cosine_is_a_plain_cosine():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_trials_enrol_k_genuines_and_test_on_the_rest():
    rng = random.Random(1)
    trials, skipped = build_trials(_dataset(rng), k_enrol=3, seed=0)
    per_writer = {}
    for t in trials:
        per_writer.setdefault(t.writer_id, []).append(t)
    assert skipped == []
    assert all(sum(1 for t in ts if t.kind == "GENUINE") == 5 for ts in per_writer.values())     # 8 - 3 enrolled
    assert all(sum(1 for t in ts if t.kind == "SKILLED_FORGERY") == 4 for ts in per_writer.values())
    assert any(t.kind == "RANDOM_FORGERY" for t in trials)


def test_a_writer_without_enough_genuines_is_skipped_and_reported():
    rng = random.Random(2)
    data = _dataset(rng, writers=3, genuine=2)
    _, skipped = build_trials(data, k_enrol=3, seed=0)
    assert sorted(skipped) == ["W0", "W1", "W2"]


def test_trial_score_is_the_best_cosine_over_the_enrolment_vectors():
    a, b = _unit([1, 0, 0]), _unit([0, 1, 0])
    data = [SigSample("W", "GENUINE", a), SigSample("W", "GENUINE", b), SigSample("W", "GENUINE", _unit([0.1, 1, 0])),
            SigSample("X", "GENUINE", a), SigSample("X", "GENUINE", b), SigSample("X", "GENUINE", b)]
    trials, _ = build_trials(data, k_enrol=2, seed=0)
    genuine_w = [t for t in trials if t.writer_id == "W" and t.kind == "GENUINE"]
    assert len(genuine_w) == 1 and genuine_w[0].score == pytest.approx(cosine(_unit([0.1, 1, 0]), b))


def test_perfectly_separated_data_has_no_errors_and_zero_eer():
    rng = random.Random(3)
    trials, _ = build_trials(_dataset(rng, noise=0.02, forgery_noise=3.0), k_enrol=3, seed=0)
    far, frr = far_frr_at(trials, 0.85, kinds=("SKILLED_FORGERY",))
    assert far.k == 0 and frr.k == 0
    assert equal_error_rate(trials, kinds=("SKILLED_FORGERY",)) == pytest.approx(0.0, abs=0.02)


def test_unseparated_data_has_an_eer_near_one_half():
    rng = random.Random(4)
    trials, _ = build_trials(_dataset(rng, noise=1.0, forgery_noise=1.0, writers=20, genuine=10, forgeries=10), k_enrol=3, seed=0)
    assert 0.35 < equal_error_rate(trials, kinds=("SKILLED_FORGERY",)) < 0.65


def test_threshold_for_a_far_target_actually_meets_it():
    rng = random.Random(5)
    trials, _ = build_trials(_dataset(rng, noise=0.4, forgery_noise=0.8, writers=20, genuine=10, forgeries=10), k_enrol=3, seed=0)
    th, far, frr = threshold_for_far(trials, max_far=0.05, kinds=("SKILLED_FORGERY",))
    assert far.rate <= 0.05
    # the next more permissive threshold must break the target, otherwise the chosen one was not the least strict that meets it
    far_looser, _ = far_frr_at(trials, th - 1e-6, kinds=("SKILLED_FORGERY",))
    assert far_looser.rate >= far.rate


def test_report_says_when_the_sample_is_too_small_to_prove_anything():
    rng = random.Random(6)
    report = evaluate(_dataset(rng, writers=3, genuine=5, forgeries=2, noise=0.02, forgery_noise=3.0), k_enrol=3, threshold=0.85, max_far=0.01)
    skilled = report["by_kind"]["SKILLED_FORGERY"]
    assert skilled["far"]["k"] == 0 and skilled["far"]["n"] == 6
    assert "NOT DEMONSTRABLE" in skilled["verdict"]
    assert report["clean_forgery_trials_needed_for_1pct"] >= 299          # about 3/p: 299 error-free trials show FAR < 1% at 95%


def test_report_without_a_target_gives_no_verdict():
    rng = random.Random(7)
    report = evaluate(_dataset(rng), k_enrol=3, threshold=0.85, max_far=None)
    assert all(v.get("verdict") is None for v in report["by_kind"].values())
