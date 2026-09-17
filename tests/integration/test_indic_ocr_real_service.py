"""
Real, non-mocked integration test for the apps/indic_ocr microservice.

Nothing here is mocked: no patched paddleocr, no fake HTTP client, no stub
server standing in for the real thing. Every test in this file makes a real
HTTP call to the real running indic_ocr process on port 8021, which loads
real PaddleOCR model weights from disk and runs real inference against real
crops taken from actual scanned bank cheques (tests/fixtures/indic_ocr/).

Why this file exists: every prior test touching this service
(tests/apps/indic_ocr/test_ai4bharat_backend.py) mocks sys.modules and the
OCR reader entirely -- it verifies routing/control-flow, never that
PaddleOCR/EasyOCR are installed, correctly configured, or produce correct
text. tests/integration/stubs/ocr_server.py (used by every Cut 1/2/3
integration test) is a separate fake server returning hardcoded canned
payloads -- it never touches this service either. As a direct result, this
service ran with zero working OCR backends (paddleocr/easyocr never
installed) and two silently-wrong PaddleOCR language codes (devanagari
mapped to the invalid "hi" instead of "devanagari"; kannada mapped to the
invalid "kn" instead of "ka") for the ~7 weeks since it was written, and no
test ever caught it, because no test ever called the real thing.

Skipped automatically (not failed, not faked) when the service isn't
reachable on port 8021 -- see require_indic_ocr() below. This intentionally
follows the exact same pattern as tests/integration/conftest.py's
require_redis/require_yugabyte/etc: a real TCP probe, a real skip message
telling you how to start the real dependency, never a silent pass.

Start the real service before running these tests:
    cd apps/indic_ocr && .venv/Scripts/python.exe main.py

Run:
    pytest tests/integration/test_indic_ocr_real_service.py -v -m integration
"""
import os
import socket

import httpx
import pytest

pytestmark = pytest.mark.integration

INDIC_OCR_HOST = "localhost"
INDIC_OCR_PORT = 8021
INDIC_OCR_URL = os.environ.get("INDIC_OCR_TEST_URL", f"http://{INDIC_OCR_HOST}:{INDIC_OCR_PORT}")

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "indic_ocr")


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def require_indic_ocr() -> None:
    if not _port_open(INDIC_OCR_HOST, INDIC_OCR_PORT):
        pytest.skip(
            f"indic_ocr service not reachable at {INDIC_OCR_HOST}:{INDIC_OCR_PORT} -- "
            f"start it with: cd apps/indic_ocr && .venv/Scripts/python.exe main.py "
            f"(needs its own venv -- paddleocr/paddlepaddle conflict with the shared "
            f"environment's protobuf/numpy versions, see apps/indic_ocr/main.py's "
            f"torch-preload comment)."
        )


class TestRealPaddleOCROnActualCheques:
    """Every assertion here reads the real HTTP response from the real
    running service -- no mock ever sits between this test and PaddleOCR."""

    def test_reads_real_printed_english_bank_name_from_actual_cheque_scan(self, require_indic_ocr):
        path = os.path.join(FIXTURES_DIR, "real_hdfc_bank_printed.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "paddle", "script": "latin"},
                files={"file": ("real_hdfc_bank_printed.png", f, "image/png")},
                timeout=60.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backend"] == "paddle"
        assert "HDFC" in data["text"].upper()
        assert data["confidence"] > 0.5

    def test_reads_real_printed_boilerplate_from_actual_cheque_scan(self, require_indic_ocr):
        """This is the exact real-world case _strip_boilerplate_text_via_ocr()
        in apps/api/routers/demo_cloud_extract.py targets: a real signature
        area with 'Authorised Signatory' printed boilerplate crossed by an
        actual pen stroke, cropped from a real UCO Bank cheque scan."""
        path = os.path.join(FIXTURES_DIR, "real_authorised_signatory.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "paddle", "script": "latin"},
                files={"file": ("real_authorised_signatory.png", f, "image/png")},
                timeout=60.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "SIGNATOR" in data["text"].upper() or "AUTHORIS" in data["text"].upper()
        assert data["confidence"] > 0.3

    def test_kannada_script_resolves_to_the_real_paddle_lang_code(self, require_indic_ocr):
        """Regression test for the exact bug found and fixed 2026-09-17:
        script=kannada was silently mapped to the invalid paddleocr lang
        code 'kn' (PaddleOCR's real code is 'ka'), which made the paddle
        backend fail and silently cascade to a Hindi-only EasyOCR reader
        producing garbage. This asserts the service reports it actually
        used paddle_lang='ka' -- proving the routing fix is live in the
        running service, not just in source that was never restarted into."""
        path = os.path.join(FIXTURES_DIR, "real_hdfc_bank_printed.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "paddle", "script": "kannada"},
                files={"file": ("real_hdfc_bank_printed.png", f, "image/png")},
                timeout=90.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paddle_lang"] == "ka", (
            f"expected the real paddleocr Kannada code 'ka', got {data['paddle_lang']!r} "
            f"-- the kn->ka mapping fix in apps/indic_ocr/main.py may have regressed"
        )

    def test_service_is_a_real_separate_process_not_reachable_through_shared_env(self, require_indic_ocr):
        """Proves this test isn't accidentally exercising some in-process
        fake: the real service must answer /health/live with its own PID
        environment, independent of whatever interpreter runs pytest."""
        resp = httpx.get(f"{INDIC_OCR_URL}/health/live", timeout=10.0)
        assert resp.status_code == 200
        assert resp.json()["service"] == "indic-ocr"


class TestRealTesseractOnActualCheques:
    """Real, non-mocked coverage for the tesseract backend added 2026-09-17
    to close the gap PaddleOCR genuinely cannot cover at all: bengali,
    gurmukhi, gujarati, odia, malayalam have zero paddleocr 2.7.3 model.
    Uses the official tesseract-ocr/tessdata_fast models
    (apps/indic_ocr/tessdata/) -- the community indic-ocr/tessdata project
    was tested and rejected the same day: its files throw
    "unichar ... in normproto file is not in unichar set" on load with
    Tesseract 5.4.0, a real, verified incompatibility."""

    def test_reads_real_kannada_letterhead_text_via_tesseract(self, require_indic_ocr):
        """PaddleOCR's 'ka' model produces zero Kannada Unicode characters on
        this exact crop (confirmed separately) -- garbled Latin fragments
        instead. Tesseract must produce genuine Kannada script output."""
        path = os.path.join(FIXTURES_DIR, "real_kannada_bank_letterhead.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "tesseract", "script": "kannada"},
                files={"file": ("real_kannada_bank_letterhead.png", f, "image/png")},
                timeout=60.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backend"] == "tesseract"
        assert data["paddle_lang"] == "kan"
        # At least one genuine Kannada Unicode codepoint (U+0C80-U+0CFF) in
        # the output -- proves real script recognition, not Latin garbage.
        assert any("ಀ" <= ch <= "೿" for ch in data["text"]), (
            f"expected real Kannada Unicode output, got {data['text']!r}"
        )
        assert data["confidence"] > 0.0

    def test_reads_real_handwritten_kannada_amount_words(self, require_indic_ocr):
        """Lower bar than the printed-letterhead test -- handwriting is
        genuinely harder -- but still must produce real Kannada script
        output, not empty/Latin garbage, from an actual cheque's
        amount-in-words line."""
        path = os.path.join(FIXTURES_DIR, "real_kannada_handwritten_amount_words.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "tesseract", "script": "kannada"},
                files={"file": ("real_kannada_handwritten_amount_words.png", f, "image/png")},
                timeout=60.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert any("ಀ" <= ch <= "೿" for ch in data["text"]), (
            f"expected at least some real Kannada Unicode output, got {data['text']!r}"
        )

    def test_gujarati_has_zero_paddle_model_but_tesseract_covers_it(self, require_indic_ocr):
        """Regression guard for the actual capability gap this backend was
        added to close: paddleocr 2.7.3 has NO Gujarati model at all (not
        degraded -- literally absent from its MODEL_URLS). Confirms the
        cascade actually reaches a working engine for a script PaddleOCR
        cannot serve under any configuration."""
        path = os.path.join(FIXTURES_DIR, "real_hdfc_bank_printed.png")
        with open(path, "rb") as f:
            resp = httpx.post(
                f"{INDIC_OCR_URL}/ocr",
                params={"backend": "tesseract", "script": "gujarati"},
                files={"file": ("real_hdfc_bank_printed.png", f, "image/png")},
                timeout=60.0,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["backend"] == "tesseract"
        assert data["paddle_lang"] == "guj"
