"""
Tests for IQA Engine — 17 deterministic NPCI image quality tests per CHI Spec Rev 3.00.

CHI Spec Rev 3.00 §IQA (Appendix 4.1.3.9 + IQA Defect Tests table pp.14-16):
  17 tests, positions A-Q.
  UserField = "{view_marker}:" + 17 single-char codes  (total 21 chars)
  Codes: '0'=pass, '1'=fail, '2'=advisory, 'N'=not-applicable

The 17 test positions (A-Q) per NPCI spec:
  A: Partial Image
  B: Excessive Image Skew
  C: Piggyback Image
  D: Streaks and/or Bands
  E: Bent Corners
  F: Below Minimum Image Size
  G: Exceeds Maximum Image Size
  H: Binary Too Light
  I: Binary Too Dark
  J: Image Height Mismatch
  K: Image Length Mismatch
  L: Below Minimum Image Length
  M: Exceeds Maximum Image Length
  N: Below Minimum Image Height
  O: Exceeds Maximum Image Height
  P: Torn Corner
  Q: ImageFormat (TIFF G4 200dpi for BW, JFIF 100dpi for gray)

UserField view markers: "BFB:" (Front B/W), "BBB:" (Back B/W), "BFG:" (Front Gray)
"""
import pytest


def _make_iqa_input(**kwargs):
    """Create a minimal IQAInput dict; override any field with kwargs."""
    defaults = {
        "front_bw_bytes": b"II\x2a\x00" + b"\x00" * 1020,   # TIFF magic + padding
        "back_bw_bytes": b"II\x2a\x00" + b"\x00" * 508,    # TIFF magic + padding
        "front_gray_bytes": b"\xff\xd8\xff\xe0" + b"\x00" * 2044,  # JFIF magic + padding
        "width_px": 1100,
        "height_px": 550,
        "dpi": 200,
        "bit_depth": 1,
    }
    defaults.update(kwargs)
    return defaults


class TestIQAEngineBasic:
    """Core IQA engine output contract."""

    def test_run_returns_iqa_result(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert result is not None

    def test_result_has_seventeen_tests(self):
        """CHI Spec Rev 3.00: 17 tests (positions A-Q)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert len(result.tests) == 17

    def test_each_test_has_id_and_code(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for test in result.tests:
            assert hasattr(test, "test_id")
            assert hasattr(test, "code")

    def test_test_ids_are_t01_through_t17(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        ids = [t.test_id for t in result.tests]
        assert ids == [f"T{i:02d}" for i in range(1, 18)]

    def test_code_values_are_valid(self):
        """Every code must be '0' (pass), '1' (fail), '2' (advisory), or 'N' (N/A)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        valid_codes = {"0", "1", "2", "N"}
        for test in result.tests:
            assert test.code in valid_codes, f"{test.test_id}: invalid code {test.code!r}"

    def test_t17_is_image_format_test(self):
        """T17 must exist and represent the ImageFormat test."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        t17 = next((t for t in result.tests if t.test_id == "T17"), None)
        assert t17 is not None, "T17 (ImageFormat) test is missing"
        assert t17.code in {"0", "1", "2", "N"}


class TestUserFieldEncoding:
    """UserField string format: '{view_marker}:' + 17 single chars = 21 chars total."""

    def test_user_field_starts_with_bfg_prefix(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert result.user_field().startswith("BFG:")

    def test_user_field_total_length_is_21(self):
        """'BFG:' (4) + 17 codes = 21 characters (CHI Spec Rev 3.00, positions A-Q)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert len(result.user_field()) == 21

    def test_user_field_front_bw_length_is_21(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        result = engine.run(IQAInput(**_make_iqa_input()))
        assert len(result.user_field_front_bw()) == 21

    def test_user_field_back_bw_length_is_21(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        result = engine.run(IQAInput(**_make_iqa_input()))
        assert len(result.user_field_back_bw()) == 21

    def test_user_field_suffix_is_17_chars(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        suffix = result.user_field()[4:]  # after 'BFG:'
        assert len(suffix) == 17

    def test_user_field_all_pass(self):
        """All 17 tests pass → 'BFG:00000000000000000' (17 zeros)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "0"
        assert result.user_field() == "BFG:00000000000000000"

    def test_user_field_with_t17_fail(self):
        """T17 fail → last char of UserField is '1'."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "0"
        result.tests[16].code = "1"  # T17 fails
        uf = result.user_field()
        assert len(uf) == 21
        assert uf[-1] == "1"   # T17 = last position

    def test_user_field_all_chars_single_width(self):
        """Every char position must be exactly 1 character (no multi-char codes)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "N"
        uf = result.user_field()
        assert uf == "BFG:NNNNNNNNNNNNNNNNN"

    def test_front_bw_prefix_is_bfb(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        result = engine.run(IQAInput(**_make_iqa_input()))
        assert result.user_field_front_bw().startswith("BFB:")

    def test_back_bw_prefix_is_bbb(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        result = engine.run(IQAInput(**_make_iqa_input()))
        assert result.user_field_back_bw().startswith("BBB:")

    def test_gray_prefix_is_bfg(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        result = engine.run(IQAInput(**_make_iqa_input()))
        assert result.user_field().startswith("BFG:")


class TestT01Dimensions:
    """T01: Image dimensions must be within acceptable range."""

    def test_t01_passes_for_standard_dimensions(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(width_px=1100, height_px=550))
        result = engine.run(inp)
        t01 = next(t for t in result.tests if t.test_id == "T01")
        assert t01.code == "0"

    def test_t01_fails_for_too_small_image(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(width_px=100, height_px=50))
        result = engine.run(inp)
        t01 = next(t for t in result.tests if t.test_id == "T01")
        assert t01.code in ("1", "2")


class TestT02DPI:
    """T02: DPI must be within acceptable range (200 dpi target for B/W)."""

    def test_t02_passes_at_200_dpi(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(dpi=200))
        result = engine.run(inp)
        t02 = next(t for t in result.tests if t.test_id == "T02")
        assert t02.code == "0"

    def test_t02_fails_at_72_dpi(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(dpi=72))
        result = engine.run(inp)
        t02 = next(t for t in result.tests if t.test_id == "T02")
        assert t02.code in ("1", "2")


class TestT03BitDepth:
    """T03: B/W image must be 1-bit (binary)."""

    def test_t03_passes_for_1_bit(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(bit_depth=1))
        result = engine.run(inp)
        t03 = next(t for t in result.tests if t.test_id == "T03")
        assert t03.code == "0"

    def test_t03_fails_for_8_bit(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(bit_depth=8))
        result = engine.run(inp)
        t03 = next(t for t in result.tests if t.test_id == "T03")
        assert t03.code in ("1", "2")


class TestT04FileSize:
    """T04: Image file size must be within acceptable range."""

    def test_t04_passes_for_reasonable_size(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b"II\x2a\x00" + b"\x00" * 49996))
        result = engine.run(inp)
        t04 = next(t for t in result.tests if t.test_id == "T04")
        assert t04.code == "0"

    def test_t04_fails_for_empty_image(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b""))
        result = engine.run(inp)
        t04 = next(t for t in result.tests if t.test_id == "T04")
        assert t04.code in ("1", "2")


class TestT05T06T07ImagePresence:
    """T05/T06/T07: Front B/W, Back B/W, Front gray images must be present."""

    def test_t05_passes_when_front_bw_present(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b"II\x2a\x00" + b"\x00" * 1020))
        result = engine.run(inp)
        t05 = next(t for t in result.tests if t.test_id == "T05")
        assert t05.code == "0"

    def test_t05_fails_when_front_bw_empty(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b""))
        result = engine.run(inp)
        t05 = next(t for t in result.tests if t.test_id == "T05")
        assert t05.code in ("1", "2")

    def test_t06_passes_when_back_bw_present(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(back_bw_bytes=b"II\x2a\x00" + b"\x00" * 508))
        result = engine.run(inp)
        t06 = next(t for t in result.tests if t.test_id == "T06")
        assert t06.code == "0"

    def test_t07_passes_when_gray_present(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_gray_bytes=b"\xff\xd8\xff\xe0" + b"\x00" * 2044))
        result = engine.run(inp)
        t07 = next(t for t in result.tests if t.test_id == "T07")
        assert t07.code == "0"


class TestT17ImageFormat:
    """T17 (position Q): ImageFormat — TIFF G4 200dpi for BW, JFIF 100dpi for Gray."""

    def test_t17_passes_for_tiff_bw_and_jfif_gray(self):
        """Correct TIFF magic (BW) + JFIF magic (gray) → T17 pass."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        # TIFF little-endian magic: II + 42 (0x2a) + offset
        front_bw = b"II\x2a\x00" + b"\x00" * 1020
        back_bw = b"II\x2a\x00" + b"\x00" * 508
        # JFIF magic: FF D8 FF E0
        front_gray = b"\xff\xd8\xff\xe0" + b"\x00" * 2044
        inp = IQAInput(**_make_iqa_input(
            front_bw_bytes=front_bw,
            back_bw_bytes=back_bw,
            front_gray_bytes=front_gray,
            dpi=200,
            bit_depth=1,
        ))
        result = engine.run(inp)
        t17 = next(t for t in result.tests if t.test_id == "T17")
        assert t17.code in ("0", "2")  # pass or advisory

    def test_t17_is_advisory_or_fail_for_wrong_gray_format(self):
        """Non-JFIF gray image → T17 advisory or fail."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        wrong_gray = b"\x00\x00\x00\x00" + b"\x00" * 2044  # no JFIF magic
        inp = IQAInput(**_make_iqa_input(front_gray_bytes=wrong_gray))
        result = engine.run(inp)
        t17 = next(t for t in result.tests if t.test_id == "T17")
        assert t17.code in ("1", "2")  # fail or advisory

    def test_t17_is_advisory_or_fail_for_wrong_dpi(self):
        """DPI != 200 → T17 advisory or fail (format requirement includes DPI)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(dpi=72))  # wrong DPI
        result = engine.run(inp)
        t17 = next(t for t in result.tests if t.test_id == "T17")
        assert t17.code in ("1", "2")
