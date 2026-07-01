"""
Tests for modules/cts/workflows/activities/amount_words_parser.py

Indian number-words → float parser for cheque amount cross-check.
Used by ocr_extract() to compare amount_in_words vs amount_in_figures.

Scope: Indian currency denomination system (Lakh, Crore).
Handles:
  - "Fifty Thousand Only" → 50000
  - "Two Lakhs Fifty Thousand" → 250000
  - "Rupees Five Crores Twenty Lakhs" → 52000000
  - "One Hundred" → 100
  - Prefix/suffix noise: "Rupees", "Rs.", "Only", "/-"
  - Case-insensitive
  - Returns None on unparseable input (never raises)
"""
import pytest


class TestCoreNumbers:
    def test_one(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("One") == 1

    def test_nineteen(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Nineteen") == 19

    def test_twenty(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Twenty") == 20

    def test_ninety_nine(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Ninety Nine") == 99

    def test_hundred(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("One Hundred") == 100

    def test_five_hundred(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Five Hundred") == 500

    def test_nine_hundred_ninety_nine(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Nine Hundred Ninety Nine") == 999


class TestThousands:
    def test_one_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("One Thousand") == 1000

    def test_fifty_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Fifty Thousand") == 50000

    def test_fifty_thousand_five_hundred(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Fifty Thousand Five Hundred") == 50500

    def test_nine_hundred_ninety_nine_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Nine Hundred Ninety Nine Thousand") == 999000


class TestLakhs:
    def test_one_lakh(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("One Lakh") == 100000

    def test_two_lakhs(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Two Lakhs") == 200000

    def test_two_lakhs_fifty_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Two Lakhs Fifty Thousand") == 250000

    def test_five_lakhs(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Five Lakh") == 500000

    def test_ninety_nine_lakhs_ninety_nine_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Ninety Nine Lakh Ninety Nine Thousand") == 9999000


class TestCrores:
    def test_one_crore(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("One Crore") == 10000000

    def test_five_crores_twenty_lakhs(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Five Crores Twenty Lakhs") == 52000000

    def test_two_crores_fifty_lakhs_seventy_five_thousand(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Two Crores Fifty Lakhs Seventy Five Thousand") == 25075000


class TestNoiseCleaning:
    def test_strips_rupees_prefix(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Rupees Fifty Thousand Only") == 50000

    def test_strips_rs_prefix(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Rs. Fifty Thousand") == 50000

    def test_strips_only_suffix(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Fifty Thousand Only") == 50000

    def test_strips_slash_suffix(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("Fifty Thousand/-") == 50000

    def test_case_insensitive(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("FIFTY THOUSAND") == 50000
        assert parse_amount_words("fifty thousand") == 50000

    def test_extra_whitespace(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("  Fifty   Thousand  Only  ") == 50000


class TestUnparseableInput:
    def test_empty_string_returns_none(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words("") is None

    def test_none_input_returns_none(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        assert parse_amount_words(None) is None

    def test_garbage_returns_none(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        result = parse_amount_words("xyzzy blorp")
        assert result is None

    def test_never_raises(self):
        from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
        # Must not raise on any input
        for text in ["", None, "???", "Rupees Only", "/-"]:
            result = parse_amount_words(text)
            assert result is None or isinstance(result, (int, float))


class TestAmountCrossCheck:
    """Tests for the cross-check function used by ocr_extract."""

    def test_matching_amounts_no_mismatch(self):
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures="50000", words="Fifty Thousand Only") is True

    def test_mismatching_amounts_detected(self):
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures="50000", words="Sixty Thousand Only") is False

    def test_tolerance_one_rupee(self):
        """Rounding in OCR: ₹50000 vs words parsed as 49999 is within ₹1 tolerance."""
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures="50000", words="Forty Nine Thousand Nine Hundred Ninety Nine") is True

    def test_large_mismatch_detected(self):
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures="500000", words="Fifty Thousand Only") is False

    def test_unparseable_words_returns_none_not_false(self):
        """If words can't be parsed, we can't cross-check — return None (unknown), not False."""
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        result = amounts_match(figures="50000", words="illegible scrawl")
        assert result is None

    def test_none_figures_returns_none(self):
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures=None, words="Fifty Thousand") is None

    def test_none_words_returns_none(self):
        from modules.cts.workflows.activities.amount_words_parser import amounts_match
        assert amounts_match(figures="50000", words=None) is None
