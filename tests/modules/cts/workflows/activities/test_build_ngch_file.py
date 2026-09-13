"""
Tests for build_ngch_file Temporal activity — CHI Spec Rev 3.00 compliant.

The activity orchestrates:
  1. IQAEngine.run()                        → 3 UserFields (21 chars each: BFB/BBB/BFG)
  2. NGCHSigner.sign_micr(keyword-args)     → MICRDSResult (fingerprint + 344-char sig)
  3. NGCHSigner.sign_image() × 3 per instr → 3 × 256-byte ImageDS
  4. CIBFAssembler.assemble_lot()           → CIBFLotResult (single lot-level binary)
  5. CXFBuilder.build()                     → CXF XML bytes (FileHeader root, attributes)

New API vs old:
  - item_seq_no: 14 chars (not 5)
  - sign_micr() uses keyword args (not positional micr_line string)
  - sign_image() called 3× per instrument (not 1×): front BW, back BW, front gray
  - CIBF is lot-level (one binary blob), not per-instrument
  - Result carries: cxf_bytes, cibf_bytes (lot), cxf_filename, cibf_filename
  - BuildNGCHFileInput gains: clearing_type, file_id, date_ddmmyyyy, time_hhmmss
  - InstrumentBuildInput gains: payor_bank_rout_no, serial_no, trans_code, account_no, doc_type

RED phase: tests fail before build_ngch_file.py is updated.
"""
import pytest
from unittest.mock import MagicMock
from typing import List


# ── Constants ──────────────────────────────────────────────────────────────────

_FAKE_RSA_SIG_256 = b"\xAB" * 256     # 256-byte fake RSA signature (ImageDS + MICRDS raw)
_FAKE_FRONT_BW   = b"II\x2a\x00" + b"\x00" * 500   # fake TIFF little-endian
_FAKE_BACK_BW    = b"II\x2a\x00" + b"\x00" * 300
_FAKE_FRONT_GRAY = b"\xff\xd8\xff\xe0" + b"\x00" * 400   # fake JFIF


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_instrument(**overrides) -> dict:
    """Minimal valid InstrumentBuildInput kwargs."""
    defaults = dict(
        item_seq_no="00000101000001",       # 14 chars — mandatory per spec
        payor_bank_rout_no="400160001",     # 9-digit routing of drawee bank
        account_no="****4521",              # masked for logging
        serial_no="123456",
        trans_code="10",
        doc_type="01",
        micr_line="400160001234",
        drawee_ifsc="SBIN0000123",
        amount_paise=5_000_000,
        front_bw_bytes=_FAKE_FRONT_BW,
        back_bw_bytes=_FAKE_BACK_BW,
        front_gray_bytes=_FAKE_FRONT_GRAY,
        width_px=1200,
        height_px=500,
        dpi=200,
        bit_depth=1,
        presenting_bank_rout_no="000550050",
        cycle_no="01",
        presentment_date="01042026",
        batch_id="BATCH-001",
    )
    defaults.update(overrides)
    return defaults


def _make_input(**overrides) -> dict:
    """Minimal valid BuildNGCHFileInput kwargs."""
    defaults = dict(
        bank_id="test-bank",
        lot_number="LOT-001",
        session_id="SES-0619-001",
        routing_no="000550050",
        clearing_type="14",
        file_id="0001",
        date_ddmmyyyy="01042026",
        time_hhmmss="103000",
        instruments=[_make_instrument()],
    )
    defaults.update(overrides)
    return defaults


def _make_mock_hsm():
    """Mock HSM: sign() returns 256 bytes of 0xAB."""
    hsm = MagicMock()
    hsm.sign.return_value = _FAKE_RSA_SIG_256
    return hsm


def _run(**input_overrides):
    """Build and run the activity with a mock HSM."""
    from modules.cts.workflows.activities.build_ngch_file import (
        build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
    )
    raw = _make_input(**input_overrides)
    instrs = raw.pop("instruments")
    inp = BuildNGCHFileInput(
        **raw,
        instruments=[InstrumentBuildInput(**i) for i in instrs],
    )
    return build_ngch_file(inp, hsm=_make_mock_hsm())


# ── Module structure ───────────────────────────────────────────────────────────

class TestBuildNGCHFileActivityExists:
    def test_module_importable(self):
        from modules.cts.workflows.activities import build_ngch_file  # noqa: F401

    def test_function_exists(self):
        from modules.cts.workflows.activities.build_ngch_file import build_ngch_file
        assert callable(build_ngch_file)

    def test_input_model_exists(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        assert BuildNGCHFileInput is not None

    def test_result_model_exists(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileResult
        assert BuildNGCHFileResult is not None

    def test_instrument_input_model_exists(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        assert InstrumentBuildInput is not None


# ── InstrumentBuildInput ───────────────────────────────────────────────────────

class TestInstrumentBuildInput:
    def test_accepts_valid_instrument(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        instr = InstrumentBuildInput(**_make_instrument())
        assert instr.item_seq_no == "00000101000001"

    def test_requires_payor_bank_rout_no(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        import pydantic
        bad = _make_instrument()
        del bad["payor_bank_rout_no"]
        with pytest.raises((pydantic.ValidationError, TypeError)):
            InstrumentBuildInput(**bad)

    def test_requires_serial_no(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        import pydantic
        bad = _make_instrument()
        del bad["serial_no"]
        with pytest.raises((pydantic.ValidationError, TypeError)):
            InstrumentBuildInput(**bad)

    def test_requires_trans_code(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        import pydantic
        bad = _make_instrument()
        del bad["trans_code"]
        with pytest.raises((pydantic.ValidationError, TypeError)):
            InstrumentBuildInput(**bad)

    def test_requires_doc_type(self):
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput
        import pydantic
        bad = _make_instrument()
        del bad["doc_type"]
        with pytest.raises((pydantic.ValidationError, TypeError)):
            InstrumentBuildInput(**bad)


# ── BuildNGCHFileInput ─────────────────────────────────────────────────────────

class TestBuildNGCHFileInputModel:
    def test_accepts_valid_input(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            BuildNGCHFileInput, InstrumentBuildInput,
        )
        inp = BuildNGCHFileInput(
            **{k: v for k, v in _make_input().items() if k != "instruments"},
            instruments=[InstrumentBuildInput(**_make_instrument())],
        )
        assert inp.session_id == "SES-0619-001"

    def test_requires_clearing_type(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        import pydantic
        bad = {k: v for k, v in _make_input().items() if k not in ("clearing_type", "instruments")}
        with pytest.raises((pydantic.ValidationError, TypeError)):
            BuildNGCHFileInput(**bad, instruments=[])

    def test_requires_routing_no(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        import pydantic
        bad = {k: v for k, v in _make_input().items() if k not in ("routing_no", "instruments")}
        with pytest.raises((pydantic.ValidationError, TypeError)):
            BuildNGCHFileInput(**bad, instruments=[])


# ── HSM sign call counts ───────────────────────────────────────────────────────

class TestHSMCallCounts:
    """sign_micr uses 1 HSM call; sign_image uses 3 per instrument."""

    def test_one_instrument_calls_hsm_four_times(self):
        """1 instrument × (1 MICRDS + 3 ImageDS) = 4 HSM sign calls."""
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        hsm = _make_mock_hsm()
        raw = _make_input()
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        build_ngch_file(inp, hsm=hsm)
        assert hsm.sign.call_count == 4

    def test_two_instruments_calls_hsm_eight_times(self):
        """2 instruments × 4 = 8 HSM sign calls."""
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        hsm = _make_mock_hsm()
        raw = _make_input(instruments=[
            _make_instrument(item_seq_no="00000101000001"),
            _make_instrument(item_seq_no="00000101000002"),
        ])
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        build_ngch_file(inp, hsm=hsm)
        assert hsm.sign.call_count == 8

    def test_sign_image_called_with_front_bw_bytes(self):
        """sign_image must be called with the front BW image bytes."""
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        hsm = _make_mock_hsm()
        raw = _make_input()
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        build_ngch_file(inp, hsm=hsm)
        # At least one call was with the front BW bytes
        call_args_list = [call[0][0] for call in hsm.sign.call_args_list]
        assert _FAKE_FRONT_BW in call_args_list

    def test_sign_image_called_with_back_bw_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        hsm = _make_mock_hsm()
        raw = _make_input()
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        build_ngch_file(inp, hsm=hsm)
        call_args_list = [call[0][0] for call in hsm.sign.call_args_list]
        assert _FAKE_BACK_BW in call_args_list

    def test_sign_image_called_with_front_gray_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        hsm = _make_mock_hsm()
        raw = _make_input()
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        build_ngch_file(inp, hsm=hsm)
        call_args_list = [call[0][0] for call in hsm.sign.call_args_list]
        assert _FAKE_FRONT_GRAY in call_args_list


# ── CXF output ────────────────────────────────────────────────────────────────

class TestCXFOutput:
    def test_cxf_bytes_is_bytes(self):
        result = _run()
        assert isinstance(result.cxf_bytes, bytes)

    def test_cxf_bytes_starts_with_xml_decl(self):
        result = _run()
        assert result.cxf_bytes.startswith(b"<?xml")

    def test_cxf_bytes_is_valid_xml(self):
        import xml.etree.ElementTree as ET
        result = _run()
        root = ET.fromstring(result.cxf_bytes)
        assert root is not None

    def test_cxf_has_cxf_namespace(self):
        result = _run()
        assert b"urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005" in result.cxf_bytes

    def test_cxf_root_is_fileheader(self):
        result = _run()
        assert b"FileHeader" in result.cxf_bytes

    def test_cxf_contains_session_id(self):
        result = _run(session_id="MY-UNIQUE-SES")
        assert b"MY-UNIQUE-SES" in result.cxf_bytes

    def test_cxf_contains_iqa_prefixes(self):
        result = _run()
        assert b"BFB:" in result.cxf_bytes
        assert b"BBB:" in result.cxf_bytes
        assert b"BFG:" in result.cxf_bytes


# ── CIBF output (lot-level) ────────────────────────────────────────────────────

class TestCIBFOutput:
    def test_result_has_cibf_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileResult
        result = _run()
        assert hasattr(result, "cibf_bytes")

    def test_cibf_bytes_is_bytes(self):
        result = _run()
        assert isinstance(result.cibf_bytes, bytes)
        assert len(result.cibf_bytes) > 0

    def test_cibf_size_is_3ds_plus_3images_per_instrument(self):
        """Per-instrument: 3×256 DS + len(FB) + len(BB) + len(FG)."""
        result = _run()
        expected = (
            3 * 256
            + len(_FAKE_FRONT_BW)
            + len(_FAKE_BACK_BW)
            + len(_FAKE_FRONT_GRAY)
        )
        assert len(result.cibf_bytes) == expected

    def test_two_instruments_cibf_double_size(self):
        raw = _make_input(instruments=[
            _make_instrument(item_seq_no="00000101000001"),
            _make_instrument(item_seq_no="00000101000002"),
        ])
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        result = build_ngch_file(inp, hsm=_make_mock_hsm())
        per_instr = 3 * 256 + len(_FAKE_FRONT_BW) + len(_FAKE_BACK_BW) + len(_FAKE_FRONT_GRAY)
        assert len(result.cibf_bytes) == 2 * per_instr


# ── Filename generation ────────────────────────────────────────────────────────

class TestFilenameGeneration:
    def test_result_has_cxf_filename(self):
        result = _run()
        assert hasattr(result, "cxf_filename")

    def test_result_has_cibf_filename(self):
        result = _run()
        assert hasattr(result, "cibf_filename")

    def test_cxf_filename_format(self):
        """CXF filename: CXF_{routing}_{ddmmyyyy}_{hhmmss}_{ct}_{fid}.XML"""
        result = _run(
            routing_no="000550050",
            date_ddmmyyyy="01042026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        assert result.cxf_filename == "CXF_000550050_01042026_103000_14_0001.XML"

    def test_cibf_filename_format(self):
        """CIBF filename: CIBF_{routing}_{ddmmyyyy}_{hhmmss}_{ct}_{fid}_{nn}.img"""
        result = _run(
            routing_no="000550050",
            date_ddmmyyyy="01042026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        # Modifier is "01" for first CIBF of the file
        assert result.cibf_filename == "CIBF_000550050_01042026_103000_14_0001_01.img"

    def test_clearing_type_14_accepted(self):
        result = _run(clearing_type="14")
        assert "14" in result.cxf_filename

    def test_clearing_type_99_accepted(self):
        result = _run(clearing_type="99")
        assert "99" in result.cxf_filename


# ── Instrument count ───────────────────────────────────────────────────────────

class TestInstrumentCount:
    def test_instrument_count_matches_input(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
        )
        raw = _make_input(instruments=[
            _make_instrument(item_seq_no="00000101000001"),
            _make_instrument(item_seq_no="00000101000002"),
            _make_instrument(item_seq_no="00000101000003"),
        ])
        instrs = raw.pop("instruments")
        inp = BuildNGCHFileInput(**raw, instruments=[InstrumentBuildInput(**i) for i in instrs])
        result = build_ngch_file(inp, hsm=_make_mock_hsm())
        assert result.instrument_count == 3


# ── Error paths ────────────────────────────────────────────────────────────────

class TestErrorPaths:
    def test_empty_instruments_raises(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        with pytest.raises((ValueError, Exception)):
            build_ngch_file(
                BuildNGCHFileInput(
                    **{k: v for k, v in _make_input().items() if k != "instruments"},
                    instruments=[],
                ),
                hsm=_make_mock_hsm(),
            )
