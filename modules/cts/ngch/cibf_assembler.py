"""
CIBFAssembler — Capture Image Binary File builder per CHI Spec Rev 3.00 Appendix 4.2.2.

Per-instrument binary layout (Appendix 4.2.2 layout diagram):
  [256-byte ImageDS for Front BW]   ← DS PRECEDES the image
  [Front BW TIFF G4 image bytes]
  [256-byte ImageDS for Back BW]    ← DS PRECEDES the image
  [Back BW TIFF G4 image bytes]
  [256-byte ImageDS for Front Gray] ← DS PRECEDES the image
  [Front Gray JFIF image bytes]

The lot-level CIBF is all instruments concatenated in order.
Byte offsets tracked here are referenced in CXF <ImageDS> and <ImageViewData> attributes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import structlog

log = structlog.get_logger()

_DS_SIZE = 256  # ImageDS = RSA-SHA256 raw signature, always 256 bytes (2048-bit key)


class CIBFValidationError(ValueError):
    """Raised when input data violates CIBF assembly constraints."""


@dataclass(frozen=True)
class CIBFInstrumentInput:
    """Input for one instrument's images and their pre-computed ImageDS signatures.

    ds_front_bw, ds_back_bw, ds_front_gray must each be exactly 256 bytes (raw RSA-SHA256).
    """
    item_seq_no: str
    front_bw: bytes
    back_bw: bytes
    front_gray: bytes
    ds_front_bw: bytes
    ds_back_bw: bytes
    ds_front_gray: bytes

    def __post_init__(self) -> None:
        for ds_field, ds_bytes in [
            ("ds_front_bw", self.ds_front_bw),
            ("ds_back_bw", self.ds_back_bw),
            ("ds_front_gray", self.ds_front_gray),
        ]:
            if len(ds_bytes) != _DS_SIZE:
                raise CIBFValidationError(
                    f"{ds_field} must be exactly {_DS_SIZE} bytes "
                    f"(RSA-SHA256 raw signature); got {len(ds_bytes)}"
                )


@dataclass(frozen=True)
class CIBFInstrumentOffsets:
    """Byte offsets for one instrument within the lot-level CIBF.

    These values are written into the CXF XML attributes:
      <ImageDS DigitalSignatureDataOffset="...">
      <ImageViewData ImageDataOffset="..." ImageDataLength="...">
    """
    item_seq_no: str
    front_bw_ds_offset: int
    front_bw_image_offset: int
    front_bw_image_length: int
    back_bw_ds_offset: int
    back_bw_image_offset: int
    back_bw_image_length: int
    front_gray_ds_offset: int
    front_gray_image_offset: int
    front_gray_image_length: int


@dataclass(frozen=True)
class CIBFLotResult:
    """Result of lot-level CIBF assembly.

    cibf_bytes:          Complete binary content of the CIBF file.
    instrument_offsets:  Per-instrument byte offsets (same order as CXF items).
    """
    cibf_bytes: bytes
    instrument_offsets: List[CIBFInstrumentOffsets]


class CIBFAssembler:
    """Assembles a lot-level CIBF binary from one or more CIBFInstrumentInput records.

    The layout strictly follows CHI Spec Rev 3.00 Appendix 4.2.2:
      For each instrument: DS→Image DS→Image DS→Image (3 DS, each preceding its image).
    """

    def assemble_lot(self, instruments: List[CIBFInstrumentInput]) -> CIBFLotResult:
        """Assemble all instruments into a single CIBF binary.

        Args:
            instruments: Non-empty list of CIBFInstrumentInput, ordered as in CXF.

        Returns:
            CIBFLotResult with complete binary and per-instrument offset table.

        Raises:
            ValueError: If instruments list is empty.
        """
        if not instruments:
            raise ValueError("instruments list must not be empty — a CIBF must contain at least one instrument")

        chunks: List[bytes] = []
        offsets: List[CIBFInstrumentOffsets] = []
        cursor = 0

        for instr in instruments:
            fb_ds_off = cursor
            cursor += _DS_SIZE
            chunks.append(instr.ds_front_bw)

            fb_img_off = cursor
            fb_img_len = len(instr.front_bw)
            cursor += fb_img_len
            chunks.append(instr.front_bw)

            bb_ds_off = cursor
            cursor += _DS_SIZE
            chunks.append(instr.ds_back_bw)

            bb_img_off = cursor
            bb_img_len = len(instr.back_bw)
            cursor += bb_img_len
            chunks.append(instr.back_bw)

            fg_ds_off = cursor
            cursor += _DS_SIZE
            chunks.append(instr.ds_front_gray)

            fg_img_off = cursor
            fg_img_len = len(instr.front_gray)
            cursor += fg_img_len
            chunks.append(instr.front_gray)

            offsets.append(CIBFInstrumentOffsets(
                item_seq_no=instr.item_seq_no,
                front_bw_ds_offset=fb_ds_off,
                front_bw_image_offset=fb_img_off,
                front_bw_image_length=fb_img_len,
                back_bw_ds_offset=bb_ds_off,
                back_bw_image_offset=bb_img_off,
                back_bw_image_length=bb_img_len,
                front_gray_ds_offset=fg_ds_off,
                front_gray_image_offset=fg_img_off,
                front_gray_image_length=fg_img_len,
            ))

            log.debug(
                "cibf_assembler.instrument_assembled",
                item_seq_no=instr.item_seq_no,
                fb_ds_offset=fb_ds_off,
                fb_img_offset=fb_img_off,
                total_cursor=cursor,
            )

        return CIBFLotResult(cibf_bytes=b"".join(chunks), instrument_offsets=offsets)
