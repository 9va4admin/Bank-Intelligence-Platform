"""TDD — 8-script Indic transliterators in payee_normalizer.
Each script: test common name syllables + a full name cross-match.
"""
import pytest
from modules.cts.preprocessing.payee_normalizer import (
    transliterate_by_script,
    payee_names_match,
)


class TestBengaliTransliterator:
    def test_rajat(self):
        r = transliterate_by_script("রজত", "bengali")
        assert "rajat" in r or r.startswith("rajat")

    def test_banerjee(self):
        r = transliterate_by_script("ব্যানার্জি", "bengali")
        # Strict Brahmic: ব্ → b (halant suppresses a), য → y, া → a → "byan..."
        assert "byan" in r or "ban" in r or "ryan" in r

    def test_full_name_match(self):
        r = payee_names_match("রজত কুমার ব্যানার্জি", "Rajat Kumar Banerjee",
                              threshold=0.78, script="bengali")
        assert r.decision in {"MATCH", "FUZZY"}

    def test_mismatch(self):
        r = payee_names_match("রজত কুমার ব্যানার্জি", "Sunita Sharma",
                              threshold=0.78, script="bengali")
        assert r.decision == "MISMATCH"


class TestGurmukhiTransliterator:
    def test_gurpreet(self):
        r = transliterate_by_script("ਗੁਰਪ੍ਰੀਤ", "gurmukhi")
        # Brahmic: ਰਪ੍ਰ → 'r' + a (inherent) + 'p' (halant suppresses a) + 'r'
        assert "gur" in r and "rit" in r

    def test_singh(self):
        r = transliterate_by_script("ਸਿੰਘ", "gurmukhi")
        # ਸਿੰਘ: s+i-matra + ੰ (tippi→n) + gh+a → "singha"
        assert "sing" in r

    def test_full_name_match(self):
        r = payee_names_match("ਗੁਰਪ੍ਰੀਤ ਸਿੰਘ ਖਾਲਸਾ", "Gurpreet Singh Khalsa",
                              threshold=0.78, script="gurmukhi")
        assert r.decision in {"MATCH", "FUZZY"}


class TestGujaratiTransliterator:
    def test_bhupendra(self):
        r = transliterate_by_script("ભૂપેન્દ્ર", "gujarati")
        assert "bhupendr" in r or "bhupend" in r

    def test_shah(self):
        r = transliterate_by_script("શાહ", "gujarati")
        assert "shah" in r or "sha" in r

    def test_full_name_match(self):
        r = payee_names_match("ભૂપેન્દ્ર ભાઈ શાહ", "Bhupendra Bhai Shah",
                              threshold=0.75, script="gujarati")
        assert r.decision in {"MATCH", "FUZZY"}


class TestOdiaTransliterator:
    def test_subhash(self):
        r = transliterate_by_script("ସୁଭାଷ", "odia")
        assert "subh" in r or "subha" in r

    def test_mahapatra(self):
        r = transliterate_by_script("ମହାପାତ୍ର", "odia")
        assert "mahap" in r or "mahap" in r

    def test_full_name_match(self):
        r = payee_names_match("ସୁଭାଷ ଚନ୍ଦ୍ର ମହାପାତ୍ର", "Subhash Chandra Mahapatra",
                              threshold=0.75, script="odia")
        assert r.decision in {"MATCH", "FUZZY"}


class TestTamilTransliterator:
    def test_ramesh(self):
        r = transliterate_by_script("ரமேஷ்", "tamil")
        assert "ramesh" in r or "rames" in r

    def test_meenakshi(self):
        r = transliterate_by_script("மீனாக்ஷி", "tamil")
        assert "meenakshi" in r or "minaksh" in r or "meena" in r

    def test_full_name_match(self):
        r = payee_names_match("ரமேஷ் குமார் நாயர்", "Ramesh Kumar Nair",
                              threshold=0.75, script="tamil")
        assert r.decision in {"MATCH", "FUZZY"}


class TestTeluguTransliterator:
    def test_venkateshwara(self):
        r = transliterate_by_script("వెంకటేశ్వర", "telugu")
        assert "venkat" in r or "vemkat" in r

    def test_reddy(self):
        r = transliterate_by_script("రెడ్డి", "telugu")
        assert "reddi" in r or "redd" in r

    def test_full_name_match(self):
        r = payee_names_match("సుభాషిణి దేవి రెడ్డి", "Subhashini Devi Reddy",
                              threshold=0.75, script="telugu")
        assert r.decision in {"MATCH", "FUZZY"}


class TestKannadaTransliterator:
    def test_vishwanath(self):
        r = transliterate_by_script("ವಿಶ್ವನಾಥ", "kannada")
        assert "vishw" in r or "viswa" in r or "vishvanath" in r

    def test_gowda(self):
        r = transliterate_by_script("ಗೌಡ", "kannada")
        # ಗ + ೌ(o-matra) + ಡ → "go" + "d" (Gowda written phonemically as 'goda')
        assert "go" in r and "d" in r

    def test_full_name_match(self):
        r = payee_names_match("ವಿಶ್ವನಾಥ ಕುಮಾರ್ ಗೌಡ", "Vishwanath Kumar Gowda",
                              threshold=0.75, script="kannada")
        assert r.decision in {"MATCH", "FUZZY"}


class TestMalayalamTransliterator:
    def test_george(self):
        r = transliterate_by_script("ജോർജ്ജ്", "malayalam")
        assert "jor" in r or "george" in r or "jorj" in r

    def test_nair(self):
        r = transliterate_by_script("നായർ", "malayalam")
        assert "nair" in r or "nay" in r

    def test_full_name_match(self):
        r = payee_names_match("ജോർജ്ജ് തോമസ് കുര്യൻ", "George Thomas Kurian",
                              threshold=0.72, script="malayalam")
        assert r.decision in {"MATCH", "FUZZY"}


class TestDispatch:
    def test_devanagari_still_works(self):
        r = payee_names_match("श्री राजेश कुमार वर्मा", "Rajesh Kumar Varma",
                              threshold=0.82, script="devanagari")
        assert r.decision in {"MATCH", "FUZZY"}

    def test_all_scripts_no_longer_undecidable(self):
        """All 9 scripts should now return MATCH/FUZZY/MISMATCH, not UNDECIDABLE."""
        cases = [
            ("ரமேஷ் குமார்", "Ramesh Kumar", "tamil"),
            ("వెంకటేశ్వర రావు", "Venkateshwara Rao", "telugu"),
            ("ವಿಶ್ವನಾಥ ಗೌಡ", "Vishwanath Gowda", "kannada"),
            ("ജോർജ്ജ് തോമസ്", "George Thomas", "malayalam"),
            ("ભૂપેન્દ્ર શાહ", "Bhupendra Shah", "gujarati"),
            ("রজত ব্যানার্জি", "Rajat Banerjee", "bengali"),
            ("ਗੁਰਪ੍ਰੀਤ ਸਿੰਘ", "Gurpreet Singh", "gurmukhi"),
            ("ସୁଭାଷ ମହାପାତ୍ର", "Subhash Mahapatra", "odia"),
        ]
        for indic, english, script in cases:
            r = payee_names_match(indic, english, threshold=0.72, script=script)
            assert r.decision != "UNDECIDABLE", \
                f"{script}: expected MATCH/FUZZY/MISMATCH, got UNDECIDABLE for '{indic}' vs '{english}'"
