"""
Tests for build_ngch_file Temporal activity — Gap 2 wiring.

P1 GAP: modules/cts/ngch/ contains IQAEngine, NGCHSigner, CIBFAssembler, CXFBuilder
as standalone tested modules, but there is no Temporal activity that orchestrates
them into a spec-compliant outward submission bundle.

This test file covers the build_ngch_file activity which must:
  1. Run IQAEngine on instrument images → UserField codes
  2. Run NGCHSigner.sign_micr(micr_line) → MICRDS (344-char Base64)
  3. Run NGCHSigner.sign_image(front_bw_bytes) → ImageDS (256-byte raw)
  4. Run CIBFAssembler.assemble(CIBFInput) → CIBFResult (binary bundle)
  5. Build CXFItem from all the above
  6. Run CXFBuilder.build([CXFItem], session_id=...) → CXF XML bytes
  7. Return BuildNGCHFileResult with cxf_bytes + cibf_bytes_per_instrument

The activity is synchronous (no async HTTP) — it wires local in-memory components.
OTel span and structlog are mandatory per project rules.

RED phase: all tests fail before build_ngch_file.py is created.
"""
import pytest
from unittest.mock import MagicMock, patch
from typing import List


# ── Helpers ─────────────────────────────────────────────────────────────────

_FAKE_RSA_SIG_256 = b"\xAB" * 256   # 256-byte fake RSA signature
_FAKE_MICRDS = "A" * 344             # 344-char fake Base64 MICRDS
_FAKE_FRONT_BW = b"\x00\x01" * 500  # ≥ 768 bytes (IMAGEDS_OFFSET+IMAGEDS_LENGTH)
_FAKE_BACK_BW  = b"\x00\x02" * 200
_FAKE_FRONT_GRAY = b"\xFF\xD8\xFF" + b"\x00" * 200  # fake JPEG header

# IQA user field prefixes for the 3 views per CHI Spec Rev 3.0
_IQA_UF_FRONT_BW   = "BFB:0000000000000000"
_IQA_UF_BACK_BW    = "BBB:0000000000000000"
_IQA_UF_FRONT_GRAY = "BFG:0000000000000000"


def _make_instrument(
    item_seq_no: str = "00001",
    micr_line: str = "400160001234",
    drawee_ifsc: str = "SBIN0000123",
    drawee_account: str = "SB12345678901",
    amount_paise: int = 5_000_000,
    front_bw: bytes = _FAKE_FRONT_BW,
    back_bw: bytes = _FAKE_BACK_BW,
    front_gray: bytes = _FAKE_FRONT_GRAY,
    width_px: int = 1200,
    height_px: int = 500,
    dpi: int = 200,
    bit_depth: int = 1,
    presenting_bank_rout_no: str = "000550050",
    cycle_no: str = "01",
    presentment_date: str = "19062026",
    batch_id: str = "BATCH-001",
) -> dict:
    return {
        "item_seq_no": item_seq_no,
        "micr_line": micr_line,
        "drawee_ifsc": drawee_ifsc,
        "drawee_account": drawee_account,
        "amount_paise": amount_paise,
        "front_bw_bytes": front_bw,
        "back_bw_bytes": back_bw,
        "front_gray_bytes": front_gray,
        "width_px": width_px,
        "height_px": height_px,
        "dpi": dpi,
        "bit_depth": bit_depth,
        "presenting_bank_rout_no": presenting_bank_rout_no,
        "cycle_no": cycle_no,
        "presentment_date": presentment_date,
        "batch_id": batch_id,
    }


def _make_mock_hsm():
    """Mock HSM that returns deterministic fake signatures."""
    hsm = MagicMock()
    hsm.sign.return_value = _FAKE_RSA_SIG_256
    return hsm


class TestBuildNGCHFileActivityExists:
    """The activity module and function must exist."""

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


class TestBuildNGCHFileInputModel:
    """BuildNGCHFileInput validates its fields."""

    def test_input_requires_session_id(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        import pydantic
        with pytest.raises((pydantic.ValidationError, TypeError)):
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                instruments=[],
                # missing: session_id
            )

    def test_input_requires_bank_id(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        import pydantic
        with pytest.raises((pydantic.ValidationError, TypeError)):
            BuildNGCHFileInput(
                lot_number="LOT-001",
                session_id="SES-001",
                instruments=[],
                # missing: bank_id
            )

    def test_input_accepts_instrument_list(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileInput
        inp = BuildNGCHFileInput(
            bank_id="test-bank",
            lot_number="LOT-001",
            session_id="SES-0619-001",
            instruments=[_make_instrument()],
        )
        assert len(inp.instruments) == 1


class TestBuildNGCHFileResultModel:
    """BuildNGCHFileResult must carry CXF bytes and per-instrument CIBF bytes."""

    def test_result_has_cxf_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileResult
        result = BuildNGCHFileResult(
            lot_number="LOT-001",
            bank_id="test-bank",
            cxf_bytes=b"<xml/>",
            cibf_bytes_per_instrument={"00001": b"\x00" * 100},
            instrument_count=1,
        )
        assert result.cxf_bytes == b"<xml/>"

    def test_result_has_cibf_bytes_per_instrument(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileResult
        cibf = {"00001": b"\xAB" * 200, "00002": b"\xCD" * 200}
        result = BuildNGCHFileResult(
            lot_number="LOT-001",
            bank_id="test-bank",
            cxf_bytes=b"<xml/>",
            cibf_bytes_per_instrument=cibf,
            instrument_count=2,
        )
        assert result.cibf_bytes_per_instrument["00001"] == b"\xAB" * 200

    def test_result_has_instrument_count(self):
        from modules.cts.workflows.activities.build_ngch_file import BuildNGCHFileResult
        result = BuildNGCHFileResult(
            lot_number="LOT-001",
            bank_id="test-bank",
            cxf_bytes=b"<xml/>",
            cibf_bytes_per_instrument={},
            instrument_count=0,
        )
        assert result.instrument_count == 0


class TestBuildNGCHFileCallsSignerAndIQA:
    """Activity must call IQAEngine, NGCHSigner, CIBFAssembler, CXFBuilder."""

    def test_activity_calls_sign_micr(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        hsm = _make_mock_hsm()
        inp = BuildNGCHFileInput(
            bank_id="test-bank",
            lot_number="LOT-001",
            session_id="SES-0619-001",
            instruments=[_make_instrument()],
        )
        result = build_ngch_file(inp, hsm=hsm)
        # HSM must have been called at least once (for MICRDS)
        assert hsm.sign.call_count >= 1

    def test_activity_calls_sign_image(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        hsm = _make_mock_hsm()
        inp = BuildNGCHFileInput(
            bank_id="test-bank",
            lot_number="LOT-001",
            session_id="SES-0619-001",
            instruments=[_make_instrument()],
        )
        result = build_ngch_file(inp, hsm=hsm)
        # HSM must be called for both MICRDS and ImageDS per instrument
        # one instrument → 2 HSM calls (sign_micr + sign_image)
        assert hsm.sign.call_count == 2

    def test_activity_with_two_instruments_calls_hsm_four_times(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        hsm = _make_mock_hsm()
        inp = BuildNGCHFileInput(
            bank_id="test-bank",
            lot_number="LOT-001",
            session_id="SES-0619-001",
            instruments=[
                _make_instrument(item_seq_no="00001"),
                _make_instrument(item_seq_no="00002"),
            ],
        )
        result = build_ngch_file(inp, hsm=hsm)
        assert hsm.sign.call_count == 4  # 2 instruments × 2 signatures each


class TestBuildNGCHFileCXFOutput:
    """CXF bytes must be valid XML with the CXF namespace."""

    def test_cxf_bytes_is_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        assert isinstance(result.cxf_bytes, bytes)

    def test_cxf_bytes_is_valid_xml(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        import xml.etree.ElementTree as ET
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        root = ET.fromstring(result.cxf_bytes)
        assert root is not None

    def test_cxf_bytes_has_cxf_namespace(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        import xml.etree.ElementTree as ET
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        _CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"
        root = ET.fromstring(result.cxf_bytes)
        assert _CXF_NS in root.tag or _CXF_NS in result.cxf_bytes.decode("utf-8")

    def test_cxf_bytes_session_id_matches_input(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-UNIQUE",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        assert b"SES-0619-UNIQUE" in result.cxf_bytes


class TestBuildNGCHFileCIBFOutput:
    """Each instrument produces a CIBF binary blob keyed by item_seq_no."""

    def test_cibf_dict_keyed_by_item_seq_no(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument(item_seq_no="00007")],
            ),
            hsm=_make_mock_hsm(),
        )
        assert "00007" in result.cibf_bytes_per_instrument

    def test_cibf_value_is_bytes(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        cibf = result.cibf_bytes_per_instrument["00001"]
        assert isinstance(cibf, bytes)
        assert len(cibf) > 0

    def test_cibf_size_equals_sum_of_three_image_segments(self):
        """CIBF is a concatenation of front_bw + back_bw + front_gray."""
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        front_bw = _FAKE_FRONT_BW      # 1000 bytes
        back_bw = b"\x00" * 800        # 800 bytes
        front_gray = b"\xFF" * 600     # 600 bytes
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument(
                    front_bw=front_bw,
                    back_bw=back_bw,
                    front_gray=front_gray,
                )],
            ),
            hsm=_make_mock_hsm(),
        )
        expected_size = len(front_bw) + len(back_bw) + len(front_gray)
        actual_size = len(result.cibf_bytes_per_instrument["00001"])
        assert actual_size == expected_size

    def test_two_instruments_produce_two_cibf_entries(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[
                    _make_instrument(item_seq_no="00001"),
                    _make_instrument(item_seq_no="00002"),
                ],
            ),
            hsm=_make_mock_hsm(),
        )
        assert len(result.cibf_bytes_per_instrument) == 2
        assert "00001" in result.cibf_bytes_per_instrument
        assert "00002" in result.cibf_bytes_per_instrument

    def test_instrument_count_matches_input(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[
                    _make_instrument(item_seq_no="00001"),
                    _make_instrument(item_seq_no="00002"),
                    _make_instrument(item_seq_no="00003"),
                ],
            ),
            hsm=_make_mock_hsm(),
        )
        assert result.instrument_count == 3


class TestBuildNGCHFileEmptyInstrumentsRaises:
    """Empty instrument list must be rejected — CXF spec requires at least one item."""

    def test_empty_instruments_raises(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        with pytest.raises((ValueError, Exception)):
            build_ngch_file(
                BuildNGCHFileInput(
                    bank_id="test-bank",
                    lot_number="LOT-001",
                    session_id="SES-0619-001",
                    instruments=[],
                ),
                hsm=_make_mock_hsm(),
            )


class TestBuildNGCHFileIQACodesInCXF:
    """IQA UserField codes must appear in the CXF output."""

    def test_iqa_user_field_present_in_cxf_xml(self):
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file, BuildNGCHFileInput,
        )
        result = build_ngch_file(
            BuildNGCHFileInput(
                bank_id="test-bank",
                lot_number="LOT-001",
                session_id="SES-0619-001",
                instruments=[_make_instrument()],
            ),
            hsm=_make_mock_hsm(),
        )
        # All 3 IQA UserField prefixes must appear per CHI Spec Rev 3.0
        assert b"BFB:" in result.cxf_bytes
        assert b"BBB:" in result.cxf_bytes
        assert b"BFG:" in result.cxf_bytes
