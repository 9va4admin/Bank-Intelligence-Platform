"""Shared cheque-date parser. Found by the real outward run: the OCR model returned the
printed 8-box date correctly ("09102026") every time, but both workflow parsers only
knew separator formats, so 16 of 19 outward cheques were rejected as UNDATED."""
from datetime import date

import pytest

from shared.utils.cheque_date import parse_cheque_date


@pytest.mark.parametrize("raw,expected", [
    ("09102026", date(2026, 10, 9)),          # printed 8-box DDMMYYYY, no separators
    ("09/10/2026", date(2026, 10, 9)),
    ("09-10-2026", date(2026, 10, 9)),
    ("09.10.2026", date(2026, 10, 9)),
    ("0 9 1 0 2 0 2 6", date(2026, 10, 9)),   # digits read box by box
    ("091026", date(2026, 10, 9)),            # DDMMYY
    ("09/10/26", date(2026, 10, 9)),
    ("2026-10-09", date(2026, 10, 9)),
    ("09-Oct-2026", date(2026, 10, 9)),
    ("  09102026  ", date(2026, 10, 9)),
])
def test_valid_formats(raw, expected):
    assert parse_cheque_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "DDMMYYYY", "DD/MM/YYYY", "32132026", "00102026",
                                 "9102026", "abcdefgh", "31022026"])
def test_unparseable_returns_none(raw):
    assert parse_cheque_date(raw) is None
