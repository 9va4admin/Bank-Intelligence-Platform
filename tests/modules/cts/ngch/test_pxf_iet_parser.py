"""
Tests for PXF ItemExpiryTime parser (P0 — IET safety critical).

ItemExpiryTime format per CTS Spec Rev 3.0, §PXF:
  0000000DDMMYYYYHH24MISS  (21 characters)
  ├─ 0000000 : 7-zero CCH protocol marker
  ├─ DD      : day (01-31)
  ├─ MM      : month (01-12)
  ├─ YYYY    : 4-digit year
  ├─ HH24    : hour in 24h format (00-23)
  ├─ MI      : minutes (00-59)
  └─ SS      : seconds (00-59)

Timezone: IST (UTC+5:30) — convert to UTC before storing.

CRITICAL: The per-item deadline from CCH is authoritative. The config-service
`iet_minutes` is only a bank-wide default used when no PXF is present.
An IET breach rate of 0.000% depends on correct parsing of this field.

RED phase: run before implementing pxf_iet_parser.py — all must FAIL.
"""
import pytest
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


class TestItemExpiryTimeParse:
    """Core parsing tests for the 21-char ItemExpiryTime field."""

    def test_valid_input_returns_utc_datetime(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        result = parse_item_expiry_time("000000007062026150000")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_result_is_utc_timezone(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        result = parse_item_expiry_time("000000007062026150000")
        # UTC offset must be zero
        assert result.utcoffset() == timedelta(0)

    def test_07_june_2026_1500_ist_maps_to_0930_utc(self):
        """07 Jun 2026 15:00:00 IST = 09:30:00 UTC (IST = UTC+5:30)."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        result = parse_item_expiry_time("000000007062026150000")
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 7
        assert result.hour == 9
        assert result.minute == 30
        assert result.second == 0

    def test_midnight_ist_crosses_date_boundary_to_utc(self):
        """01 Jan 2026 00:00:00 IST = 31 Dec 2025 18:30:00 UTC."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        result = parse_item_expiry_time("000000001012026000000")
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 31
        assert result.hour == 18
        assert result.minute == 30
        assert result.second == 0

    def test_end_of_session_1600_ist_maps_correctly(self):
        """19 Jun 2026 16:00:00 IST = 10:30:00 UTC."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        result = parse_item_expiry_time("000000019062026160000")
        assert result.hour == 10
        assert result.minute == 30

    def test_nonzero_seconds_preserved(self):
        """Seconds field is extracted and preserved correctly."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time

        # 15 Mar 2026 12:45:30 IST = 07:15:30 UTC
        result = parse_item_expiry_time("000000015032026124530")
        assert result.hour == 7
        assert result.minute == 15
        assert result.second == 30


class TestItemExpiryTimeValidation:
    """Error-path validation for malformed ItemExpiryTime strings."""

    def test_empty_string_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        with pytest.raises(IETParseError):
            parse_item_expiry_time("")

    def test_too_short_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        with pytest.raises(IETParseError):
            parse_item_expiry_time("00000007062026150000")  # 20 chars

    def test_too_long_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        with pytest.raises(IETParseError):
            parse_item_expiry_time("0000000700620261500000")  # 22 chars

    def test_wrong_prefix_raises(self):
        """Prefix must be exactly 7 zero characters."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        # 8th char is '1' not '0'
        with pytest.raises(IETParseError):
            parse_item_expiry_time("000000107062026150000")

    def test_invalid_month_13_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        # DD=01, MM=13, YYYY=2026, HH=15, MI=00, SS=00 — month 13 invalid
        with pytest.raises(IETParseError):
            parse_item_expiry_time("000000001132026150000")

    def test_invalid_day_32_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        # DD=32 is invalid
        with pytest.raises(IETParseError):
            parse_item_expiry_time("000000032012026150000")

    def test_invalid_hour_25_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        # HH=25 is invalid
        with pytest.raises(IETParseError):
            parse_item_expiry_time("000000007062026250000")

    def test_non_numeric_raises(self):
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        with pytest.raises(IETParseError):
            parse_item_expiry_time("0000000XXXXXXXXXXX0000"[:21])

    def test_all_zeros_raises(self):
        """Day=00, Month=00, Year=0000 are all invalid dates."""
        from modules.cts.ngch.pxf_iet_parser import parse_item_expiry_time, IETParseError

        with pytest.raises(IETParseError):
            parse_item_expiry_time("000000000000000000000")


class TestIetToUnixTimestamp:
    """Tests for the convenience Unix-timestamp converter."""

    def test_returns_float(self):
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        ts = iet_to_unix_timestamp("000000019062026160000")
        assert isinstance(ts, float)

    def test_correct_utc_timestamp(self):
        """19 Jun 2026 10:30:00 UTC expected."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        expected = datetime(2026, 6, 19, 10, 30, 0, tzinfo=timezone.utc).timestamp()
        result = iet_to_unix_timestamp("000000019062026160000")
        assert abs(result - expected) < 1.0

    def test_later_iet_has_larger_timestamp(self):
        """Two instruments in same session: later deadline = larger Unix ts."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        ts_1600 = iet_to_unix_timestamp("000000019062026160000")  # 16:00 IST
        ts_1400 = iet_to_unix_timestamp("000000019062026140000")  # 14:00 IST
        assert ts_1600 > ts_1400

    def test_two_instruments_distinct_deadlines(self):
        """Different ItemExpiryTime values must produce distinct timestamps."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        ts_a = iet_to_unix_timestamp("000000007062026150000")
        ts_b = iet_to_unix_timestamp("000000007062026160000")
        assert ts_a != ts_b

    def test_propagates_parse_error(self):
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp, IETParseError

        with pytest.raises(IETParseError):
            iet_to_unix_timestamp("BAD_INPUT_123456789012")


class TestIETWatchdogInputCompatibility:
    """Confirm parsed timestamp slots directly into IETWatchdogInput.iet_deadline."""

    def test_iet_deadline_field_accepts_float(self):
        """IETWatchdogInput.iet_deadline: float — no type coercion needed."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogInput

        ts = iet_to_unix_timestamp("000000007062026150000")
        inp = IETWatchdogInput(
            instrument_id="INS001",
            bank_id="saraswat-coop",
            iet_deadline=ts,
            workflow_id="cts-saraswat-coop-INS001",
        )
        assert inp.iet_deadline == ts

    def test_cheque_workflow_input_accepts_per_item_deadline(self):
        """ChequeWorkflowInput.iet_deadline: float — confirm no schema mismatch."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput

        ts = iet_to_unix_timestamp("000000007062026150000")
        inp = ChequeWorkflowInput(
            instrument_id="INS002",
            bank_id="saraswat-coop",
            image_url="minio://cts/front/INS002.tiff",
            account_number="SB12345678",
            cheque_number="000123",
            presented_amount=50000.0,
            presented_payee="Test Payee",
            iet_deadline=ts,
            cts_config={},
        )
        assert inp.iet_deadline == ts
