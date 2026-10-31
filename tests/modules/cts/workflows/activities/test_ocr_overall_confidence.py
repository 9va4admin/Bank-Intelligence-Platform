"""overall_confidence is the outward CTS-2010 quality score (IQA and MICR band legibility use it).

Found on the first live outward run (2026-10-31): a cheque whose six read fields were all ~0.95 scored 0.75 and was rejected
for MICR band legibility, because fields the cheque does not need (account number, drawee name, category) were averaged in as 0.0.
An optional field that was not returned is not an unreadable one. A mandatory field that came back empty still counts as 0."""
import pytest

from modules.cts.workflows.activities.ocr import OCRActivityInput, _build_result


def _inp():
    return OCRActivityInput(instrument_id="I1", bank_id="b", image_url="s3://b/k.tif")


def _six(**over):
    f = {"micr_line": ("500025033290062", 0.97), "amount_figures": ("95000", 0.96), "amount_words": ("Ninety Five Thousand Only", 0.95),
         "date": ("25-08-2026", 0.98), "payee": ("Pradeep Kumar", 0.94), "ifsc_code": ("SYNB0003011", 0.92)}
    f.update(over)
    return f


def _overall(fields):
    return _build_result(fields, 0.5, 1, [], None, _inp()).overall_confidence


def test_optional_fields_that_were_not_returned_do_not_drag_the_score_down():
    absent = {"account_number": (None, 0.0), "drawee_name": (None, 0.0), "instrument_category": (None, 0.0)}
    assert _overall({**_six(), **absent}) == pytest.approx(_overall(_six()))
    assert _overall({**_six(), **absent}) > 0.9


def test_a_mandatory_field_that_came_back_empty_still_counts_as_zero():
    with_payee_lost = _overall(_six(payee=(None, 0.0)))
    assert with_payee_lost < _overall(_six()) - 0.1


def test_an_optional_field_that_was_returned_counts_with_its_confidence():
    assert _overall({**_six(), "account_number": ("4242424242", 0.20)}) < _overall(_six())
