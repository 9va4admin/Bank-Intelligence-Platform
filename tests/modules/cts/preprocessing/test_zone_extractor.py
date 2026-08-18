"""
TDD — zone_extractor.py (RED first)

Tests for CTS-2010 field zone extraction, data-URI encoding, and
per-field script detection (Indic vs Latin).
"""
import base64
import pytest
from PIL import Image


# ── helpers ────────────────────────────────────────────────────────────────────

def _cheque(w: int = 1400, h: int = 600) -> Image.Image:
    """Synthetic cheque image (solid grey — content irrelevant for geometry tests)."""
    return Image.new("RGB", (w, h), color=(200, 220, 200))


# ── extract_zone ──────────────────────────────────────────────────────────────

class TestExtractZone:
    def test_date_zone_is_top_right(self):
        from modules.cts.preprocessing.zone_extractor import extract_zone, CTS_ZONES
        img = _cheque()
        zone = extract_zone(img, "date")
        x1f, y1f, x2f, y2f = CTS_ZONES["date"]
        assert zone.size == (int(x2f * 1400) - int(x1f * 1400),
                             int(y2f * 600)  - int(y1f * 600))

    def test_payee_zone_dimensions(self):
        from modules.cts.preprocessing.zone_extractor import extract_zone, CTS_ZONES
        img = _cheque()
        zone = extract_zone(img, "payee_name")
        x1f, y1f, x2f, y2f = CTS_ZONES["payee_name"]
        assert zone.size == (int(x2f * 1400) - int(x1f * 1400),
                             int(y2f * 600)  - int(y1f * 600))

    def test_all_zones_produce_non_empty_crops(self):
        from modules.cts.preprocessing.zone_extractor import extract_zone, CTS_ZONES
        img = _cheque()
        for field in CTS_ZONES:
            z = extract_zone(img, field)
            assert z.width > 0 and z.height > 0

    def test_unknown_field_raises_value_error(self):
        from modules.cts.preprocessing.zone_extractor import extract_zone
        with pytest.raises(ValueError, match="Unknown CTS field"):
            extract_zone(_cheque(), "nonexistent")

    def test_small_image_clamps_to_bounds(self):
        """Zone coordinates must not exceed image dimensions on tiny images."""
        from modules.cts.preprocessing.zone_extractor import extract_zone
        img = _cheque(w=100, h=50)
        z = extract_zone(img, "micr_band")
        assert z.width <= 100 and z.height <= 50


# ── zone_to_data_uri ──────────────────────────────────────────────────────────

class TestZoneToDataUri:
    def test_returns_jpeg_data_uri(self):
        from modules.cts.preprocessing.zone_extractor import zone_to_data_uri
        uri = zone_to_data_uri(_cheque(200, 50))
        assert uri.startswith("data:image/jpeg;base64,")

    def test_png_format_returns_png_mime(self):
        from modules.cts.preprocessing.zone_extractor import zone_to_data_uri
        uri = zone_to_data_uri(_cheque(200, 50), fmt="PNG")
        assert uri.startswith("data:image/png;base64,")

    def test_base64_payload_is_valid(self):
        from modules.cts.preprocessing.zone_extractor import zone_to_data_uri
        uri = zone_to_data_uri(_cheque(200, 50))
        b64 = uri.split(",", 1)[1]
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0

    def test_extract_then_encode_roundtrip(self):
        from modules.cts.preprocessing.zone_extractor import extract_zone, zone_to_data_uri
        zone = extract_zone(_cheque(), "amount_figures")
        uri = zone_to_data_uri(zone)
        assert uri.startswith("data:image/jpeg;base64,")


# ── has_devanagari / has_indic_script ─────────────────────────────────────────

class TestHasDevanagari:
    def test_true_for_hindi_text(self):
        from modules.cts.preprocessing.zone_extractor import has_devanagari
        assert has_devanagari("अभिलाष रेड्डी") is True

    def test_true_for_marathi_text(self):
        from modules.cts.preprocessing.zone_extractor import has_devanagari
        assert has_devanagari("बीस लाख पचास हजार") is True

    def test_false_for_english(self):
        from modules.cts.preprocessing.zone_extractor import has_devanagari
        assert has_devanagari("Abhilash Reddy") is False

    def test_false_for_numerics(self):
        from modules.cts.preprocessing.zone_extractor import has_devanagari
        assert has_devanagari("2255000") is False

    def test_false_for_empty_string(self):
        from modules.cts.preprocessing.zone_extractor import has_devanagari
        assert has_devanagari("") is False


class TestHasIndicScript:
    def test_detects_devanagari(self):
        from modules.cts.preprocessing.zone_extractor import has_indic_script
        assert has_indic_script("अभिलाष") is True

    def test_detects_gujarati(self):
        from modules.cts.preprocessing.zone_extractor import has_indic_script
        assert has_indic_script("ગુજરાત") is True       # U+0A97 etc.

    def test_detects_tamil(self):
        from modules.cts.preprocessing.zone_extractor import has_indic_script
        assert has_indic_script("தமிழ்") is True

    def test_detects_telugu(self):
        from modules.cts.preprocessing.zone_extractor import has_indic_script
        assert has_indic_script("తెలుగు") is True

    def test_false_for_latin(self):
        from modules.cts.preprocessing.zone_extractor import has_indic_script
        assert has_indic_script("Twenty Two Lakhs") is False


# ── detect_script ─────────────────────────────────────────────────────────────

class TestDetectScript:
    def test_indic_for_devanagari(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("बीस लाख") == "indic"

    def test_indic_for_gujarati(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("ગુજરાત") == "indic"

    def test_latin_for_english_amount(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("Twenty Two Lakhs Fifty Five Thousand") == "latin"

    def test_latin_for_date(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("08/01/2013") == "latin"

    def test_unknown_for_empty_string(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("") == "unknown"

    def test_unknown_for_whitespace_only(self):
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("   \t\n") == "unknown"

    def test_indic_wins_in_mixed_text(self):
        # Even a single Devanagari char in otherwise-Latin text → indic
        from modules.cts.preprocessing.zone_extractor import detect_script
        assert detect_script("Pay रुपये 100") == "indic"


# ── field classification constants ────────────────────────────────────────────

class TestFieldClassification:
    def test_always_latin_includes_date(self):
        from modules.cts.preprocessing.zone_extractor import ALWAYS_LATIN
        assert "date" in ALWAYS_LATIN

    def test_always_latin_includes_amount_figures(self):
        from modules.cts.preprocessing.zone_extractor import ALWAYS_LATIN
        assert "amount_figures" in ALWAYS_LATIN

    def test_always_latin_includes_micr_band(self):
        from modules.cts.preprocessing.zone_extractor import ALWAYS_LATIN
        assert "micr_band" in ALWAYS_LATIN

    def test_script_adaptive_includes_payee(self):
        from modules.cts.preprocessing.zone_extractor import SCRIPT_ADAPTIVE
        assert "payee_name" in SCRIPT_ADAPTIVE

    def test_script_adaptive_includes_amount_words(self):
        from modules.cts.preprocessing.zone_extractor import SCRIPT_ADAPTIVE
        assert "amount_words" in SCRIPT_ADAPTIVE

    def test_script_adaptive_includes_bank_name(self):
        from modules.cts.preprocessing.zone_extractor import SCRIPT_ADAPTIVE
        assert "bank_name" in SCRIPT_ADAPTIVE

    def test_always_latin_and_script_adaptive_disjoint(self):
        from modules.cts.preprocessing.zone_extractor import ALWAYS_LATIN, SCRIPT_ADAPTIVE
        assert ALWAYS_LATIN.isdisjoint(SCRIPT_ADAPTIVE)

    def test_all_zone_fields_classified(self):
        """Every field in CTS_ZONES must be in exactly one of the two sets."""
        from modules.cts.preprocessing.zone_extractor import CTS_ZONES, ALWAYS_LATIN, SCRIPT_ADAPTIVE
        for field in CTS_ZONES:
            assert (field in ALWAYS_LATIN) != (field in SCRIPT_ADAPTIVE), (
                f"Field '{field}' must be in exactly one of ALWAYS_LATIN or SCRIPT_ADAPTIVE"
            )


# ── identify_indic_script ──────────────────────────────────────────────────────

class TestIdentifyIndicScript:
    def test_devanagari_text_returns_devanagari(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("अभिलाष रेड्डी") == "devanagari"

    def test_tamil_text_returns_tamil(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("தமிழ்") == "tamil"

    def test_telugu_text_returns_telugu(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("తెలుగు") == "telugu"

    def test_kannada_text_returns_kannada(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("ಕನ್ನಡ") == "kannada"

    def test_malayalam_text_returns_malayalam(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("മലയാളം") == "malayalam"

    def test_gujarati_text_returns_gujarati(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("ગુજરાત") == "gujarati"

    def test_bengali_text_returns_bengali(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("বাংলা") == "bengali"

    def test_latin_returns_none(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("ACME Corp") is None

    def test_empty_returns_none(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("") is None

    def test_dominant_script_wins_on_mixed_text(self):
        # Devanagari codepoints outnumber Tamil in this string
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("अभिलाष தமிழ்") == "devanagari"

    def test_marathi_amount_words_devanagari(self):
        from modules.cts.preprocessing.zone_extractor import identify_indic_script
        assert identify_indic_script("बीस लाख पचास हजार") == "devanagari"
