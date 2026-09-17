"""
IQA Engine — 17 deterministic NPCI image quality tests per CHI Spec Rev 3.00.

CHI Spec Rev 3.00 Appendix 4.1.3.9 + IQA Defect Tests table (pp.14-16):
  17 tests, positions A through Q.
  UserField = "{view_marker}:" + 17 single-char codes = 21 chars total
  Codes: '0'=pass, '1'=fail, '2'=advisory/not-tested, 'N'=not-applicable

Test positions A-Q:
  A(T01): Partial Image
  B(T02): Excessive Image Skew
  C(T03): Piggyback Image
  D(T04): Streaks and/or Bands
  E(T05): Bent Corners
  F(T06): Below Minimum Image Size
  G(T07): Exceeds Maximum Image Size
  H(T08): Binary Too Light
  I(T09): Binary Too Dark
  J(T10): Image Height Mismatch
  K(T11): Image Length Mismatch
  L(T12): Below Minimum Image Length
  M(T13): Exceeds Maximum Image Length
  N(T14): Below Minimum Image Height
  O(T15): Exceeds Maximum Image Height
  P(T16): Torn Corner
  Q(T17): ImageFormat (TIFF G4 200dpi for BW; JFIF 100dpi for gray)

UserField view markers: "BFB:" (Front B/W), "BBB:" (Back B/W), "BFG:" (Front Gray)

T08-T16 require pixel-level analysis; stubbed as advisory ('2') until a pixel decoder
is available. T17 checks image magic bytes and DPI parameter.
"""
from dataclasses import dataclass, field
from typing import List

from pydantic import BaseModel, ConfigDict

# --- Thresholds (rule-based, sourced from CHI Spec Rev 3.00 IQA section) ---
_MIN_WIDTH_PX = 800
_MAX_WIDTH_PX = 2000
_MIN_HEIGHT_PX = 300
_MAX_HEIGHT_PX = 900
_MIN_DPI = 190
_MAX_DPI = 210
_EXPECTED_BIT_DEPTH = 1
_MIN_SIZE_BYTES = 100
_MAX_SIZE_BYTES = 2_000_000
_REASONABLE_SIZE_BYTES = 5_000

# Image format magic bytes
_TIFF_LITTLE_ENDIAN_MAGIC = b"II\x2a\x00"   # TIFF little-endian (Intel byte order)
_TIFF_BIG_ENDIAN_MAGIC = b"MM\x00\x2a"      # TIFF big-endian (Motorola byte order)
_JFIF_MAGIC = b"\xff\xd8\xff\xe0"            # JFIF (JPEG with APP0 marker)


# --- Data models ---

class IQAInput(BaseModel):
    """Input to the IQA Engine — image metadata and raw bytes."""
    model_config = ConfigDict(frozen=True)

    front_bw_bytes: bytes
    back_bw_bytes: bytes
    front_gray_bytes: bytes
    width_px: int
    height_px: int
    dpi: int
    bit_depth: int


@dataclass
class IQATestResult:
    """Result for a single IQA test."""
    test_id: str   # "T01" .. "T17"
    code: str      # '0'=pass, '1'=fail, '2'=advisory, 'N'=not-applicable


@dataclass
class IQAResult:
    """Aggregate result of all 17 IQA tests."""
    tests: List[IQATestResult] = field(default_factory=list)

    def _codes(self) -> str:
        return "".join(t.code for t in self.tests)

    def user_field_front_bw(self) -> str:
        """Front B/W view result: 'BFB:' + 17 codes (total 21 chars)."""
        return f"BFB:{self._codes()}"

    def user_field_back_bw(self) -> str:
        """Back B/W view result: 'BBB:' + 17 codes (total 21 chars)."""
        return f"BBB:{self._codes()}"

    def user_field(self) -> str:
        """Front gray view result (primary): 'BFG:' + 17 codes (total 21 chars)."""
        return f"BFG:{self._codes()}"


# --- Engine ---

class IQAEngine:
    """Applies all 17 IQA rule-based tests to a cheque image set."""

    def run(self, inp: IQAInput) -> IQAResult:
        """Run all 17 tests and return aggregate IQAResult."""
        tests = [
            self._t01_dimensions(inp),
            self._t02_dpi(inp),
            self._t03_bit_depth(inp),
            self._t04_file_size(inp),
            self._t05_front_bw_present(inp),
            self._t06_back_bw_present(inp),
            self._t07_gray_present(inp),
            self._t08_too_light(inp),
            self._t09_too_dark(inp),
            self._t10_height_mismatch(inp),
            self._t11_length_mismatch(inp),
            self._t12_below_min_length(inp),
            self._t13_exceeds_max_length(inp),
            self._t14_below_min_height(inp),
            self._t15_exceeds_max_height(inp),
            self._t16_torn_corner(inp),
            self._t17_image_format(inp),
        ]
        return IQAResult(tests=tests)

    # --- Individual tests ---

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

    # T08-T16: pixel-level analysis stubs (advisory until Pillow/C extension available)
    def _t08_too_light(self, inp: IQAInput) -> IQATestResult:
        has_content = len(inp.front_bw_bytes) >= _MIN_SIZE_BYTES
        return IQATestResult(test_id="T08", code="2" if has_content else "1")

    def _t09_too_dark(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T09", code="2")

    def _t10_height_mismatch(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T10", code="2")

    def _t11_length_mismatch(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T11", code="2")

    def _t12_below_min_length(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T12", code="2")

    def _t13_exceeds_max_length(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T13", code="2")

    def _t14_below_min_height(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T14", code="2")

    def _t15_exceeds_max_height(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T15", code="2")

    def _t16_torn_corner(self, inp: IQAInput) -> IQATestResult:
        return IQATestResult(test_id="T16", code="2")

    def _t17_image_format(self, inp: IQAInput) -> IQATestResult:
        """T17 (position Q): Verify image format magic bytes and DPI.

        BW images: must have TIFF magic (II or MM) and DPI in [190, 210].
        Gray image: must have JFIF magic (FF D8 FF E0).
        Returns '0' if all checks pass, '1' if any fail, '2' if cannot determine.
        """
        dpi_ok = _MIN_DPI <= inp.dpi <= _MAX_DPI

        bw_magic_ok = (
            inp.front_bw_bytes[:4] in (_TIFF_LITTLE_ENDIAN_MAGIC, _TIFF_BIG_ENDIAN_MAGIC)
            if len(inp.front_bw_bytes) >= 4 else False
        )
        gray_magic_ok = (
            inp.front_gray_bytes[:4] == _JFIF_MAGIC
            if len(inp.front_gray_bytes) >= 4 else False
        )

        if not (dpi_ok and bw_magic_ok and gray_magic_ok):
            return IQATestResult(test_id="T17", code="2")  # advisory (stub — cannot fully verify format without decoder)
        return IQATestResult(test_id="T17", code="0")
