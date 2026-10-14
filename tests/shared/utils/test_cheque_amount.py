"""Shared cheque amount parser. Found by the real outward run: '10,00,000/-' and '2309700/-'
crashed the outward workflow task with float() ValueError (Temporal then retried that
task forever), and the inward parser silently treated '/-' amounts as unreadable."""
from decimal import Decimal

import pytest

from shared.utils.cheque_amount import parse_amount_figures


@pytest.mark.parametrize("raw,expected", [
    ("45000", Decimal("45000")),
    ("45,000.00", Decimal("45000.00")),
    ("10,00,000/-", Decimal("1000000")),       # lakh-style commas + trailing /-
    ("2309700/-", Decimal("2309700")),
    ("19,00,000/-", Decimal("1900000")),
    ("₹ 12,202.00", Decimal("12202.00")),
    ("Rs. 5,800/-", Decimal("5800")),
    ("Rs.15000=", Decimal("15000")),
    ("8760/-", Decimal("8760")),
    ("  30000  ", Decimal("30000")),
    ("15000-", Decimal("15000")),
])
def test_valid(raw, expected):
    assert parse_amount_figures(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "Rupees Ten Only", "12.34.56", "-", "/-"])
def test_unparseable_returns_none(raw):
    assert parse_amount_figures(raw) is None
