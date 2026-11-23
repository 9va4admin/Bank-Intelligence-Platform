"""Scoring for the OCR / vision-language model bake-off (docs/research/ocr-bakeoff-plan.md).

Pure functions: no model, no network, no file access. Every threshold (the length guard, the agreement similarity, the bootstrap size and seed) is a required argument,
because in real use they come from settings, never from a literal here.

What it answers, per model, field and stratum (script, handwritten or printed, scan quality):
  - how often the value shown is exactly right, **wrong** (the dangerous error: it reaches a screen or a decision) or **withheld** (empty, failed, or a runaway output);
  - the character error rate and how often the answer was in the wrong script;
  - whether one model is better than another on the SAME items (exact McNemar test, paired bootstrap);
  - for a primary reader plus an independent second reader of a different model family: how many items are shown correct, shown wrong while both agree on the wrong value,
    or sent to a human, using the same "two reads must agree" idea as the production re-read gate but comparing letters in every script.
"""
from __future__ import annotations

import difflib
import math
import random
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional, Sequence

from modules.cts.evaluation.stats import wilson_interval
from shared.messages import get_message

# -------------------------------------------------------------------------- data

AMOUNT_FIELDS = frozenset({"amount_figures"})
_SCRIPT_NAMES = ("LATIN", "DEVANAGARI", "KANNADA", "TAMIL", "TELUGU", "MALAYALAM", "BENGALI", "GUJARATI", "GURMUKHI", "ORIYA")
_SCRIPT_LABEL = {"ORIYA": "ODIA"}
_EMPTY_TOKENS = frozenset({"", "null", "none", "n/a"})


@dataclass(frozen=True)
class Truth:
    item_id: str
    field: str
    text: str
    script: str                 # the expected script of the value: LATIN, KANNADA, DEVANAGARI ... or NONE (numbers)
    handwritten: bool
    quality: str                # e.g. "good" or "poor"
    scoreable: bool = True      # False when the truth is uncertain: such items are left out


@dataclass(frozen=True)
class Reading:
    item_id: str
    field: str
    model: str
    text: Optional[str]
    failed: bool = False        # the model call failed or returned nothing usable
    latency_ms: Optional[float] = None


@dataclass(frozen=True)
class Classified:
    outcome: str                # EXACT | WRONG_SHOWN | WITHHELD
    cer: float
    guard_tripped: bool
    script_wrong: bool


@dataclass(frozen=True)
class FieldScore:
    model: str
    field: str
    stratum: str
    dimension: str              # which split the stratum belongs to: all, script, handwritten or quality
    n: int
    exact: int
    wrong_shown: int
    withheld: int
    guard_tripped: int
    script_wrong: int
    mean_cer: float
    exact_ci: tuple[float, float]
    wrong_shown_ci: tuple[float, float]


@dataclass(frozen=True)
class McNemarResult:
    a_only: int                 # items only model A got right
    b_only: int
    pairs: int                  # items both models have a result for
    p_value: float


@dataclass(frozen=True)
class BootstrapDiff:
    diff: float
    lo: float
    hi: float


@dataclass(frozen=True)
class PairResult:
    primary_model: str
    second_model: str
    field: str
    n: int
    agree_correct: int
    wrong_shown: int            # both readers agree and the value is wrong
    review_primary_correct: int  # disagreement (or no second read) sent a correct primary read to a human
    review_primary_wrong: int   # disagreement caught a wrong primary read
    review_primary_unread: int  # the primary read nothing

    @property
    def wrong_shown_rate(self) -> float:
        return self.wrong_shown / self.n if self.n else 0.0

    @property
    def review_rate(self) -> float:
        return (self.review_primary_correct + self.review_primary_wrong + self.review_primary_unread) / self.n if self.n else 0.0


# -------------------------------------------------------------------------- text

def detect_script(text: Optional[str]) -> str:
    """The script most of the letters belong to (LATIN, KANNADA, DEVANAGARI ...), OTHER for any other script, NONE when there are no letters."""
    counts: dict[str, int] = {}
    for ch in text or "":
        if unicodedata.category(ch)[0] not in ("L", "M"):
            continue
        try:
            word = unicodedata.name(ch).split(" ", 1)[0]
        except ValueError:
            continue
        key = word if word in _SCRIPT_NAMES else "OTHER"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "NONE"
    top = max(counts, key=lambda k: counts[k])
    return _SCRIPT_LABEL.get(top, top)


def normalise_text(text: Optional[str]) -> str:
    """Make equal text equal: composed Unicode, lower case, digits of any script as 0-9, no zero-width marks, no punctuation, single spaces."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", text or ""):
        cat = unicodedata.category(ch)
        if cat == "Cf":
            continue
        if cat == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        elif cat[0] in ("P", "S", "Z", "C"):
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out).casefold()).strip()


def normalise_amount(text: Optional[str]) -> Optional[Decimal]:
    """An amount as a number, whatever the decoration (Rs., rupee sign, commas in any grouping, /-, only, digits of any script). None when there is no number, or more than one."""
    if not text:
        return None
    ascii_digits = "".join(str(unicodedata.decimal(ch)) if unicodedata.category(ch) == "Nd" else ch for ch in unicodedata.normalize("NFC", text))
    tokens = re.findall(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?", ascii_digits)
    if len(tokens) != 1:
        return None
    try:
        return Decimal(tokens[0].replace(",", ""))
    except InvalidOperation:
        return None


def _letters(text: Optional[str]) -> str:
    return "".join(ch for ch in normalise_text(text) if unicodedata.category(ch)[0] in ("L", "M", "N"))


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(truth: Optional[str], read: Optional[str]) -> float:
    """Character error rate against the truth (edits over truth length, spaces and punctuation ignored), capped at 1.0 so a long wrong answer is no worse than a wrong one."""
    t, r = _letters(truth), _letters(read)
    if not t:
        return 0.0 if not r else 1.0
    return min(1.0, _edit_distance(t, r) / len(t))


def names_agree(a: Optional[str], b: Optional[str], min_similarity: float) -> bool:
    """Two reads agree when their letters match closely enough, in ANY script. (The production re-read rule keeps only A-Z and digits, so it reduces Kannada or Hindi to
    nothing and can never agree: it always sends Indic payees to a human. This comparison does not have that limit.)"""
    la, lb = _letters(a), _letters(b)
    if not la or not lb:
        return False
    return difflib.SequenceMatcher(None, la, lb).ratio() >= min_similarity


# -------------------------------------------------------------------------- one reading

def _is_empty(text: Optional[str]) -> bool:
    return (text or "").strip().casefold() in _EMPTY_TOKENS


def classify(truth: Truth, reading: Optional[Reading], *, guard_multiple: int, guard_min_chars: int) -> Classified:
    """EXACT, WRONG_SHOWN (a value was produced and it is wrong) or WITHHELD (nothing usable, a failed call, no reading at all, or a runaway output)."""
    if reading is None or reading.failed or _is_empty(reading.text):
        return Classified("WITHHELD", 1.0, False, False)
    text = reading.text or ""
    if len(text) > guard_multiple * max(len(truth.text), guard_min_chars):
        return Classified("WITHHELD", 1.0, True, False)
    if truth.field in AMOUNT_FIELDS:
        want, got = normalise_amount(truth.text), normalise_amount(text)
        exact = want is not None and got is not None and want == got
        return Classified("EXACT" if exact else "WRONG_SHOWN", 0.0 if exact else 1.0, False, False)
    exact = normalise_text(truth.text) == normalise_text(text)
    wrong_script = truth.script not in ("NONE", "OTHER") and detect_script(text) not in (truth.script, "NONE")
    return Classified("EXACT" if exact else "WRONG_SHOWN", cer(truth.text, text), False, wrong_script)


# -------------------------------------------------------------------------- scoring

def _stratum_value(truth: Truth, key: str) -> str:
    if key == "script":
        return truth.script
    if key == "handwritten":
        return "HANDWRITTEN" if truth.handwritten else "PRINTED"
    if key == "quality":
        return truth.quality.upper()
    raise ValueError(key)


def _index(readings: Iterable[Reading]) -> dict[tuple[str, str, str], Reading]:
    return {(r.model, r.item_id, r.field): r for r in readings}


def score(truths: Sequence[Truth], readings: Sequence[Reading], *, models: Sequence[str], by: Sequence[str], guard_multiple: int, guard_min_chars: int) -> list[FieldScore]:
    """One row per model, field and stratum (each value of each `by` key, plus ALL). Items whose truth is not scoreable are left out; a scoreable item with no reading counts as withheld."""
    index = _index(readings)
    rows: list[FieldScore] = []
    scoreable = [t for t in truths if t.scoreable]
    fields = sorted({t.field for t in scoreable})
    for model in models:
        for field in fields:
            items = [t for t in scoreable if t.field == field]
            groups: dict[tuple[str, str], list[Truth]] = {("all", "ALL"): items}
            for key in by:
                for t in items:
                    groups.setdefault((key, _stratum_value(t, key)), []).append(t)
            for (dimension, stratum), members in groups.items():
                out = [classify(t, index.get((model, t.item_id, field)), guard_multiple=guard_multiple, guard_min_chars=guard_min_chars) for t in members]
                n = len(out)
                exact = sum(c.outcome == "EXACT" for c in out)
                wrong = sum(c.outcome == "WRONG_SHOWN" for c in out)
                rows.append(FieldScore(model=model, field=field, stratum=stratum, dimension=dimension, n=n, exact=exact, wrong_shown=wrong, withheld=n - exact - wrong,
                                       guard_tripped=sum(c.guard_tripped for c in out), script_wrong=sum(c.script_wrong for c in out),
                                       mean_cer=sum(c.cer for c in out) / n if n else 0.0, exact_ci=wilson_interval(exact, n), wrong_shown_ci=wilson_interval(wrong, n)))
    return rows


# -------------------------------------------------------------------------- paired comparison

def mcnemar(correct_a: dict[str, bool], correct_b: dict[str, bool]) -> McNemarResult:
    """Exact two-sided McNemar test on the items both models have a result for: only the items where exactly one model is right carry information."""
    shared = set(correct_a) & set(correct_b)
    a_only = sum(1 for k in shared if correct_a[k] and not correct_b[k])
    b_only = sum(1 for k in shared if correct_b[k] and not correct_a[k])
    n = a_only + b_only
    if n == 0:
        return McNemarResult(a_only, b_only, len(shared), 1.0)
    tail = sum(math.comb(n, i) for i in range(0, min(a_only, b_only) + 1)) / 2 ** n
    return McNemarResult(a_only, b_only, len(shared), min(1.0, 2 * tail))


def paired_bootstrap_diff(a: Sequence[int], b: Sequence[int], *, resamples: int, seed: int) -> BootstrapDiff:
    """Mean of a minus mean of b over the same items, with a 95% percentile interval from resampling the items (the seed makes it repeatable)."""
    if len(a) != len(b) or not a:
        raise ValueError(get_message("CTS_A_AND_B_MUST_BE"))
    n = len(a)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    return BootstrapDiff(diff=sum(a[i] - b[i] for i in range(n)) / n, lo=diffs[int(0.025 * (resamples - 1))], hi=diffs[int(0.975 * (resamples - 1))])


# -------------------------------------------------------------------------- the pair

def cross_family_pairs(families: dict[str, str]) -> list[tuple[str, str]]:
    """Every ordered (primary, second) pair of models from DIFFERENT families: two models from one family tend to fail the same way, so they make a poor pair."""
    return [(p, s) for p in families for s in families if p != s and families[p] != families[s]]


def pair_analysis(truths: Sequence[Truth], primary: Sequence[Reading], second: Sequence[Reading], *, primary_model: str, second_model: str, field: str, min_similarity: float,
                  guard_multiple: int, guard_min_chars: int) -> PairResult:
    """What the bank would see for each item when the primary read is shown only if the second reader agrees: shown correct, shown wrong because both agree on a wrong value
    (the dangerous case), or sent to a human (with or without the primary being right)."""
    p_index, s_index = _index(primary), _index(second)
    items = [t for t in truths if t.scoreable and t.field == field]
    agree_correct = wrong_shown = review_ok = review_wrong = unread = 0
    for t in items:
        p = p_index.get((primary_model, t.item_id, field))
        s = s_index.get((second_model, t.item_id, field))
        cp = classify(t, p, guard_multiple=guard_multiple, guard_min_chars=guard_min_chars)
        cs = classify(t, s, guard_multiple=guard_multiple, guard_min_chars=guard_min_chars)
        if cp.outcome == "WITHHELD":
            unread += 1
            continue
        if cs.outcome == "WITHHELD":
            agreed = False
        elif field in AMOUNT_FIELDS:
            agreed = normalise_amount(p.text) == normalise_amount(s.text) and normalise_amount(p.text) is not None
        else:
            agreed = names_agree(p.text, s.text, min_similarity)
        if agreed:
            if cp.outcome == "EXACT":
                agree_correct += 1
            else:
                wrong_shown += 1
        elif cp.outcome == "EXACT":
            review_ok += 1
        else:
            review_wrong += 1
    return PairResult(primary_model, second_model, field, len(items), agree_correct, wrong_shown, review_ok, review_wrong, unread)
