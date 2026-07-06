"""
IQA Engine — 16 deterministic NPCI image quality tests per CTS Spec Rev 3.0.

NOT AI-based. All 16 tests are rule-based checks against image metadata and
content dimensions. Results are encoded in the CXF UserField as:
  "BFG:" + 16 single-char codes
  where each char ∈ {'0'=pass, '1'=fail, '2'=advisory, 'N'=not-applicable}

UserField is embedded in CXF XML: <ImageViewAnalysis><UserField>.

Tests T01–T16:
  T01: Image dimensions within acceptable range
  T02: Image DPI within acceptable range (200 dpi target)
  T03: Bit depth = 1 (binary B/W)
  T04: Image file size within acceptable range
  T05: Front B/W image present
  T06: Back B/W image present
  T07: Front gray image present
  T08: MICR band area not blank (content check)
  T09: Image skew within acceptable range
  T10: Contrast acceptable
  T11: No torn corner
  T12: No crumple
  T13: Signature area not blank
  T14: Amount area readable
  T15: Date area readable
  T16: Payee area readable

T08–T16 require pixel-level analysis; these are stubbed as advisory ('2') when
actual image content analysis is not available (depends on image decoder).
"""
from dataclasses import dataclass, field
from typing import List

from pydantic import BaseModel, ConfigDict

# --- Thresholds (Rule-based — sourced from CTS Spec Rev 3.0 IQA section) ---
_MIN_WIDTH_PX = 800
_MAX_WIDTH_PX = 2000
_MIN_HEIGHT_PX = 300
_MAX_HEIGHT_PX = 900
_MIN_DPI = 190
_MAX_DPI = 210
_EXPECTED_BIT_DEPTH = 1
_MIN_SIZE_BYTES = 100         # suspiciously tiny = fail
_MAX_SIZE_BYTES = 2_000_000   # >2 MB = advisory (may cause NGCH rejection)
_REASONABLE_SIZE_BYTES = 5_000  # anything ≥ this is "reasonable"


# --- Data models ---

class IQAInput(BaseModel):
    """Input to the IQA Engine — image metadata and raw bytes."""
    model_config = ConfigDict(frozen=True)

    front_bw_bytes: bytes     # Front B/W TIFF G4 200dpi
    back_bw_bytes: bytes      # Back B/W TIFF G4 200dpi
    front_gray_bytes: bytes   # Front gray JPEG JFIF 100dpi
    width_px: int             # Image width in pixels
    height_px: int            # Image height in pixels
    dpi: int                  # Capture DPI
    bit_depth: int            # Bit depth of the front B/W image


@dataclass
class IQATestResult:
    """Result for a single IQA test."""
    test_id: str   # "T01" .. "T16"
    code: str      # '0'=pass, '1'=fail, '2'=advisory, 'N'=not-applicable


@dataclass
class IQAResult:
    """Aggregate result of all 16 IQA tests."""
    tests: List[IQATestResult] = field(default_factory=list)

    def user_field(self) -> str:
        """Encode as 'BFG:' + 16 single-char codes (total 20 chars)."""
        codes = "".join(t.code for t in self.tests)
        return f"BFG:{codes}"


# --- Engine ---

class IQAEngine:
    """Applies all 16 IQA rule-based tests to a cheque image set."""

    def run(self, inp: IQAInput) -> IQAResult:
        """Run all 16 tests and return aggregate IQAResult."""
        tests = [
            self._t01_dimensions(inp),
            self._t02_dpi(inp),
            self._t03_bit_depth(inp),
            self._t04_file_size(inp),
            self._t05_front_bw_present(inp),
            self._t06_back_bw_present(inp),
            self._t07_gray_present(inp),
            self._t08_micr_band(inp),
            self._t09_skew(inp),
            self._t10_contrast(inp),
            self._t11_torn_corner(inp),
            self._t12_crumple(inp),
            self._t13_signature_area(inp),
            self._t14_amount_area(inp),
            self._t15_date_area(inp),
            self._t16_payee_area(inp),
        ]
        return IQAResult(tests=tests)

    # --- Individual test implementations ---

    def _t01_dimensions(self, inp: IQAInput) -> IQATestResult:
        ok = (
            _MIN_WIDTH_PX <= inp.width_px <= _MAX_WIDTH_PX
            and _MIN_HEIGHT_PX <= inp.height_px <= _MAX_HEIGHT_PX
        )
        return IQATestResult(test_id="T01", code="0" if ok else "1")

    def _t02_dpi(self, inp: IQAInput) -> IQATestResult:
        ok = _MIN_DPI <= inp.dpi <= _MAX_DPI
        return IQATestResult(test_id="T02", code="0" if ok else "1")

    def _t03_bit_depth(self, inp: IQAInput) -> IQATestResult:
        ok = inp.bit_depth == _EXPECTED_BIT_DEPTH
        return IQATestResult(test_id="T03", code="0" if ok else "1")

    def _t04_file_size(self, inp: IQAInput) -> IQATestResult:
        size = len(inp.front_bw_bytes)
        if size < _MIN_SIZE_BYTES:
            return IQATestResult(test_id="T04", code="1")
        if size > _MAX_SIZE_BYTES:
            return IQATestResult(test_id="T04", code="2")  # advisory
        return IQATestResult(test_id="T04", code="0")

    def _t05_front_bw_present(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T05", code="0" if inp.front_bw_bytes else "1")

    def _t06_back_bw_present(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T06", code="0" if inp.back_bw_bytes else "1")

    def _t07_gray_present(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T07", code="0" if inp.front_gray_bytes else "1")

    # T08–T16: pixel-level analysis stubs.
    # '2' = advisory (data present but not deeply analysed without image decoder).
    # A future implementation using Pillow or a C extension replaces these stubs.
    def _t08_micr_band(self, inp: IQAInput) -> IQATestResult:
        has_content = len(inp.front_bw_bytes) >= _MIN_SIZE_BYTES
        return IQATestResult(test_id="T08", code="2" if has_content else "1")

    def _t09_skew(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T09", code="2")

    def _t10_contrast(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T10", code="2")

    def _t11_torn_corner(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T11", code="2")

    def _t12_crumple(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T12", code="2")

    def _t13_signature_area(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T13", code="2")

    def _t14_amount_area(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T14", code="2")

    def _t15_date_area(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T15", code="2")

    def _t16_payee_area(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T16", code="2")
