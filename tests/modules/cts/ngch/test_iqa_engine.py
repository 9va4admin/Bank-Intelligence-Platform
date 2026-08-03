"""
Tests for IQA Engine — 16 deterministic NPCI image quality tests.

CTS Spec Rev 3.0 §IQA: the Image Quality Assessment is NOT AI-based.
It applies 16 rule-based tests to each image and encodes results as:
  UserField = "BFG:" + 16 single-char codes
  where each char is: '0'=pass, '1'=fail, '2'=advisory, 'N'=not-applicable

The UserField is embedded in CXF XML <ImageViewAnalysis><UserField>.

The 16 tests (T01–T16) per NPCI spec:
  T01: Image dimensions within acceptable range
  T02: Image DPI within acceptable range (200 dpi target for B/W)
  T03: Bit depth = 1 (binary/black-and-white image)
  T04: Image file size within acceptable range
  T05: Front image available
  T06: Back image available
  T07: Gray image available
  T08: MICR band present (bottom 20% of image not blank)
  T09: Image skew within acceptable range (<3 degrees)
  T10: Contrast acceptable (not too dark or too light)
  T11: No torn corner detected
  T12: No crumple detected
  T13: Signature area not blank
  T14: Amount area readable
  T15: Date area readable
  T16: Payee area readable

RED phase: all tests must fail before iqa_engine.py is created.
"""
import pytest


def _make_iqa_input(**kwargs):
    """Create a minimal IQAInput dict; override any field with kwargs."""
    defaults = {
        "front_bw_bytes": b"\x00" * 1024,
        "back_bw_bytes": b"\x00" * 512,
        "front_gray_bytes": b"\x00" * 2048,
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

    def test_result_has_sixteen_tests(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert len(result.tests) == 16

    def test_each_test_has_id_and_code(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for test in result.tests:
            assert hasattr(test, "test_id")
            assert hasattr(test, "code")

    def test_test_ids_are_t01_through_t16(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        ids = [t.test_id for t in result.tests]
        assert ids == [f"T{i:02d}" for i in range(1, 17)]

    def test_code_values_are_valid(self):
        """Every code must be '0' (pass), '1' (fail), '2' (advisory), or 'N' (N/A)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        valid_codes = {"0", "1", "2", "N"}
        for test in result.tests:
            assert test.code in valid_codes, f"{test.test_id}: invalid code {test.code!r}"


class TestUserFieldEncoding:
    """UserField string format: 'BFG:' + 16 single chars."""

    def test_user_field_starts_with_bfg_prefix(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert result.user_field().startswith("BFG:")

    def test_user_field_total_length_is_20(self):
        """'BFG:' (4) + 16 codes = 20 characters."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        assert len(result.user_field()) == 20

    def test_user_field_suffix_is_16_chars(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        suffix = result.user_field()[4:]  # after 'BFG:'
        assert len(suffix) == 16

    def test_user_field_all_pass(self):
        """All 16 tests pass → 'BFG:0000000000000000'."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput, IQATestResult

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        # Force all codes to '0'
        for t in result.tests:
            t.code = "0"
        assert result.user_field() == "BFG:0000000000000000"

    def test_user_field_with_one_fail(self):
        """T02 fail → 'BFG:0100000000000000' (second char is '1')."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "0"
        result.tests[1].code = "1"  # T02 fails
        uf = result.user_field()
        assert uf[4] == "0"   # T01 pass
        assert uf[5] == "1"   # T02 fail
        assert uf[6:] == "00000000000000"  # T03-T16 pass

    def test_user_field_not_applicable(self):
        """Not-applicable tests use 'N' (one char, not '-1')."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "0"
        result.tests[15].code = "N"  # T16 not applicable
        uf = result.user_field()
        assert uf[-1] == "N"
        assert len(uf) == 20  # still exactly 20 chars

    def test_user_field_all_chars_single_width(self):
        """Every char position must be exactly 1 character (no '-1' literals)."""
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input())
        result = engine.run(inp)
        for t in result.tests:
            t.code = "N"
        uf = result.user_field()
        assert uf == "BFG:NNNNNNNNNNNNNNNN"


class TestT01Dimensions:
    """T01: Image dimensions must be within acceptable range."""

    def test_t01_passes_for_standard_dimensions(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        # Standard cheque: ~1100×550 px at 200 dpi
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
        assert t01.code in ("1", "2")  # fail or advisory


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
        # A realistic front B/W TIFF G4: ~20KB–100KB
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b"\x00" * 50_000))
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
        inp = IQAInput(**_make_iqa_input(front_bw_bytes=b"\x00" * 1024))
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
        inp = IQAInput(**_make_iqa_input(back_bw_bytes=b"\x00" * 512))
        result = engine.run(inp)
        t06 = next(t for t in result.tests if t.test_id == "T06")
        assert t06.code == "0"

    def test_t07_passes_when_gray_present(self):
        from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput

        engine = IQAEngine()
        inp = IQAInput(**_make_iqa_input(front_gray_bytes=b"\x00" * 2048))
        result = engine.run(inp)
        t07 = next(t for t in result.tests if t.test_id == "T07")
        assert t07.code == "0"
