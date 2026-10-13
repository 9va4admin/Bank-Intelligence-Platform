"""Scoring of inward results against by-eye truth, against the bank's accuracy targets."""
from modules.cts.evaluation.inward_eval import Row, score, NFR_TARGETS


def _r(**kw):
    base = dict(key="K1", lot="Lot 1", truth_type="CHQ", read_type="CHQ", truth_payee="Anjali", read_payee="Anjali",
                payee_withheld=False, payee_scored=True, truth_micr9="110052005", read_micr9="110052005",
                truth_num="080654", read_num="080654", truth_amount="12202", read_amount="12202.00",
                decision="HUMAN_REVIEW", truth_should_return=False)
    base.update(kw)
    return Row(**base)


def _m(res, name):
    return next(m for m in res.metrics if m.name == name)


def test_all_correct_gives_full_marks_and_no_wrong_shown():
    res = score([_r(), _r(key="K2")])
    assert _m(res, "instrument type (cheque vs DD)").k == 2
    assert _m(res, "payee: wrong value SHOWN").k == 0


def test_a_wrong_payee_that_is_shown_is_the_critical_failure():
    res = score([_r(read_payee="Anjalee")])
    assert _m(res, "payee: wrong value SHOWN").k == 1
    assert _m(res, "payee: exact").k == 0


def test_a_withheld_payee_is_safe_but_not_exact():
    res = score([_r(read_payee=None, payee_withheld=True)])
    assert _m(res, "payee: wrong value SHOWN").k == 0
    assert _m(res, "payee: withheld for review").k == 1


def test_unscored_payees_are_excluded_not_counted_wrong():
    res = score([_r(payee_scored=False, read_payee="garbage")])
    assert _m(res, "payee: exact").n == 0


def test_amount_is_compared_as_a_number_not_a_string():
    assert _m(score([_r(read_amount="12,202.00")]), "amount figures correct").k == 1
    assert _m(score([_r(read_amount="12,203.00")]), "amount figures correct").k == 0


def test_an_unread_sort_code_is_not_a_wrong_one():
    res = score([_r(read_micr9=None)])
    assert _m(res, "9-digit sort code: wrong value READ").k == 0
    assert _m(res, "9-digit sort code correct").k == 0


def test_wrong_automatic_return_is_counted_when_truth_says_the_cheque_was_returnable_not():
    res = score([_r(decision="STP_RETURN", truth_should_return=False), _r(key="K2", decision="STP_RETURN", truth_should_return=True)])
    m = _m(res, "automatic returns that were WRONG")
    assert (m.k, m.n) == (1, 2)


def test_targets_come_from_the_documented_nfrs():
    assert NFR_TARGETS["ocr_field_accuracy"] == 0.99
    assert NFR_TARGETS["signature_precision"] == 0.97
    assert NFR_TARGETS["fraud_f1"] == 0.92
    assert NFR_TARGETS["false_positive"] == 0.03 and NFR_TARGETS["false_negative"] == 0.01


def test_rows_without_amount_truth_are_not_counted_as_correct_amounts():
    res = score([_r(truth_amount="", read_amount=None), _r(key="K2", truth_amount="12202", read_amount="12202.00")])
    m = _m(res, "amount figures correct")
    assert (m.k, m.n) == (1, 1)


def test_wrong_reads_are_named_read_not_shown_because_later_gates_may_catch_them():
    names = {m.name for m in score([_r()]).metrics}
    assert "cheque/DD number: wrong value READ" in names and "amount figures: wrong value READ" in names
