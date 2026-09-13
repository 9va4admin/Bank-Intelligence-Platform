"""
Tests for CIBF Assembler — CHI Spec Rev 3.00 Appendix 4.2.2.

CIBF (Capture Image Binary File) is a lot-level binary file containing all instruments.

Per-instrument binary layout (Appendix 4.2.2 layout diagram):
  [256-byte DS for Front BW]  ← DS PRECEDES the image (NOT embedded within it)
  [Front BW TIFF G4 bytes]
  [256-byte DS for Back BW]
  [Back BW TIFF G4 bytes]
  [256-byte DS for Front Gray]
  [Front Gray JFIF JPEG bytes]

The lot-level CIBF is all instruments concatenated in the same order as CXF items.

CXFImageViewData and CXFImageDS in the CXF XML reference byte offsets within the CIBF:
  - ImageDS.DigitalSignatureDataOffset = byte offset of the 256-byte DS within CIBF
  - ImageViewData.ImageDataOffset      = byte offset of the image data within CIBF
  - ImageViewData.ImageDataLength      = length of the image data in bytes

The assembler must track a running byte offset as it concatenates and return
per-instrument offset info so CXFBuilder can populate these attributes.

RED phase: all tests must fail against the OLD cibf_assembler.py which embeds DS
at offset 512 inside the image (the wrong approach).
"""
import pytest


def _make_tiff_stub(size: int = 1024) -> bytes:
    """Minimal TIFF little-endian stub: correct 4-byte magic, rest zeros."""
    return b"II\x2a\x00" + b"\x00" * (size - 4)


def _make_jpeg_stub(size: int = 2048) -> bytes:
    """Minimal JFIF JPEG stub: correct magic header, rest zeros."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


def _make_image_ds() -> bytes:
    """256-byte fake ImageDS (RSA-SHA256 signature raw bytes)."""
    return b"\xAB" * 256


def _make_instrument_input(
    seq: str = "00000101000001",
    fb_size: int = 1024,
    bb_size: int = 512,
    fg_size: int = 2048,
    ds_byte: int = 0xAB,
) -> dict:
    """Build a CIBFInstrumentInput dict for one instrument."""
    return dict(
        item_seq_no=seq,
        front_bw=_make_tiff_stub(fb_size),
        back_bw=_make_tiff_stub(bb_size),
        front_gray=_make_jpeg_stub(fg_size),
        ds_front_bw=bytes([ds_byte]) * 256,
        ds_back_bw=bytes([ds_byte + 1]) * 256,
        ds_front_gray=bytes([ds_byte + 2]) * 256,
    )


class TestCIBFInstrumentInput:
    """CIBFInstrumentInput validation — 3 DS required, each 256 bytes."""

    def test_accepts_valid_instrument(self):
        from modules.cts.ngch.cibf_assembler import CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        assert inp.item_seq_no == "00000101000001"

    def test_rejects_ds_front_bw_wrong_length(self):
        from modules.cts.ngch.cibf_assembler import CIBFInstrumentInput, CIBFValidationError

        bad = {**_make_instrument_input(), "ds_front_bw": b"\x00" * 100}
        with pytest.raises((CIBFValidationError, ValueError)):
            CIBFInstrumentInput(**bad)

    def test_rejects_ds_back_bw_wrong_length(self):
        from modules.cts.ngch.cibf_assembler import CIBFInstrumentInput, CIBFValidationError

        bad = {**_make_instrument_input(), "ds_back_bw": b"\x00" * 300}
        with pytest.raises((CIBFValidationError, ValueError)):
            CIBFInstrumentInput(**bad)

    def test_rejects_ds_front_gray_wrong_length(self):
        from modules.cts.ngch.cibf_assembler import CIBFInstrumentInput, CIBFValidationError

        bad = {**_make_instrument_input(), "ds_front_gray": b"\x00" * 255}
        with pytest.raises((CIBFValidationError, ValueError)):
            CIBFInstrumentInput(**bad)


class TestCIBFBinaryLayout:
    """DS must PRECEDE each image — not be embedded at offset 512 within it."""

    def test_ds_front_bw_precedes_front_bw_image(self):
        """First 256 bytes of CIBF must be the Front BW DS."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        ds_fb = bytes([0xAA]) * 256
        inp = CIBFInstrumentInput(**{**_make_instrument_input(), "ds_front_bw": ds_fb})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        # First 256 bytes = Front BW DS
        assert result.cibf_bytes[:256] == ds_fb

    def test_front_bw_image_follows_its_ds(self):
        """Bytes 256 onward must be the actual Front BW TIFF data."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        front_bw = _make_tiff_stub(1024)
        inp = CIBFInstrumentInput(**{**_make_instrument_input(), "front_bw": front_bw})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        # Bytes 256..256+1024 = Front BW image
        assert result.cibf_bytes[256: 256 + 1024] == front_bw

    def test_ds_back_bw_precedes_back_bw_image(self):
        """After Front BW image, next 256 bytes = Back BW DS."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size = 1024
        ds_bb = bytes([0xBB]) * 256
        inp = CIBFInstrumentInput(**{**_make_instrument_input(fb_size=fb_size), "ds_back_bw": ds_bb})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        # DS Back BW starts at: 256 (DS_FB) + fb_size
        ds_bb_offset = 256 + fb_size
        assert result.cibf_bytes[ds_bb_offset: ds_bb_offset + 256] == ds_bb

    def test_back_bw_image_follows_its_ds(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size, bb_size = 1024, 512
        back_bw = _make_tiff_stub(bb_size)
        inp = CIBFInstrumentInput(**{**_make_instrument_input(fb_size=fb_size, bb_size=bb_size), "back_bw": back_bw})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        bb_img_offset = 256 + fb_size + 256
        assert result.cibf_bytes[bb_img_offset: bb_img_offset + bb_size] == back_bw

    def test_ds_front_gray_precedes_front_gray_image(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size, bb_size = 1024, 512
        ds_fg = bytes([0xCC]) * 256
        inp = CIBFInstrumentInput(**{**_make_instrument_input(fb_size=fb_size, bb_size=bb_size), "ds_front_gray": ds_fg})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        fg_ds_offset = 256 + fb_size + 256 + bb_size
        assert result.cibf_bytes[fg_ds_offset: fg_ds_offset + 256] == ds_fg

    def test_total_size_per_instrument_is_3ds_plus_3images(self):
        """Per-instrument size = 3×256 + len(FB) + len(BB) + len(FG)."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size, bb_size, fg_size = 1024, 512, 2048
        inp = CIBFInstrumentInput(**_make_instrument_input(fb_size=fb_size, bb_size=bb_size, fg_size=fg_size))
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        expected = 3 * 256 + fb_size + bb_size + fg_size
        assert len(result.cibf_bytes) == expected

    def test_ds_not_embedded_in_image_bytes(self):
        """DS must NOT corrupt the image bytes — image data must be intact."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        front_bw = _make_tiff_stub(1024)  # distinctive content
        inp = CIBFInstrumentInput(**{**_make_instrument_input(), "front_bw": front_bw})
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])

        # Image starts at offset 256 (after its DS) — must match original bytes exactly
        image_start = 256
        assert result.cibf_bytes[image_start: image_start + 1024] == front_bw


class TestCIBFByteOffsets:
    """assemble_lot must return correct byte offsets for CXF reference."""

    def test_result_has_instrument_offsets(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        assert hasattr(result, "instrument_offsets")
        assert len(result.instrument_offsets) == 1

    def test_offset_has_all_required_fields(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        off = result.instrument_offsets[0]
        assert hasattr(off, "item_seq_no")
        assert hasattr(off, "front_bw_ds_offset")
        assert hasattr(off, "front_bw_image_offset")
        assert hasattr(off, "front_bw_image_length")
        assert hasattr(off, "back_bw_ds_offset")
        assert hasattr(off, "back_bw_image_offset")
        assert hasattr(off, "back_bw_image_length")
        assert hasattr(off, "front_gray_ds_offset")
        assert hasattr(off, "front_gray_image_offset")
        assert hasattr(off, "front_gray_image_length")

    def test_front_bw_ds_offset_is_zero_for_first_instrument(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        off = result.instrument_offsets[0]
        assert off.front_bw_ds_offset == 0

    def test_front_bw_image_offset_is_256(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        off = result.instrument_offsets[0]
        assert off.front_bw_image_offset == 256

    def test_front_bw_image_length_matches_input(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size = 1500
        inp = CIBFInstrumentInput(**_make_instrument_input(fb_size=fb_size))
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        assert result.instrument_offsets[0].front_bw_image_length == fb_size

    def test_back_bw_ds_offset_follows_front_bw(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size = 1024
        inp = CIBFInstrumentInput(**_make_instrument_input(fb_size=fb_size))
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        off = result.instrument_offsets[0]
        assert off.back_bw_ds_offset == 256 + fb_size

    def test_back_bw_image_offset_follows_back_bw_ds(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb_size = 1024
        inp = CIBFInstrumentInput(**_make_instrument_input(fb_size=fb_size))
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        off = result.instrument_offsets[0]
        assert off.back_bw_image_offset == 256 + fb_size + 256

    def test_item_seq_no_matches(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input(seq="00000101999001"))
        assembler = CIBFAssembler()
        result = assembler.assemble_lot([inp])
        assert result.instrument_offsets[0].item_seq_no == "00000101999001"


class TestCIBFLotAssembly:
    """Lot-level CIBF: multiple instruments concatenated in order."""

    def test_two_instruments_total_size(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb, bb, fg = 1024, 512, 2048
        instr_size = 3 * 256 + fb + bb + fg

        instruments = [
            CIBFInstrumentInput(**_make_instrument_input("00000101000001", fb, bb, fg)),
            CIBFInstrumentInput(**_make_instrument_input("00000101000002", fb, bb, fg, ds_byte=0xDD)),
        ]
        assembler = CIBFAssembler()
        result = assembler.assemble_lot(instruments)
        assert len(result.cibf_bytes) == 2 * instr_size

    def test_second_instrument_offsets_follow_first(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb, bb, fg = 1024, 512, 2048
        first_instrument_size = 3 * 256 + fb + bb + fg

        instruments = [
            CIBFInstrumentInput(**_make_instrument_input("00000101000001", fb, bb, fg)),
            CIBFInstrumentInput(**_make_instrument_input("00000101000002", fb, bb, fg, ds_byte=0xDD)),
        ]
        assembler = CIBFAssembler()
        result = assembler.assemble_lot(instruments)

        off2 = result.instrument_offsets[1]
        # Second instrument's Front BW DS must start immediately after first instrument's data
        assert off2.front_bw_ds_offset == first_instrument_size

    def test_two_instruments_offset_list_length(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        instruments = [
            CIBFInstrumentInput(**_make_instrument_input("00000101000001")),
            CIBFInstrumentInput(**_make_instrument_input("00000101000002", ds_byte=0xCC)),
        ]
        assembler = CIBFAssembler()
        result = assembler.assemble_lot(instruments)
        assert len(result.instrument_offsets) == 2

    def test_second_instrument_data_is_correct(self):
        """Second instrument's Front BW DS must appear at the correct byte offset."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        fb, bb, fg = 1024, 512, 2048
        first_size = 3 * 256 + fb + bb + fg

        ds2 = bytes([0xEE]) * 256
        instruments = [
            CIBFInstrumentInput(**_make_instrument_input("00000101000001", fb, bb, fg)),
            CIBFInstrumentInput(**{**_make_instrument_input("00000101000002", fb, bb, fg), "ds_front_bw": ds2}),
        ]
        assembler = CIBFAssembler()
        result = assembler.assemble_lot(instruments)

        # Second instrument's DS starts at first_size
        assert result.cibf_bytes[first_size: first_size + 256] == ds2

    def test_empty_instrument_list_raises(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler

        assembler = CIBFAssembler()
        with pytest.raises((ValueError, Exception)):
            assembler.assemble_lot([])


class TestCIBFResult:
    """CIBFLotResult contract."""

    def test_result_has_cibf_bytes(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput

        inp = CIBFInstrumentInput(**_make_instrument_input())
        result = CIBFAssembler().assemble_lot([inp])
        assert hasattr(result, "cibf_bytes")
        assert isinstance(result.cibf_bytes, bytes)

    def test_result_is_cibf_lot_result_type(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInstrumentInput, CIBFLotResult

        inp = CIBFInstrumentInput(**_make_instrument_input())
        result = CIBFAssembler().assemble_lot([inp])
        assert isinstance(result, CIBFLotResult)
