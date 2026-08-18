"""TDD — cheque date validation (stale / post-dated / format).

RBI CTS rule: cheque > 90 days old = stale → return reason 38.
Post-dated cheque → hold queue, not return.
"""
import pytest
from datetime import date, timedelta
from modules.cts.preprocessing.cheque_date_validator import (
    validate_cheque_date,
    DateValidationResult,
    DateDecision,
)

TODAY = date(2026, 8, 12)


class TestDateParsing:
    def test_dd_mm_yyyy(self):
        r = validate_cheque_date("07/08/2026", reference_date=TODAY)
        assert r.cheque_date == date(2026, 8, 7)

    def test_dd_mm_yy(self):
        r = validate_cheque_date("07/08/26", reference_date=TODAY)
        assert r.cheque_date == date(2026, 8, 7)

    def test_dd_dash_mm_dash_yyyy(self):
        r = validate_cheque_date("07-08-2026", reference_date=TODAY)
        assert r.cheque_date == date(2026, 8, 7)

    def test_dd_dot_mm_dot_yyyy(self):
        r = validate_cheque_date("07.08.2026", reference_date=TODAY)
        assert r.cheque_date == date(2026, 8, 7)

    def test_spaces_in_date(self):
        # OCR artifact: "07 / 08 / 2026"
        r = validate_cheque_date("07 / 08 / 2026", reference_date=TODAY)
        assert r.cheque_date == date(2026, 8, 7)

    def test_invalid_format_returns_invalid(self):
        r = validate_cheque_date("abc/def/ghij", reference_date=TODAY)
        assert r.decision == "INVALID_FORMAT"
        assert r.cheque_date is None

    def test_impossible_date_returns_invalid(self):
        # day 32 doesn't exist
        r = validate_cheque_date("32/08/2026", reference_date=TODAY)
        assert r.decision == "INVALID_FORMAT"

    def test_completely_garbled(self):
        r = validate_cheque_date("", reference_date=TODAY)
        assert r.decision == "INVALID_FORMAT"


class TestStaleCheques:
    def test_exactly_90_days_old_is_valid(self):
        d = TODAY - timedelta(days=90)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.decision == "VALID"
        assert r.days_old == 90

    def test_91_days_old_is_stale(self):
        d = TODAY - timedelta(days=91)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.decision == "STALE"
        assert r.days_old == 91

    def test_stale_has_return_reason_38(self):
        d = TODAY - timedelta(days=120)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.return_reason_code == "38"

    def test_60_days_old_is_valid(self):
        d = TODAY - timedelta(days=60)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.decision == "VALID"
        assert r.return_reason_code is None

    def test_today_is_valid(self):
        r = validate_cheque_date(TODAY.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.decision == "VALID"
        assert r.days_old == 0

    def test_stale_threshold_configurable(self):
        # Bank configured 60-day stale window (stricter than default)
        d = TODAY - timedelta(days=65)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=60,
                                 reference_date=TODAY)
        assert r.decision == "STALE"

    def test_six_month_old_cheque_is_stale(self):
        d = TODAY - timedelta(days=180)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), stale_days=90,
                                 reference_date=TODAY)
        assert r.decision == "STALE"


class TestPostDatedCheques:
    def test_tomorrow_is_post_dated(self):
        d = TODAY + timedelta(days=1)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), reference_date=TODAY)
        assert r.decision == "POST_DATED"
        assert r.days_old < 0

    def test_30_days_future_is_post_dated(self):
        d = TODAY + timedelta(days=30)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), reference_date=TODAY)
        assert r.decision == "POST_DATED"

    def test_post_dated_has_no_return_reason(self):
        # Post-dated goes to hold queue, not returned
        d = TODAY + timedelta(days=7)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), reference_date=TODAY)
        assert r.return_reason_code is None

    def test_post_dated_days_old_is_negative(self):
        d = TODAY + timedelta(days=14)
        r = validate_cheque_date(d.strftime("%d/%m/%Y"), reference_date=TODAY)
        assert r.days_old == -14


class TestResultShape:
    def test_result_is_frozen_dataclass(self):
        r = validate_cheque_date(TODAY.strftime("%d/%m/%Y"), reference_date=TODAY)
        with pytest.raises((AttributeError, TypeError)):
            r.decision = "STALE"  # type: ignore

    def test_valid_result_shape(self):
        r = validate_cheque_date("01/08/2026", reference_date=TODAY)
        assert r.decision in {"VALID", "STALE", "POST_DATED", "INVALID_FORMAT"}
        assert isinstance(r.days_old, int) or r.days_old is None
