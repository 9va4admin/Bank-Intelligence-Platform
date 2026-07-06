"""
CIBF Assembler — Cheque Image Bundle Format per CTS Spec Rev 3.0.

CIBF is a binary concatenation of three image segments:
  1. Front B/W TIFF G4 200dpi  (FRONTBW)
  2. Back  B/W TIFF G4 200dpi  (BACKBW)
  3. Front Gray JPEG JFIF 100dpi (FRONTGRAY)

ImageDS (256-byte RSA-SHA256 signature of the front B/W image) is embedded at
byte offset 512 within the FRONTBW segment, replacing those bytes in-place.
The total CIBF size does not change — ImageDS replaces, not appends.

The CIBFResult includes per-segment sizes so the CXF builder can correctly
populate the <ImageViewData> element for NGCH to slice the concatenated binary.

Validation:
  - ImageDS must be exactly 256 bytes
  - front_bw must be at least IMAGEDS_OFFSET + 256 (768) bytes
"""
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

_IMAGEDS_OFFSET = 512    # byte offset within front_bw where ImageDS is embedded
_IMAGEDS_LENGTH = 256    # RSA-SHA256 with 2048-bit key → 256 bytes
_MIN_FRONT_BW_SIZE = _IMAGEDS_OFFSET + _IMAGEDS_LENGTH  # 768 bytes minimum


class CIBFValidationError(ValueError):
    """Raised when CIBF assembly inputs fail validation."""


@dataclass
class CIBFInput:
    """Input to the CIBF assembler."""

    front_bw:   bytes   # Front B/W TIFF G4 200dpi
    back_bw:    bytes   # Back B/W TIFF G4 200dpi
    front_gray: bytes   # Front gray JPEG JFIF 100dpi
    image_ds:   bytes   # 256-byte RSA-SHA256 ImageDS signature

    def __post_init__(self) -> None:
        if len(self.image_ds) != _IMAGEDS_LENGTH:
            raise CIBFValidationError(
                f"ImageDS must be exactly {_IMAGEDS_LENGTH} bytes, "
                f"got {len(self.image_ds)}"
            )
        if len(self.front_bw) < _MIN_FRONT_BW_SIZE:
            raise CIBFValidationError(
                f"front_bw must be at least {_MIN_FRONT_BW_SIZE} bytes to "
                f"accommodate ImageDS at offset {_IMAGEDS_OFFSET}, "
                f"got {len(self.front_bw)} bytes"
            )


@dataclass
class CIBFResult:
    """Result of CIBF assembly."""

    cibf_bytes:     bytes   # Complete concatenated CIBF binary
    front_bw_size:  int     # Byte length of FRONTBW segment
    back_bw_size:   int     # Byte length of BACKBW segment
    front_gray_size: int    # Byte length of FRONTGRAY segment


class CIBFAssembler:
    """Assembles CIBF binary from image components with embedded ImageDS."""

    def assemble(self, inp: CIBFInput) -> CIBFResult:
        """Embed ImageDS into front_bw and concatenate all three segments.

        ImageDS is written in-place at byte offset 512 within FRONTBW.
        Returns CIBFResult with complete binary and segment sizes.
        """
        # Embed ImageDS at offset 512 — replace bytes, do not expand
        front_bw_with_ds = bytearray(inp.front_bw)
        front_bw_with_ds[_IMAGEDS_OFFSET: _IMAGEDS_OFFSET + _IMAGEDS_LENGTH] = inp.image_ds
        front_bw_bytes = bytes(front_bw_with_ds)

        # Concatenate: FRONTBW + BACKBW + FRONTGRAY
        cibf = front_bw_bytes + inp.back_bw + inp.front_gray

        log.debug(
            "cibf_assembler.assembled",
            front_bw_size=len(front_bw_bytes),
            back_bw_size=len(inp.back_bw),
            front_gray_size=len(inp.front_gray),
            total_size=len(cibf),
        )

        return CIBFResult(
            cibf_bytes=cibf,
            front_bw_size=len(front_bw_bytes),
            back_bw_size=len(inp.back_bw),
            front_gray_size=len(inp.front_gray),
        )
