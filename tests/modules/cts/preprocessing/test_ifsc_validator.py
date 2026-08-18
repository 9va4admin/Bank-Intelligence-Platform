"""TDD — IFSC code validator for CTS cheque cross-check."""
import pytest
from modules.cts.preprocessing.ifsc_validator import validate_ifsc, parse_ifsc, IFSCInfo


class TestValidateIfsc:
    def test_valid_sbi(self):
        assert validate_ifsc("SBIN0001234") is True

    def test_valid_hdfc(self):
        assert validate_ifsc("HDFC0001234") is True

    def test_valid_saraswat(self):
        assert validate_ifsc("SRCB0000001") is True

    def test_valid_uppercase_input(self):
        assert validate_ifsc("ICIC0002345") is True

    def test_lowercase_input_normalised(self):
        assert validate_ifsc("sbin0001234") is True

    def test_mixed_case_normalised(self):
        assert validate_ifsc("Hdfc0001234") is True

    def test_fifth_char_must_be_zero(self):
        assert validate_ifsc("SBIN1001234") is False

    def test_first_4_must_be_alpha(self):
        assert validate_ifsc("1234001234") is False
        assert validate_ifsc("SBI10001234") is False

    def test_total_length_must_be_11(self):
        assert validate_ifsc("SBIN000123") is False   # 10 chars
        assert validate_ifsc("SBIN00012345") is False  # 12 chars

    def test_empty_string(self):
        assert validate_ifsc("") is False

    def test_branch_code_alphanumeric(self):
        assert validate_ifsc("SBIN0ABC123") is True

    def test_branch_code_all_digits(self):
        assert validate_ifsc("SBIN0123456") is True

    def test_special_chars_invalid(self):
        assert validate_ifsc("SBIN0-01234") is False

    def test_whitespace_stripped(self):
        assert validate_ifsc("  SBIN0001234  ") is True


class TestParseIfsc:
    def test_parse_valid(self):
        info = parse_ifsc("SBIN0001234")
        assert info.valid is True
        assert info.bank_code == "SBIN"
        assert info.branch_code == "001234"
        assert info.error is None

    def test_parse_invalid_returns_error(self):
        info = parse_ifsc("BADIFSC")
        assert info.valid is False
        assert info.bank_code is None
        assert info.error is not None

    def test_parse_extracts_branch_exactly_6_chars(self):
        info = parse_ifsc("HDFC0ABCDEF")
        assert info.branch_code == "ABCDEF"

    def test_parse_returns_ifsc_info_type(self):
        info = parse_ifsc("SRCB0000001")
        assert isinstance(info, IFSCInfo)
