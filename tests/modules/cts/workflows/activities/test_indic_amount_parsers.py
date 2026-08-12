"""TDD — amount word parsers for all 8 non-Devanagari Indic scripts.

Each test uses the exact amount words from the 27-cheque digest specimens so
we verify against real-world cheque text, not invented strings.

Parser contract: returns float | None.
  None = undecidable (unknown token after noise filtering).
"""
import pytest
from modules.cts.workflows.activities.indic_amount_parsers import (
    parse_tamil_amount_words,
    parse_telugu_amount_words,
    parse_kannada_amount_words,
    parse_malayalam_amount_words,
    parse_gujarati_amount_words,
    parse_bengali_amount_words,
    parse_punjabi_amount_words,
    parse_odia_amount_words,
    parse_indic_amount_by_script,
)


# ─── TAMIL ────────────────────────────────────────────────────────────────────

class TestTamilParser:
    def test_1_lakh(self):
        assert parse_tamil_amount_words("ஒரு லட்சம் ரூபாய் மட்டும்") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_tamil_amount_words(
            "இருபது லட்சம் ஐம்பது ஆயிரம் ரூபாய் மட்டும்"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_tamil_amount_words(
            "ஐந்து லட்சம் எழுபத்தைந்து ஆயிரம் ரூபாய் மட்டும்"
        ) == 5_75_000.0

    def test_10_thousand(self):
        assert parse_tamil_amount_words("பத்து ஆயிரம் ரூபாய்") == 10_000.0

    def test_bare_lakh(self):
        assert parse_tamil_amount_words("லட்சம்") == 100_000.0

    def test_unknown_token_returns_none(self):
        assert parse_tamil_amount_words("xyz abc def") is None

    def test_empty_string_returns_none(self):
        assert parse_tamil_amount_words("") is None

    def test_noise_only_returns_none(self):
        assert parse_tamil_amount_words("ரூபாய் மட்டும்") is None


# ─── TELUGU ───────────────────────────────────────────────────────────────────

class TestTeluguParser:
    def test_1_lakh(self):
        assert parse_telugu_amount_words("ఒక లక్ష రూపాయలు మాత్రమే") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_telugu_amount_words(
            "ఇరవై లక్షలు యాభై వేలు రూపాయలు మాత్రమే"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand_additive(self):
        # "70 + 5 thousand" are separate additive tokens before the scale
        assert parse_telugu_amount_words(
            "ఐదు లక్షలు డెబ్బది అయిదు వేలు రూపాయలు మాత్రమే"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_telugu_amount_words("xyz abc") is None


# ─── KANNADA ──────────────────────────────────────────────────────────────────

class TestKannadaParser:
    def test_1_lakh(self):
        assert parse_kannada_amount_words("ಒಂದು ಲಕ್ಷ ರೂಪಾಯಿ ಮಾತ್ರ") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_kannada_amount_words(
            "ಇಪ್ಪತ್ತು ಲಕ್ಷ ಐವತ್ತು ಸಾವಿರ ರೂಪಾಯಿ ಮಾತ್ರ"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_kannada_amount_words(
            "ಐದು ಲಕ್ಷ ಎಪ್ಪತ್ತೈದು ಸಾವಿರ ರೂಪಾಯಿ ಮಾತ್ರ"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_kannada_amount_words("hello world") is None


# ─── MALAYALAM ────────────────────────────────────────────────────────────────

class TestMalayalamParser:
    def test_1_lakh(self):
        assert parse_malayalam_amount_words("ഒരു ലക്ഷം രൂപ മാത്രം") == 100_000.0

    def test_20_lakh_50_thousand_compound(self):
        # "അൻപതിനായിരം" = 50,000 as a compound direct value
        assert parse_malayalam_amount_words(
            "ഇരുപത് ലക്ഷം അൻപതിനായിരം രൂപ മാത്രം"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_malayalam_amount_words(
            "അഞ്ച് ലക്ഷം എഴുപത്തഞ്ച് ആയിരം രൂപ മാത്രം"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_malayalam_amount_words("nothing") is None


# ─── GUJARATI ─────────────────────────────────────────────────────────────────

class TestGujaratiParser:
    def test_1_lakh(self):
        assert parse_gujarati_amount_words("એક લાખ રૂપિયા માત્ર") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_gujarati_amount_words(
            "વીસ લાખ પચાસ હજાર રૂપિયા"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_gujarati_amount_words(
            "પાંચ લાખ પંચોતેર હજાર રૂપિયા"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_gujarati_amount_words("unknown") is None


# ─── BENGALI ──────────────────────────────────────────────────────────────────

class TestBengaliParser:
    def test_1_lakh(self):
        assert parse_bengali_amount_words("এক লক্ষ টাকা মাত্র") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_bengali_amount_words(
            "বিশ লক্ষ পঞ্চাশ হাজার টাকা মাত্র"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_bengali_amount_words(
            "পাঁচ লক্ষ পঁচাত্তর হাজার টাকা মাত্র"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_bengali_amount_words("xyz") is None


# ─── PUNJABI (GURMUKHI) ───────────────────────────────────────────────────────

class TestPunjabiParser:
    def test_1_lakh(self):
        assert parse_punjabi_amount_words("ਇੱਕ ਲੱਖ ਰੁਪਏ ਕੇਵਲ") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_punjabi_amount_words(
            "ਵੀਹ ਲੱਖ ਪੰਜਾਹ ਹਜ਼ਾਰ ਰੁਪਏ ਕੇਵਲ"
        ) == 20_50_000.0

    def test_5_lakh_75_thousand(self):
        assert parse_punjabi_amount_words(
            "ਪੰਜ ਲੱਖ ਪੰਜਾਹਤਰ ਹਜ਼ਾਰ ਰੁਪਏ ਕੇਵਲ"
        ) == 5_75_000.0

    def test_unknown_token_returns_none(self):
        assert parse_punjabi_amount_words("abc") is None


# ─── ODIA ─────────────────────────────────────────────────────────────────────

class TestOdiaParser:
    def test_1_lakh(self):
        assert parse_odia_amount_words("ଏକ ଲକ୍ଷ ଟଙ୍କା ମାତ୍ର") == 100_000.0

    def test_20_lakh_50_thousand(self):
        assert parse_odia_amount_words(
            "ବିଶ ଲକ୍ଷ ପଚାଶ ହଜାର ଟଙ୍କା ମାତ୍ର"
        ) == 20_50_000.0

    def test_5_lakh(self):
        assert parse_odia_amount_words("ପାଞ୍ଚ ଲକ୍ଷ ଟଙ୍କା ମାତ୍ର") == 5_00_000.0

    def test_unknown_token_returns_none(self):
        assert parse_odia_amount_words("xyz") is None


# ─── DISPATCH BY SCRIPT ───────────────────────────────────────────────────────

class TestDispatch:
    def test_tamil_dispatch(self):
        assert parse_indic_amount_by_script(
            "ஒரு லட்சம் ரூபாய் மட்டும்", "tamil"
        ) == 100_000.0

    def test_telugu_dispatch(self):
        assert parse_indic_amount_by_script(
            "ఒక లక్ష రూపాయలు మాత్రమే", "telugu"
        ) == 100_000.0

    def test_kannada_dispatch(self):
        assert parse_indic_amount_by_script(
            "ಒಂದು ಲಕ್ಷ ರೂಪಾಯಿ ಮಾತ್ರ", "kannada"
        ) == 100_000.0

    def test_malayalam_dispatch(self):
        assert parse_indic_amount_by_script(
            "ഒരു ലക്ഷം രൂപ മാത്രം", "malayalam"
        ) == 100_000.0

    def test_gujarati_dispatch(self):
        assert parse_indic_amount_by_script(
            "એક લાખ રૂપિયા માત્ર", "gujarati"
        ) == 100_000.0

    def test_bengali_dispatch(self):
        assert parse_indic_amount_by_script(
            "এক লক্ষ টাকা মাত্র", "bengali"
        ) == 100_000.0

    def test_gurmukhi_dispatch(self):
        assert parse_indic_amount_by_script(
            "ਇੱਕ ਲੱਖ ਰੁਪਏ ਕੇਵਲ", "gurmukhi"
        ) == 100_000.0

    def test_odia_dispatch(self):
        assert parse_indic_amount_by_script(
            "ଏକ ଲକ୍ଷ ଟଙ୍କା ମାତ୍ର", "odia"
        ) == 100_000.0

    def test_devanagari_dispatches_to_none_from_this_module(self):
        # Devanagari is handled by amount_words_parser.py (Hindi/Marathi), not here
        result = parse_indic_amount_by_script("रुपये बीस लाख", "devanagari")
        assert result is None  # caller falls back to parse_hindi_amount_words

    def test_unknown_script_returns_none(self):
        assert parse_indic_amount_by_script("some text", "unknown_script") is None
