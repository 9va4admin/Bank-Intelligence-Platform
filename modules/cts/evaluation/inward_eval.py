"""Score inward results against ground truth and hold them to the documented accuracy targets.

NFR targets (CLAUDE.md section 12): OCR > 99.0%, signature precision > 97.0%, fraud F1 > 0.92,
false positive < 3%, false negative < 1%. Two numbers matter more than raw accuracy in a bank:
how often a WRONG value is shown/used (the dangerous error) versus withheld for human review (the costly one).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from modules.cts.evaluation.stats import verdict, wilson_interval
from shared.messages import get_message

NFR_TARGETS = {
    "ocr_field_accuracy": 0.99,
    "signature_precision": 0.97,
    "fraud_f1": 0.92,
    "false_positive": 0.03,
    "false_negative": 0.01,
}


@dataclass
class Row:
    key: str
    lot: str
    truth_type: str                      # "CHQ" | "DD"
    read_type: str                       # "CHQ" | "DD"
    truth_payee: str
    read_payee: Optional[str]
    payee_withheld: bool                 # the pipeline refused to show a payee (two reads disagreed)
    payee_scored: bool                   # False for Indic-script handwriting and uncertain truth
    truth_micr9: str
    read_micr9: Optional[str]
    truth_num: str
    read_num: Optional[str]
    truth_amount: str                    # digits only
    read_amount: Optional[str]
    decision: str
    truth_should_return: Optional[bool]  # True/False when verifiable from truth, None when it is not


@dataclass
class Metric:
    name: str
    k: int
    n: int
    target: Optional[float] = None
    higher_is_better: bool = True
    critical: bool = False               # a wrong value shown / used: the dangerous error class
    note: str = ""

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson_interval(self.k, self.n)

    @property
    def verdict(self) -> str:
        if self.target is None:
            return "(no target defined)"
        return verdict(self.k, self.n, self.target, self.higher_is_better)


@dataclass
class EvalResult:
    metrics: list[Metric] = field(default_factory=list)


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", re.sub(r"null", "", (s or ""), flags=re.I).upper())


def _digits(s: Optional[str]) -> str:
    """Integer part of an amount as digits: '12,202.00' -> '12202'."""
    return re.sub(r"[^\d]", "", str(s or "").split(".")[0])


def score(rows: list[Row]) -> EvalResult:
    ocr, err = NFR_TARGETS["ocr_field_accuracy"], 1 - NFR_TARGETS["ocr_field_accuracy"]
    res = EvalResult()
    add = lambda *a, **kw: res.metrics.append(Metric(*a, **kw))

    add("instrument type (cheque vs DD)", sum(r.read_type == r.truth_type for r in rows), len(rows), ocr)

    ps = [r for r in rows if r.payee_scored]
    exact = sum(1 for r in ps if r.read_payee and not r.payee_withheld and _norm(r.read_payee) == _norm(r.truth_payee))
    shown_wrong = sum(1 for r in ps if r.read_payee and not r.payee_withheld and _norm(r.read_payee) != _norm(r.truth_payee))
    withheld = sum(1 for r in ps if r.payee_withheld or not r.read_payee)
    add("payee: exact", exact, len(ps), ocr, note=get_message("CTS_LATIN_SCRIPT_PAYEES_WITH_RELIABLE"))
    add("payee: wrong value SHOWN", shown_wrong, len(ps), err, higher_is_better=False, critical=True)
    add("payee: withheld for review", withheld, len(ps), note=get_message("CTS_THE_COST_SIDE_HANDLED_BY"))

    add("9-digit sort code correct", sum(r.read_micr9 == r.truth_micr9 for r in rows), len(rows), ocr)
    add("9-digit sort code: wrong value READ", sum(1 for r in rows if r.read_micr9 and r.read_micr9 != r.truth_micr9),
        len(rows), err, higher_is_better=False, critical=True,
        note=get_message("CTS_READ_WRONGLY_THE_PRESENTED_NUMBER"))
    add("cheque/DD number correct", sum(r.read_num == r.truth_num for r in rows), len(rows), ocr)
    add("cheque/DD number: wrong value READ", sum(1 for r in rows if r.read_num and r.read_num != r.truth_num),
        len(rows), err, higher_is_better=False, critical=True)
    am = [r for r in rows if r.truth_amount]          # only rows whose amount truth exists
    add("amount figures correct", sum(_digits(r.read_amount) == _digits(r.truth_amount) for r in am), len(am), ocr)
    add("amount figures: wrong value READ",
        sum(1 for r in am if r.read_amount and _digits(r.read_amount) != _digits(r.truth_amount)),
        len(am), err, higher_is_better=False, critical=True,
        note=get_message("CTS_READ_WRONGLY_FIGURES_VS_WORDS"))

    returns = [r for r in rows if r.decision == "STP_RETURN" and r.truth_should_return is not None]
    add("automatic returns that were WRONG", sum(1 for r in returns if r.truth_should_return is False), len(returns),
        err, higher_is_better=False, critical=True,
        note=get_message("CTS_ONLY_RETURNS_WHOSE_CORRECTNESS_IS"))
    return res
