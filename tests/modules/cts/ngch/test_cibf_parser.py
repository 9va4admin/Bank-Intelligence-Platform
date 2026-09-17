"""
CIBFParser tests — extract per-instrument images from an inward CIBF binary.

CIBF binary layout per instrument (CHI Spec Rev 3.00 Appendix 4.2.2):
  [256-byte ImageDS for Front BW]
  [Front BW TIFF G4 bytes]
  [256-byte ImageDS for Back BW]
  [Back BW TIFF G4 bytes]
  [256-byte ImageDS for Front Gray]
  [Front Gray JFIF bytes]

All instruments are concatenated in order. CIBFParser uses the byte offsets
from the CXF (ParsedCXFItem) to slice each image and its preceding DS out of
the flat binary.

RED phase: all tests must fail before cibf_parser.py is created.
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass

_DS_SIZE = 256

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_ds(tag: bytes = b"DS") -> bytes:
    """256-byte block uniquely tagged for testing."""
    return tag.ljust(_DS_SIZE, b"\x00")[:_DS_SIZE]


def _fake_image(tag: bytes, size: int) -> bytes:
    return (tag * (size // len(tag) + 1))[:size]


def _make_instrument_bytes(
    fbw_size=50000, bbw_size=45000, fgry_size=120000
) -> tuple[bytes, dict]:
    """Build one instrument's binary blob and return it with the offsets dict."""
    ds_fbw  = _fake_ds(b"DSFBW")
    img_fbw = _fake_image(b"\x49\x49\x2A\x00", fbw_size)  # fake TIFF
    ds_bbw  = _fake_ds(b"DSBBW")
    img_bbw = _fake_image(b"\x49\x49\x2A\x01", bbw_size)
    ds_fgry = _fake_ds(b"DSGRY")
    img_fgry = _fake_image(b"\xFF\xD8\xFF", fgry_size)    # fake JFIF

    blob = ds_fbw + img_fbw + ds_bbw + img_bbw + ds_fgry + img_fgry

    offsets = dict(
        front_bw_ds_offset=0,
        front_bw_image_offset=_DS_SIZE,
        front_bw_image_length=fbw_size,
        back_bw_ds_offset=_DS_SIZE + fbw_size,
        back_bw_image_offset=_DS_SIZE + fbw_size + _DS_SIZE,
        back_bw_image_length=bbw_size,
        front_gray_ds_offset=_DS_SIZE + fbw_size + _DS_SIZE + bbw_size,
        front_gray_image_offset=_DS_SIZE + fbw_size + _DS_SIZE + bbw_size + _DS_SIZE,
        front_gray_image_length=fgry_size,
    )
    return blob, offsets


def _make_parsed_item(item_seq_no="00055005000001", base_offset=0,
                      fbw_size=50000, bbw_size=45000, fgry_size=120000,
                      **extra_offsets):
    """Create a ParsedCXFItem-like object with byte offsets."""
    from modules.cts.ngch.cxf_parser import ParsedCXFItem

    _, offsets = _make_instrument_bytes(fbw_size=fbw_size, bbw_size=bbw_size, fgry_size=fgry_size)
    # Shift only *_offset keys by base_offset; leave *_length keys unchanged
    shifted = {k: (v + base_offset if k.endswith("_offset") else v)
               for k, v in offsets.items()}
    shifted.update(extra_offsets)

    return ParsedCXFItem(
        item_seq_no=item_seq_no,
        payor_bank_rout_no="012345678",
        serial_no="000001",
        trans_code="51",
        micr_line="",
        drawee_ifsc="SBIN0000001",
        amount_paise=10000000,
        doc_type="01",
        micrds_fingerprint="MICRLine",
        micrds_signature="A" * 344,
        iqa_user_field_front_bw="BFB:" + "A" * 17,
        iqa_user_field_back_bw="BBB:" + "A" * 17,
        iqa_user_field_front_gray="BFG:" + "A" * 17,
        **shifted,
    )


# ── Test classes ─────────────────────────────────────────────────────────────

class TestCIBFParserSingleInstrument:
    def test_front_bw_bytes_extracted(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.front_bw) == 50000

    def test_back_bw_bytes_extracted(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.back_bw) == 45000

    def test_front_gray_bytes_extracted(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.front_gray) == 120000

    def test_ds_front_bw_is_256_bytes(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.ds_front_bw) == 256

    def test_ds_back_bw_is_256_bytes(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.ds_back_bw) == 256

    def test_ds_front_gray_is_256_bytes(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        assert len(result.ds_front_gray) == 256

    def test_front_bw_content_correct(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        # Should contain the fake TIFF bytes (pattern \x49\x49\x2A\x00)
        assert result.front_bw[:4] == b"\x49\x49\x2A\x00"

    def test_ds_front_bw_content_correct(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item()
        result = CIBFParser().extract_instrument(blob, item)
        # DS is tagged with b"DSFBW" padded to 256 bytes
        assert result.ds_front_bw[:5] == b"DSFBW"

    def test_item_seq_no_in_result(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        blob, _ = _make_instrument_bytes()
        item = _make_parsed_item(item_seq_no="00055005000007")
        result = CIBFParser().extract_instrument(blob, item)
        assert result.item_seq_no == "00055005000007"


class TestCIBFParserTwoInstruments:
    """Verify that second instrument at a non-zero base offset is sliced correctly."""

    def test_second_instrument_extracted_correctly(self):
        from modules.cts.ngch.cibf_parser import CIBFParser

        blob1, _ = _make_instrument_bytes(fbw_size=10000, bbw_size=9000, fgry_size=20000)
        blob2, _ = _make_instrument_bytes(fbw_size=12000, bbw_size=11000, fgry_size=22000)
        cibf = blob1 + blob2

        item2 = _make_parsed_item(
            item_seq_no="00055005000002",
            base_offset=len(blob1),
            fbw_size=12000, bbw_size=11000, fgry_size=22000,
        )
        result = CIBFParser().extract_instrument(cibf, item2)
        assert len(result.front_bw) == 12000
        assert len(result.back_bw) == 11000
        assert len(result.front_gray) == 22000

    def test_second_instrument_ds_correct(self):
        from modules.cts.ngch.cibf_parser import CIBFParser

        blob1, _ = _make_instrument_bytes(fbw_size=10000, bbw_size=9000, fgry_size=20000)
        blob2, _ = _make_instrument_bytes(fbw_size=12000, bbw_size=11000, fgry_size=22000)
        cibf = blob1 + blob2

        item2 = _make_parsed_item(
            item_seq_no="00055005000002",
            base_offset=len(blob1),
            fbw_size=12000, bbw_size=11000, fgry_size=22000,
        )
        result = CIBFParser().extract_instrument(cibf, item2)
        assert result.ds_front_bw[:5] == b"DSFBW"
        assert result.ds_back_bw[:5] == b"DSBBW"
        assert result.ds_front_gray[:5] == b"DSGRY"


class TestCIBFParserExtractAll:
    """Test extract_all convenience method: parse all items from a CIBF."""

    def test_extract_all_returns_all_items(self):
        from modules.cts.ngch.cibf_parser import CIBFParser

        blob1, _ = _make_instrument_bytes(fbw_size=5000, bbw_size=4000, fgry_size=8000)
        blob2, _ = _make_instrument_bytes(fbw_size=6000, bbw_size=5000, fgry_size=9000)
        cibf = blob1 + blob2

        item1 = _make_parsed_item(item_seq_no="00055005000001", base_offset=0,
                                   fbw_size=5000, bbw_size=4000, fgry_size=8000)
        item2 = _make_parsed_item(item_seq_no="00055005000002", base_offset=len(blob1),
                                   fbw_size=6000, bbw_size=5000, fgry_size=9000)

        results = CIBFParser().extract_all(cibf, [item1, item2])
        assert len(results) == 2

    def test_extract_all_item_seq_nos(self):
        from modules.cts.ngch.cibf_parser import CIBFParser

        blob1, _ = _make_instrument_bytes(fbw_size=5000, bbw_size=4000, fgry_size=8000)
        blob2, _ = _make_instrument_bytes(fbw_size=6000, bbw_size=5000, fgry_size=9000)
        cibf = blob1 + blob2

        item1 = _make_parsed_item(item_seq_no="00055005000001", base_offset=0,
                                   fbw_size=5000, bbw_size=4000, fgry_size=8000)
        item2 = _make_parsed_item(item_seq_no="00055005000002", base_offset=len(blob1),
                                   fbw_size=6000, bbw_size=5000, fgry_size=9000)

        results = CIBFParser().extract_all(cibf, [item1, item2])
        seq_nos = {r.item_seq_no for r in results}
        assert seq_nos == {"00055005000001", "00055005000002"}

    def test_extract_all_empty_list_returns_empty(self):
        from modules.cts.ngch.cibf_parser import CIBFParser
        results = CIBFParser().extract_all(b"\x00" * 1000, [])
        assert results == []


class TestCIBFParserErrors:
    def test_offset_beyond_cibf_raises(self):
        from modules.cts.ngch.cibf_parser import CIBFParser, CIBFParseError
        blob, _ = _make_instrument_bytes()
        # Give a bad offset that is beyond the CIBF length
        item = _make_parsed_item(front_bw_image_offset=999999999, front_bw_image_length=1000)
        with pytest.raises(CIBFParseError):
            CIBFParser().extract_instrument(blob, item)

    def test_empty_cibf_raises(self):
        from modules.cts.ngch.cibf_parser import CIBFParser, CIBFParseError
        item = _make_parsed_item()
        with pytest.raises(CIBFParseError):
            CIBFParser().extract_instrument(b"", item)
