"""Tests for shared/utils/masking.py — PII masking utilities."""
import pytest

from shared.utils.masking import (
    mask_account_number,
    mask_amount,
    mask_customer_name,
    mask_phone,
)


class TestMaskAccountNumber:
    def test_last4_digits_shown(self):
        assert mask_account_number("12345678901234") == "****1234"

    def test_short_account_shows_what_it_can(self):
        assert mask_account_number("1234") == "****1234"

    def test_empty_string_returns_stars(self):
        assert mask_account_number("") == "****"

    def test_suffix_always_4_chars(self):
        result = mask_account_number("9876543210")
        assert result.startswith("****")
        assert len(result) == 8  # **** + last 4


class TestMaskCustomerName:
    def test_first_initial_only(self):
        assert mask_customer_name("Nilesh Shah") == "N***"

    def test_single_char_name(self):
        assert mask_customer_name("A") == "A***"

    def test_empty_returns_stars(self):
        assert mask_customer_name("") == "***"

    def test_whitespace_only_returns_stars(self):
        assert mask_customer_name("   ") == "***"

    def test_strips_leading_space(self):
        assert mask_customer_name("  Priya") == "P***"


class TestMaskAmount:
    def test_below_1_lakh(self):
        assert mask_amount(50_000) == "₹[<1L]"

    def test_exactly_1_lakh(self):
        assert mask_amount(100_000) == "₹[1L-5L]"

    def test_1L_to_5L_range(self):
        assert mask_amount(250_000) == "₹[1L-5L]"

    def test_5L_to_10L_range(self):
        assert mask_amount(750_000) == "₹[5L-10L]"

    def test_10L_to_1Cr_range(self):
        assert mask_amount(5_000_000) == "₹[10L-1Cr]"

    def test_above_1Cr(self):
        assert mask_amount(15_000_000) == "₹[>1Cr]"

    def test_zero(self):
        assert mask_amount(0) == "₹[<1L]"

    def test_high_value_cheque(self):
        assert mask_amount(50_00_000) == "₹[10L-1Cr]"  # 50,00,000 = 50 lakh


class TestMaskPhone:
    def test_last4_digits_shown(self):
        assert mask_phone("9876543210") == "******3210"

    def test_empty_returns_stars(self):
        assert mask_phone("") == "******"

    def test_short_phone(self):
        assert mask_phone("1234") == "******1234"
