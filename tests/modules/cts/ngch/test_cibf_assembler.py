"""
Tests for CIBF Assembler — Cheque Image Bundle Format per CTS Spec Rev 3.0.

CIBF is a binary format concatenating three image components:
  1. Front B/W TIFF G4 200dpi (FRONTBW)
  2. Back  B/W TIFF G4 200dpi (BACKBW)
  3. Front Gray JPEG JFIF 100dpi (FRONTGRAY)

ImageDS (256-byte RSA-SHA256 signature) is embedded at a spec-defined byte
offset within the front B/W TIFF component.

Per CTS Spec Rev 3.0:
  - CIBF is binary (not XML, not base64)
  - Segment sizes are included in the CXF <ImageViewData> element so NGCH
    can correctly slice the concatenated bytes
  - ImageDS offset within front B/W is 512 bytes from start of that segment
    (spec §CIBF: signature embedded at byte 512 of FRONTBW header area)

RED phase: all tests must fail before cibf_assembler.py is created.
"""
import pytest


def _make_tiff_stub(size: int = 1024) -> bytes:
    """Minimal TIFF G4 stub: correct 4-byte magic, rest zeros."""
    # TIFF little-endian magic: 'II' + 42 + offset
    return b"II\x2a\x00" + b"\x00" * (size - 4)


def _make_jpeg_stub(size: int = 2048) -> bytes:
    """Minimal JPEG stub: JFIF magic header, rest zeros."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * (size - 4)


def _make_image_ds() -> bytes:
    """256-byte fake ImageDS (RSA-SHA256 signature raw bytes)."""
    return b"\xAB" * 256


class TestCIBFAssemblerBasic:
    """Basic CIBF output contract."""

    def test_assemble_cibf_bytes_is_bytes(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        assembler = CIBFAssembler()
        inp = CIBFInput(
            front_bw=_make_tiff_stub(),
            back_bw=_make_tiff_stub(512),
            front_gray=_make_jpeg_stub(),
            image_ds=_make_image_ds(),
        )
        result = assembler.assemble(inp)
        assert isinstance(result.cibf_bytes, bytes)

    def test_assemble_returns_cibf_result(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        assembler = CIBFAssembler()
        inp = CIBFInput(
            front_bw=_make_tiff_stub(),
            back_bw=_make_tiff_stub(512),
            front_gray=_make_jpeg_stub(),
            image_ds=_make_image_ds(),
        )
        result = assembler.assemble(inp)
        # CIBFResult has both cibf_bytes and segment sizes
        assert hasattr(result, "cibf_bytes")
        assert hasattr(result, "front_bw_size")
        assert hasattr(result, "back_bw_size")
        assert hasattr(result, "front_gray_size")

    def test_cibf_bytes_is_concatenation_of_three_segments(self):
        """CIBF is binary concatenation of 3 image segments."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        front_bw = _make_tiff_stub(1024)
        back_bw = _make_tiff_stub(512)
        front_gray = _make_jpeg_stub(2048)

        assembler = CIBFAssembler()
        inp = CIBFInput(
            front_bw=front_bw,
            back_bw=back_bw,
            front_gray=front_gray,
            image_ds=_make_image_ds(),
        )
        result = assembler.assemble(inp)
        # Total size = front_bw (with ImageDS embedded) + back_bw + front_gray
        # front_bw size doesn't change — ImageDS replaces bytes, doesn't expand
        assert len(result.cibf_bytes) == len(front_bw) + len(back_bw) + len(front_gray)


class TestImageDSEmbedding:
    """ImageDS must be embedded at byte 512 of the front B/W segment."""

    _IMAGEDS_OFFSET = 512

    def test_imageds_embedded_at_correct_offset(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        image_ds = b"\xDE\xAD\xBE\xEF" + b"\x00" * 252  # 256 bytes with distinctive start
        front_bw = _make_tiff_stub(2048)

        assembler = CIBFAssembler()
        inp = CIBFInput(
            front_bw=front_bw,
            back_bw=_make_tiff_stub(512),
            front_gray=_make_jpeg_stub(),
            image_ds=image_ds,
        )
        result = assembler.assemble(inp)

        # ImageDS starts at byte 512 of the CIBF (offset within front_bw segment)
        offset = self._IMAGEDS_OFFSET
        extracted = result.cibf_bytes[offset: offset + 256]
        assert extracted == image_ds

    def test_imageds_replaces_bytes_not_expands(self):
        """Embedding ImageDS must not change the total CIBF size."""
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        front_bw = _make_tiff_stub(2048)
        back_bw = _make_tiff_stub(512)
        front_gray = _make_jpeg_stub(1024)
        expected_size = len(front_bw) + len(back_bw) + len(front_gray)

        assembler = CIBFAssembler()
        result = assembler.assemble(CIBFInput(
            front_bw=front_bw,
            back_bw=back_bw,
            front_gray=front_gray,
            image_ds=_make_image_ds(),
        ))
        assert len(result.cibf_bytes) == expected_size

    def test_imageds_must_be_256_bytes(self):
        """CIBFInput must reject ImageDS that is not exactly 256 bytes."""
        from modules.cts.ngch.cibf_assembler import CIBFInput, CIBFValidationError

        with pytest.raises((CIBFValidationError, ValueError)):
            CIBFInput(
                front_bw=_make_tiff_stub(),
                back_bw=_make_tiff_stub(512),
                front_gray=_make_jpeg_stub(),
                image_ds=b"\x00" * 100,  # wrong length
            )

    def test_front_bw_must_be_longer_than_imageds_offset(self):
        """front_bw must be at least 512 + 256 = 768 bytes to accommodate ImageDS."""
        from modules.cts.ngch.cibf_assembler import CIBFInput, CIBFValidationError

        with pytest.raises((CIBFValidationError, ValueError)):
            CIBFInput(
                front_bw=b"\x00" * 100,  # too short
                back_bw=_make_tiff_stub(512),
                front_gray=_make_jpeg_stub(),
                image_ds=_make_image_ds(),
            )


class TestSegmentSizes:
    """Segment sizes must be accurately reported for CXF embedding."""

    def test_front_bw_size_matches_input(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        front_bw = _make_tiff_stub(1000)
        assembler = CIBFAssembler()
        result = assembler.assemble(CIBFInput(
            front_bw=front_bw,
            back_bw=_make_tiff_stub(512),
            front_gray=_make_jpeg_stub(),
            image_ds=_make_image_ds(),
        ))
        assert result.front_bw_size == len(front_bw)

    def test_back_bw_size_matches_input(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        back_bw = _make_tiff_stub(600)
        assembler = CIBFAssembler()
        result = assembler.assemble(CIBFInput(
            front_bw=_make_tiff_stub(1024),
            back_bw=back_bw,
            front_gray=_make_jpeg_stub(),
            image_ds=_make_image_ds(),
        ))
        assert result.back_bw_size == len(back_bw)

    def test_front_gray_size_matches_input(self):
        from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput

        front_gray = _make_jpeg_stub(3000)
        assembler = CIBFAssembler()
        result = assembler.assemble(CIBFInput(
            front_bw=_make_tiff_stub(1024),
            back_bw=_make_tiff_stub(512),
            front_gray=front_gray,
            image_ds=_make_image_ds(),
        ))
        assert result.front_gray_size == len(front_gray)
