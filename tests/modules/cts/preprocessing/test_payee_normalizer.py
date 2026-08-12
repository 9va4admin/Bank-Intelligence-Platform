"""TDD — tests for payee name normalizer.
Run BEFORE writing implementation to confirm RED state.
"""
import pytest
from modules.cts.preprocessing.payee_normalizer import (
    strip_salutation,
    transliterate_devanagari,
    payee_names_match,
    PayeeMatchResult,
)


# ─────────────────────────────────────────────────────────────
#  strip_salutation
# ─────────────────────────────────────────────────────────────

class TestStripSalutation:
    def test_hindi_shreemati(self):
        assert strip_salutation("श्रीमती लता देशपांडे") == "लता देशपांडे"

    def test_hindi_shri(self):
        assert strip_salutation("श्री राजेश कुमार वर्मा") == "राजेश कुमार वर्मा"

    def test_hindi_doctor_abbrev(self):
        assert strip_salutation("डॉ. सुभाष महापात्र") == "सुभाष महापात्र"

    def test_hindi_kumari(self):
        assert strip_salutation("कु. प्रीति शर्मा") == "प्रीति शर्मा"

    def test_marathi_sau(self):
        # Marathi सौ. = Smt
        assert strip_salutation("सौ. लता देशपांडे") == "लता देशपांडे"

    def test_english_smt(self):
        assert strip_salutation("Smt. Lata Deshpande") == "Lata Deshpande"

    def test_english_mr(self):
        assert strip_salutation("Mr. Rajesh Kumar Varma") == "Rajesh Kumar Varma"

    def test_english_mrs(self):
        assert strip_salutation("Mrs. Sunita Mishra") == "Sunita Mishra"

    def test_english_ms(self):
        assert strip_salutation("Ms. Ananya Singh") == "Ananya Singh"

    def test_english_dr(self):
        assert strip_salutation("Dr. Subhash Chandra Mahapatra") == "Subhash Chandra Mahapatra"

    def test_tamil_thirumathi(self):
        assert strip_salutation("திருமதி மீனாக்ஷி சுந்தரம்") == "மீனாக்ஷி சுந்தரம்"

    def test_tamil_thiru(self):
        assert strip_salutation("திரு ரமேஷ் குமார்") == "ரமேஷ் குமார்"

    def test_telugu_sreemathi(self):
        assert strip_salutation("శ్రీమతి సుభాషిణి రెడ్డి") == "సుభాషిణి రెడ్డి"

    def test_no_salutation_unchanged(self):
        assert strip_salutation("Abhilash Kumar Sharma") == "Abhilash Kumar Sharma"

    def test_no_salutation_unchanged_devanagari(self):
        assert strip_salutation("लता देशपांडे") == "लता देशपांडे"

    def test_strips_only_leading_salutation(self):
        # "Shri" appearing in the middle of a name must NOT be stripped
        result = strip_salutation("Lata Shridhar Deshpande")
        assert "Shridhar" in result

    def test_empty_string(self):
        assert strip_salutation("") == ""

    def test_salutation_only(self):
        # Edge: just a salutation with nothing after
        assert strip_salutation("श्री") == ""


# ─────────────────────────────────────────────────────────────
#  transliterate_devanagari
# ─────────────────────────────────────────────────────────────

class TestTransliterateDevanagari:
    def test_lata(self):
        assert transliterate_devanagari("लता") == "lata"

    def test_rajesh(self):
        # राजेश — word-final consonant inherent-a expected
        result = transliterate_devanagari("राजेश")
        assert result.startswith("rajesh")  # trailing 'a' acceptable

    def test_kumar(self):
        result = transliterate_devanagari("कुमार")
        assert result.startswith("kumar")

    def test_varma(self):
        assert transliterate_devanagari("वर्मा") == "varma"

    def test_deshpande(self):
        # देशपांडे — anusvara should give 'n'
        result = transliterate_devanagari("देशपांडे")
        assert "desh" in result
        assert "pand" in result

    def test_sunita(self):
        result = transliterate_devanagari("सुनीता")
        assert result.startswith("sunita") or result.startswith("sunita")

    def test_abhilash(self):
        result = transliterate_devanagari("अभिलाष")
        assert "abhilash" in result or result.startswith("abhilash")

    def test_mishra(self):
        result = transliterate_devanagari("मिश्रा")
        assert "mishr" in result

    def test_sharma(self):
        result = transliterate_devanagari("शर्मा")
        assert result.startswith("sharma") or "sharma" in result

    def test_devanagari_numerals_pass_through(self):
        result = transliterate_devanagari("१२३")
        assert result == "123"

    def test_non_devanagari_chars_stripped(self):
        # Period/space should survive normalization
        result = transliterate_devanagari("राजेश वर्मा")
        assert " " in result


# ─────────────────────────────────────────────────────────────
#  payee_names_match
# ─────────────────────────────────────────────────────────────

class TestPayeeNamesMatch:
    """
    payee_names_match(ocr_name, cbs_name, threshold, script=None)
    Returns PayeeMatchResult with .decision in {"MATCH", "FUZZY", "MISMATCH", "UNDECIDABLE"}
    """

    # ── Devanagari cheque vs English CBS (main use case) ──

    def test_shreemati_lata_vs_english(self):
        r = payee_names_match("श्रीमती लता देशपांडे", "Lata Deshpande",
                              threshold=0.82, script="devanagari")
        assert r.decision in {"MATCH", "FUZZY"}
        assert r.score >= 0.80

    def test_shri_rajesh_vs_english(self):
        r = payee_names_match("श्री राजेश कुमार वर्मा", "Rajesh Kumar Varma",
                              threshold=0.82, script="devanagari")
        assert r.decision in {"MATCH", "FUZZY"}
        assert r.score >= 0.80

    def test_devanagari_exact_name_vs_english(self):
        r = payee_names_match("अभिलाष कुमार शर्मा", "Abhilash Kumar Sharma",
                              threshold=0.82, script="devanagari")
        assert r.decision in {"MATCH", "FUZZY"}

    # ── English cheque vs English CBS ──

    def test_english_vs_english_exact(self):
        r = payee_names_match("Lata Deshpande", "Lata Deshpande",
                              threshold=0.82, script=None)
        assert r.decision == "MATCH"
        assert r.score == 1.0

    def test_english_case_insensitive(self):
        r = payee_names_match("LATA DESHPANDE", "Lata Deshpande",
                              threshold=0.82, script=None)
        assert r.decision == "MATCH"

    def test_english_smt_prefix_vs_no_prefix(self):
        r = payee_names_match("Smt. Lata Deshpande", "Lata Deshpande",
                              threshold=0.82, script=None)
        assert r.decision in {"MATCH", "FUZZY"}

    def test_english_dr_prefix(self):
        r = payee_names_match("Dr. Subhash Mahapatra", "Subhash Mahapatra",
                              threshold=0.82, script=None)
        assert r.decision in {"MATCH", "FUZZY"}

    # ── Clear mismatches ──

    def test_completely_different_names(self):
        r = payee_names_match("Lata Deshpande", "Rajesh Sharma",
                              threshold=0.82, script=None)
        assert r.decision == "MISMATCH"
        assert r.score < 0.82

    def test_devanagari_wrong_person(self):
        r = payee_names_match("श्री राजेश कुमार वर्मा", "Sunita Mishra",
                              threshold=0.82, script="devanagari")
        assert r.decision == "MISMATCH"

    # ── Non-Devanagari scripts → UNDECIDABLE (no transliterator) ──

    def test_tamil_script_undecidable(self):
        r = payee_names_match("மீனாக்ஷி சுந்தரம்", "Meenakshi Sundaram",
                              threshold=0.82, script="tamil")
        assert r.decision == "UNDECIDABLE"

    def test_telugu_script_undecidable(self):
        r = payee_names_match("సుభాషిణి రెడ్డి", "Subhashini Reddy",
                              threshold=0.82, script="telugu")
        assert r.decision == "UNDECIDABLE"

    def test_kannada_script_undecidable(self):
        r = payee_names_match("ಶಾಂತಾ ಲಕ್ಷ್ಮೀ", "Shantha Lakshmi",
                              threshold=0.82, script="kannada")
        assert r.decision == "UNDECIDABLE"

    def test_malayalam_script_undecidable(self):
        r = payee_names_match("ലക്ഷ്മി നായർ", "Laxmi Nair",
                              threshold=0.82, script="malayalam")
        assert r.decision == "UNDECIDABLE"

    def test_gujarati_script_undecidable(self):
        r = payee_names_match("ભૂપેન્દ્ર ભાઈ શાહ", "Bhupendra Bhai Shah",
                              threshold=0.82, script="gujarati")
        assert r.decision == "UNDECIDABLE"

    def test_bengali_script_undecidable(self):
        r = payee_names_match("রজত কুমার ব্যানার্জি", "Rajat Kumar Banerjee",
                              threshold=0.82, script="bengali")
        assert r.decision == "UNDECIDABLE"

    def test_gurmukhi_script_undecidable(self):
        r = payee_names_match("ਗੁਰਪ੍ਰੀਤ ਸਿੰਘ", "Gurpreet Singh",
                              threshold=0.82, script="gurmukhi")
        assert r.decision == "UNDECIDABLE"

    def test_odia_script_undecidable(self):
        r = payee_names_match("ସୁଭାଷ ମହାପାତ୍ର", "Subhash Mahapatra",
                              threshold=0.82, script="odia")
        assert r.decision == "UNDECIDABLE"

    # ── Result shape ──

    def test_result_has_score(self):
        r = payee_names_match("Lata Deshpande", "Lata Deshpande",
                              threshold=0.82, script=None)
        assert 0.0 <= r.score <= 1.0

    def test_result_has_normalized_fields(self):
        r = payee_names_match("Smt. Lata Deshpande", "Lata Deshpande",
                              threshold=0.82, script=None)
        assert r.normalized_ocr == "lata deshpande"
        assert r.normalized_cbs == "lata deshpande"

    def test_undecidable_has_none_score(self):
        r = payee_names_match("மீனாக்ஷி சுந்தரம்", "Meenakshi Sundaram",
                              threshold=0.82, script="tamil")
        assert r.score is None
