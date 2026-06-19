"""
CTS Scanner SDK — data models.

ScanResult is the normalised output from any scanner OEM adapter.
All OEM differences are absorbed by the adapter; the rest of the CTS pipeline
sees only ScanResult objects regardless of whether the scanner is Panini or Canon.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScannerOEM(str, Enum):
    PANINI  = 'PANINI'
    CANON   = 'CANON'
    GENERIC = 'GENERIC'


@dataclass
class ScanResult:
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

    micr_raw:            str        # raw MICR line string from scanner — never log full value
    bank_id:             str
    operator_id:         str

    @property
    def has_front_image(self) -> bool:
        return len(self.front_image) > 0

    @property
    def has_rear_image(self) -> bool:
        return len(self.rear_image) > 0
