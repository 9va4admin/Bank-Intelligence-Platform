"""
CIBFParser — extract per-instrument images from an inward CIBF binary.

Counterpart to CIBFAssembler (outward builder). Uses byte offsets from the
CXF (ParsedCXFItem produced by CXFParser) to slice each image and its
preceding 256-byte ImageDS signature out of the flat binary bundle.

CIBF binary layout per instrument (CHI Spec Rev 3.00 Appendix 4.2.2):
  [256-byte ImageDS for Front BW]
  [Front BW TIFF G4 bytes]
  [256-byte ImageDS for Back BW]
  [Back BW TIFF G4 bytes]
  [256-byte ImageDS for Front Gray]
  [Front Gray JFIF bytes]

All instruments are concatenated. Byte offsets are absolute within the
lot-level CIBF — there are no per-instrument length headers in the binary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import structlog

from modules.cts.ngch.cxf_parser import ParsedCXFItem

log = structlog.get_logger()

_DS_SIZE = 256


class CIBFParseError(ValueError):
    """Raised when slicing fails (offset out of range or CIBF is empty)."""


@dataclass(frozen=True)
class ExtractedInstrumentImages:
    """Per-instrument images and their ImageDS signatures extracted from CIBF."""
    item_seq_no: str
    front_bw: bytes
    back_bw: bytes
    front_gray: bytes
    ds_front_bw: bytes     # 256-byte RSA-SHA256 raw DS
    ds_back_bw: bytes
    ds_front_gray: bytes


class CIBFParser:
    """Slice individual cheque images from a CIBF binary bundle.

    All methods are pure (no I/O). Byte offsets come from ParsedCXFItem which
    was parsed from the accompanying CXF XML by CXFParser.
    """

    def extract_instrument(
        self,
        cibf_bytes: bytes,
        item: ParsedCXFItem,
    ) -> ExtractedInstrumentImages:
        """Extract front BW, back BW, and front gray images for one instrument.

        Args:
            cibf_bytes: Full CIBF binary (all instruments concatenated).
            item:       ParsedCXFItem with byte offsets for this instrument.

        Returns:
            ExtractedInstrumentImages with the three images and their DS blocks.

        Raises:
            CIBFParseError: If CIBF is empty or any offset is out of range.
        """
        if not cibf_bytes:
            raise CIBFParseError("CIBF binary is empty")

        def _slice(ds_offset: int, img_offset: int, img_length: int, label: str):
            end = img_offset + img_length
            if ds_offset < 0 or img_offset < 0 or end > len(cibf_bytes):
                raise CIBFParseError(
                    f"Item {item.item_seq_no} {label}: offset out of range "
                    f"(ds_offset={ds_offset}, img_offset={img_offset}, "
                    f"img_length={img_length}, cibf_size={len(cibf_bytes)})"
                )
            ds_end = ds_offset + _DS_SIZE
            if ds_end > len(cibf_bytes):
                raise CIBFParseError(
                    f"Item {item.item_seq_no} {label}: DS end {ds_end} "
                    f"exceeds CIBF size {len(cibf_bytes)}"
                )
            return (
                cibf_bytes[ds_offset:ds_end],
                cibf_bytes[img_offset:end],
            )

        ds_fbw,  img_fbw  = _slice(
            item.front_bw_ds_offset,  item.front_bw_image_offset,  item.front_bw_image_length,  "Front BW")
        ds_bbw,  img_bbw  = _slice(
            item.back_bw_ds_offset,   item.back_bw_image_offset,   item.back_bw_image_length,   "Back BW")
        ds_fgry, img_fgry = _slice(
            item.front_gray_ds_offset, item.front_gray_image_offset, item.front_gray_image_length, "Front Gray")

        log.debug(
            "cibf_parser.extracted",
            item_seq_no=item.item_seq_no,
            fbw_len=len(img_fbw),
            bbw_len=len(img_bbw),
            fgry_len=len(img_fgry),
        )
        return ExtractedInstrumentImages(
            item_seq_no=item.item_seq_no,
            front_bw=img_fbw,
            back_bw=img_bbw,
            front_gray=img_fgry,
            ds_front_bw=ds_fbw,
            ds_back_bw=ds_bbw,
            ds_front_gray=ds_fgry,
        )

    def extract_all(
        self,
        cibf_bytes: bytes,
        items: List[ParsedCXFItem],
    ) -> List[ExtractedInstrumentImages]:
        """Extract images for every instrument in the list.

        Returns an empty list if items is empty. Raises CIBFParseError on
        the first instrument that fails to parse.
        """
        results = []
        for item in items:
            results.append(self.extract_instrument(cibf_bytes, item))
        log.info(
            "cibf_parser.extract_all_complete",
            instrument_count=len(results),
        )
        return results
