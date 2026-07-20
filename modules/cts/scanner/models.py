"""
CTS Scanner SDK — data models.

ScanResult is the normalised output from any scanner OEM adapter.
All OEM differences are absorbed by the adapter; the rest of the CTS pipeline
sees only ScanResult objects regardless of whether the scanner is a Panini,
Digital Check TS240-UV, Canon CR-120UV, or any other device.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScannerOEM(str, Enum):
    PANINI        = 'PANINI'
    DIGITAL_CHECK = 'DIGITAL_CHECK'   # TellerScan TS240-UV, TS250, CheXpress series
    MAGTEK        = 'MAGTEK'          # MagTek MICR readers
    BURROUGHS     = 'BURROUGHS'       # Burroughs Spectrum / Itec series
    RDM           = 'RDM'             # RDM / Scancorp
    OPEX          = 'OPEX'            # OPEX high-volume transports
    CANON         = 'CANON'           # Canon CR-120UV, CR-190i, imageFormula series
    GENERIC       = 'GENERIC'         # Fallback for TWAIN/ISIS devices


class IntegrationMode(str, Enum):
    """How ASTRA communicates with the physical scanner at a branch."""
    SECURELINK       = 'SECURELINK'        # Digital Check SecureLink 2.0 HTTPS REST API
    DCC_API          = 'DCC_API'           # Digital Check native USB SDK (DCC API v12+)
    RANGER_TRANSPORT = 'RANGER_TRANSPORT'  # Canon Ranger Transport API (TCP, port 4242)
    DROP_FOLDER      = 'DROP_FOLDER'       # OEM software writes to a watched folder
    TWAIN            = 'TWAIN'             # Generic TWAIN/ISIS driver (fallback)


@dataclass
class ScanResult:
    """
    Normalised output from any scanner OEM adapter.

    Mandatory fields (all adapters must populate these):
      scan_id, oem, scanner_model, front_image, rear_image, DPI fields,
      file size fields, colour depth fields, micr_raw, bank_id, operator_id.

    Optional capability fields (populated only when the scanner supports them):
      uv_image            — UV image buffer (TS240-UV, CR-120UV, MVX, etc.)
      micr_hardware_raw   — Hardware MICR E13B read (Canon Ranger; separate from image OCR)
      imprinter_stamped   — Rear endorsement stamped during pass-through
      double_feed_detected — Ultrasonic double-feed signal (Canon, Panini Vision X)
    """
    scan_id:             str
    oem:                 ScannerOEM
    scanner_model:       str

    front_image:         bytes
    rear_image:          bytes
    front_dpi:           int
    rear_dpi:            int
    front_file_size_kb:  float
    rear_file_size_kb:   float
    front_colour_depth:  int
    rear_colour_depth:   int

    micr_raw:            str        # raw MICR line — never log in full (contains account data)
    bank_id:             str
    operator_id:         str

    # Optional scanner capability fields
    uv_image:             Optional[bytes] = None   # UV scan buffer — any UV-capable OEM
    micr_hardware_raw:    Optional[str]   = None   # Hardware MICR (Canon Ranger TransportGetMICR)
    imprinter_stamped:    bool            = False   # Endorsement stamped during document pass
    double_feed_detected: bool            = False   # Ultrasonic double-feed signal

    @property
    def has_front_image(self) -> bool:
        return len(self.front_image) > 0

    @property
    def has_rear_image(self) -> bool:
        return len(self.rear_image) > 0

    @property
    def has_hardware_micr(self) -> bool:
        return bool(self.micr_hardware_raw)

    @property
    def has_uv_image(self) -> bool:
        return self.uv_image is not None and len(self.uv_image) > 0
