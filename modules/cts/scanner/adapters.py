"""
CTS Scanner OEM Adapters.

Each adapter wraps OEM-specific SDK behaviour and normalises output to ScanResult.
PaniniAdapter: Panini I:Deal, MyMicr, Vision series.
CanonAdapter:  Canon CR-190i, CR-120, imageFormula series.

In production, these adapters call OEM SDK C-extensions or REST APIs
exposed by the scanner firmware. In this implementation the ingest() method
accepts pre-captured bytes (from SDK callback or file) for testability.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from modules.cts.scanner.models import ScanResult, ScannerOEM


class ScannerAdapter(ABC):
    """Abstract base for all OEM scanner adapters."""

    def __init__(self, scanner_model: str, bank_id: str, operator_id: str) -> None:
        self.scanner_model = scanner_model
        self.bank_id       = bank_id
        self.operator_id   = operator_id

    @property
    @abstractmethod
    def oem(self) -> ScannerOEM: ...

    def ingest(
        self,
        *,
        front_image: bytes,
        rear_image:  bytes,
        front_dpi:   int,
        rear_dpi:    int,
        micr_raw:    str,
    ) -> ScanResult:
        scan_id = self._generate_scan_id()
        return ScanResult(
            scan_id=scan_id,
            oem=self.oem,
            scanner_model=self.scanner_model,
            front_image=front_image,
            rear_image=rear_image,
            front_dpi=front_dpi,
            rear_dpi=rear_dpi,
            front_file_size_kb=len(front_image) / 1024,
            rear_file_size_kb=len(rear_image)  / 1024,
            front_colour_depth=24,
            rear_colour_depth=24,
            micr_raw=micr_raw,
            bank_id=self.bank_id,
            operator_id=self.operator_id,
        )

    def _generate_scan_id(self) -> str:
        date_str = datetime.now(tz=timezone.utc).strftime('%Y%m%d')
        short    = str(uuid.uuid4()).split('-')[0].upper()
        return f'SCAN-{date_str}-{short}'


class PaniniAdapter(ScannerAdapter):
    """Adapter for Panini scanner family (I:Deal, MyMicr, Vision series)."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.PANINI


class CanonAdapter(ScannerAdapter):
    """Adapter for Canon imageFormula / CR series scanners (CR-120, CR-190i, etc.)."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.CANON

    def ingest_cr120(
        self,
        *,
        front_image: bytes,
        rear_image: bytes,
        front_dpi: int,
        rear_dpi: int,
        micr_hardware_raw: str,
        imprinter_stamped: bool = False,
        double_feed_detected: bool = False,
        uv_image: Optional[bytes] = None,
    ) -> ScanResult:
        """
        CR-120 specific ingest — captures hardware MICR, imprinter status, and
        optional UV image alongside the standard duplex scan.

        micr_hardware_raw comes directly from the Ranger Transport API
        TransportGetMICR() call — it is the authoritative MICR source for the
        outward path. Never log it in full (contains account number).

        The base ingest() method still populates micr_raw with the same value
        so that all downstream code that reads micr_raw continues to work
        without change.
        """
        result = self.ingest(
            front_image=front_image,
            rear_image=rear_image,
            front_dpi=front_dpi,
            rear_dpi=rear_dpi,
            micr_raw=micr_hardware_raw,
        )
        result.micr_hardware_raw    = micr_hardware_raw
        result.imprinter_stamped    = imprinter_stamped
        result.double_feed_detected = double_feed_detected
        result.uv_image             = uv_image
        return result


class GenericAdapter(ScannerAdapter):
    """Fallback adapter for unrecognised OEMs that expose TWAIN/ISIS interface."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.GENERIC


# Factory — selects adapter by OEM string from config_service
def get_adapter(oem_name: str, scanner_model: str, bank_id: str, operator_id: str) -> ScannerAdapter:
    mapping = {
        'PANINI':  PaniniAdapter,
        'CANON':   CanonAdapter,
        'GENERIC': GenericAdapter,
    }
    cls = mapping.get(oem_name.upper(), GenericAdapter)
    return cls(scanner_model=scanner_model, bank_id=bank_id, operator_id=operator_id)
