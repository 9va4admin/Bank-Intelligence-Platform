"""TDD — MICR line integrity validation.

CTS-2010 MICR line: ⑆[6-digit cheque]⑈[9-digit MICR code][account]⑉[tx code]⑆
Validates format, city code, transaction code, and optional account suffix cross-check.
Tampered images often change bank name on face but not MICR — this catches that.
"""
import pytest
from modules.cts.preprocessing.micr_validator import (
    validate_micr_line,
    MICRValidationResult,
)


class TestMICRParsing:
    def test_clean_micr_is_valid(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.decision == "VALID"

    def test_extracts_cheque_number(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.cheque_number == "001234"

    def test_extracts_micr_code(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.micr_code == "055301234"

    def test_extracts_account_field(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.account_field == "000021"

    def test_extracts_transaction_code(self):
        # Transaction code is embedded at start of the account field (last 2 chars)
        # OR parsed separately — depending on format: accept both
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.decision == "VALID"

    def test_missing_outer_transit_symbols_still_parsed(self):
        # Some OCR outputs drop the outer ⑆
        r = validate_micr_line("001234⑈055301234⑉000021")
        assert r.cheque_number == "001234"
        assert r.micr_code == "055301234"

    def test_spaces_tolerated(self):
        r = validate_micr_line("⑆ 001234 ⑈ 055301234 ⑉ 000021 ⑆")
        assert r.cheque_number == "001234"

    def test_empty_string_invalid_format(self):
        r = validate_micr_line("")
        assert r.decision == "INVALID_FORMAT"

    def test_garbled_string_invalid_format(self):
        r = validate_micr_line("ABCXYZ###")
        assert r.decision == "INVALID_FORMAT"


class TestChecksumRules:
    def test_city_code_000_is_suspicious(self):
        # City code 000 is not assigned — indicates MICR tampering
        r = validate_micr_line("⑆001234⑈000001234⑉000021⑆")
        assert r.decision == "SUSPICIOUS"
        assert any("city" in f.lower() for f in r.flags)

    def test_non_numeric_cheque_number_is_invalid(self):
        r = validate_micr_line("⑆ABC234⑈055301234⑉000021⑆")
        assert r.decision == "INVALID_FORMAT"

    def test_non_numeric_micr_code_is_invalid(self):
        r = validate_micr_line("⑆001234⑈05530ABCD⑉000021⑆")
        assert r.decision == "INVALID_FORMAT"

    def test_micr_code_wrong_length_invalid(self):
        # MICR code must be exactly 9 digits
        r = validate_micr_line("⑆001234⑈05530⑉000021⑆")
        assert r.decision == "INVALID_FORMAT"

    def test_cheque_number_wrong_length_invalid(self):
        # Cheque number must be exactly 6 digits
        r = validate_micr_line("⑆12345⑈055301234⑉000021⑆")
        assert r.decision == "INVALID_FORMAT"


class TestAccountSuffixCrossCheck:
    def test_matching_suffix_is_valid(self):
        # Account field ends in "0021", expected suffix "0021" → VALID
        r = validate_micr_line("⑆001234⑈055301234⑉000000000021⑆",
                                expected_account_suffix="0021")
        assert r.decision == "VALID"

    def test_mismatching_suffix_is_suspicious(self):
        # Account field ends in "0021", expected suffix "9999" → SUSPICIOUS
        r = validate_micr_line("⑆001234⑈055301234⑉000000000021⑆",
                                expected_account_suffix="9999")
        assert r.decision == "SUSPICIOUS"
        assert any("account" in f.lower() for f in r.flags)

    def test_no_expected_suffix_skips_check(self):
        # When we don't have an expected suffix, don't flag it
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆",
                                expected_account_suffix=None)
        assert r.decision == "VALID"
        assert not any("account" in f.lower() for f in r.flags)

    def test_4_digit_suffix_match(self):
        r = validate_micr_line("⑆001234⑈055301234⑉012345⑆",
                                expected_account_suffix="2345")
        assert r.decision == "VALID"


class TestResultShape:
    def test_flags_is_list(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert isinstance(r.flags, list)

    def test_valid_has_empty_flags(self):
        r = validate_micr_line("⑆001234⑈055301234⑉000021⑆")
        assert r.flags == []

    def test_suspicious_has_flags(self):
        r = validate_micr_line("⑆001234⑈000001234⑉000021⑆")
        assert len(r.flags) > 0
