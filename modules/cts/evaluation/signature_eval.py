"""Signature-verifier evaluation: how often does a signature embedder accept a forgery, and reject a genuine signature?

Pure maths on vectors (no model, no images), so any embedder (the generic stand-in, a trained Siamese network, a vendor model) can be
scored on the same labelled data and compared.

Protocol, matching how the verifier scores in production (modules/cts/workflows/activities/signature.py): a writer is enrolled with k
genuine specimens; a trial's score is the BEST cosine similarity to any enrolment vector. Genuine trials are the writer's remaining genuine
samples; forgery trials are that writer's labelled SKILLED_FORGERY samples and other writers' genuine signatures (RANDOM_FORGERY).

FAR = forgeries accepted / forgery trials (the dangerous error); FRR = genuine rejected / genuine trials (the costly one: reviewer workload).
Every rate carries a 95% Wilson interval, and nothing is called "meets" unless the interval clears the target (see stats.verdict).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Sequence

from modules.cts.evaluation.stats import required_n_for_error_bound, verdict, wilson_interval

GENUINE = "GENUINE"
SKILLED = "SKILLED_FORGERY"
RANDOM = "RANDOM_FORGERY"
_FORGERY_KINDS = (SKILLED, RANDOM)


@dataclass(frozen=True)
class SigSample:
    writer_id: str
    label: str                 # GENUINE | SKILLED_FORGERY
    vector: Sequence[float]


@dataclass(frozen=True)
class Trial:
    writer_id: str
    kind: str                  # GENUINE | SKILLED_FORGERY | RANDOM_FORGERY
    score: float


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.k, self.n)

    def as_dict(self) -> dict:
        lo, hi = self.interval
        return {"k": self.k, "n": self.n, "rate": round(self.rate, 6), "ci95": [round(lo, 6), round(hi, 6)]}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def build_trials(
    samples: Sequence[SigSample], k_enrol: int, seed: int = 0, max_random_per_writer: int = 50,
) -> tuple[list[Trial], list[str]]:
    """Returns (trials, skipped_writer_ids). A writer needs more than k_enrol genuine samples (at least one left to test)."""
    rng = random.Random(seed)
    genuine: dict[str, list[SigSample]] = {}
    skilled: dict[str, list[SigSample]] = {}
    for s in samples:
        (genuine if s.label == GENUINE else skilled).setdefault(s.writer_id, []).append(s)

    writers = sorted(genuine)
    enrol: dict[str, list[SigSample]] = {}
    test_genuine: dict[str, list[SigSample]] = {}
    skipped: list[str] = []
    for w in writers:
        pool = list(genuine[w])
        rng.shuffle(pool)
        if len(pool) <= k_enrol:
            skipped.append(w)
            continue
        enrol[w], test_genuine[w] = pool[:k_enrol], pool[k_enrol:]

    def best(w: str, vector: Sequence[float]) -> float:
        return max(cosine(vector, e.vector) for e in enrol[w])

    trials: list[Trial] = []
    for w in enrol:
        trials += [Trial(w, GENUINE, best(w, g.vector)) for g in test_genuine[w]]
        trials += [Trial(w, SKILLED, best(w, f.vector)) for f in skilled.get(w, [])]
        others = [g for o in writers if o != w for g in genuine[o]]
        rng.shuffle(others)
        trials += [Trial(w, RANDOM, best(w, g.vector)) for g in others[:max_random_per_writer]]
    return trials, skipped


def far_frr_at(trials: Sequence[Trial], threshold: float, kinds: Sequence[str] = _FORGERY_KINDS) -> tuple[Rate, Rate]:
    """(FAR over the chosen forgery kinds, FRR over genuine trials) when a score >= threshold is accepted."""
    forged = [t for t in trials if t.kind in kinds]
    genuine = [t for t in trials if t.kind == GENUINE]
    return (Rate(sum(1 for t in forged if t.score >= threshold), len(forged)),
            Rate(sum(1 for t in genuine if t.score < threshold), len(genuine)))


def _thresholds(trials: Sequence[Trial]) -> list[float]:
    scores = sorted({t.score for t in trials})
    return scores + [scores[-1] + 1e-9] if scores else []


def equal_error_rate(trials: Sequence[Trial], kinds: Sequence[str] = _FORGERY_KINDS) -> float:
    """The error rate where FAR and FRR meet (mean of the two at the closest threshold). 0.5 means no separation at all."""
    best_gap, best = None, 0.5
    for th in _thresholds(trials):
        far, frr = far_frr_at(trials, th, kinds)
        if far.n == 0 or frr.n == 0:
            continue
        gap = abs(far.rate - frr.rate)
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, (far.rate + frr.rate) / 2
    return best


def threshold_for_far(trials: Sequence[Trial], max_far: float, kinds: Sequence[str] = _FORGERY_KINDS) -> tuple[float, Rate, Rate]:
    """The least strict threshold whose FAR is at most max_far (lowest FRR that still meets the target): (threshold, FAR, FRR)."""
    for th in _thresholds(trials):
        far, frr = far_frr_at(trials, th, kinds)
        if far.n and far.rate <= max_far:
            return th, far, frr
    th = (max((t.score for t in trials), default=1.0)) + 1e-9
    far, frr = far_frr_at(trials, th, kinds)
    return th, far, frr


def evaluate(
    samples: Sequence[SigSample], k_enrol: int, threshold: float, max_far: Optional[float] = None, seed: int = 0,
) -> dict:
    """Full report for one embedder on one labelled dataset. `verdict` is only given when a FAR target is supplied."""
    trials, skipped = build_trials(samples, k_enrol, seed)
    report: dict = {
        "k_enrol": k_enrol, "threshold": threshold, "max_far": max_far,
        "writers_evaluated": len({t.writer_id for t in trials}), "writers_skipped_too_few_genuine": skipped,
        "by_kind": {},
        "clean_forgery_trials_needed_for_1pct": required_n_for_error_bound(0.01),
    }
    for kind in _FORGERY_KINDS:
        far, frr = far_frr_at(trials, threshold, (kind,))
        if far.n == 0:
            continue
        entry = {"far": far.as_dict(), "frr": frr.as_dict(), "equal_error_rate": round(equal_error_rate(trials, (kind,)), 6),
                 "verdict": verdict(far.k, far.n, max_far, higher_is_better=False) if max_far is not None else None}
        if max_far is not None:
            th, tfar, tfrr = threshold_for_far(trials, max_far, (kind,))
            entry["threshold_for_target_far"] = {"threshold": round(th, 6), "far": tfar.as_dict(), "frr": tfrr.as_dict()}
        report["by_kind"][kind] = entry
    return report
