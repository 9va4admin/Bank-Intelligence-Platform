"""
CTS Scanner Drop-Folder Mapper.

Reads OEM scanner software output files from a configured drop folder and
produces OEM-blind ScannedChequeInput records for the CTS pipeline.

Every scanner OEM produces a different metadata file format (CSV dialect, XML,
fixed-width) with different field names, date formats, and amount conventions.
ScannerConfig captures all of this per branch. The mapper absorbs OEM
differences here — the rest of the pipeline never sees them.

Pattern: identical to EJ OEM fingerprinting (detect format → canonical record),
except scanner OEM is explicitly configured per branch rather than auto-detected.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import structlog

log = structlog.get_logger()
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator

# ScannerOEM is the single source of truth in models.py — re-exported here for
# backward compatibility (file_watcher.py and tests import it from mapper).
from modules.cts.scanner.models import ScannerOEM  # noqa: F401


# ── Bundle status ──────────────────────────────────────────────────────────────

from enum import Enum

class BundleStatus(str, Enum):
    COMPLETE         = "COMPLETE"         # UV + front_bw + front_gray + rear_bw all present
    PROCESSABLE      = "PROCESSABLE"      # front_bw + front_gray present; UV and/or rear absent
    INSTRUMENT_HOLD  = "INSTRUMENT_HOLD"  # front_bw or front_gray missing; cannot process


# ── Exception ─────────────────────────────────────────────────────────────────

class ScannerMappingError(Exception):
    """Raised when OEM metadata cannot be mapped to the canonical model."""


# ── Config model ──────────────────────────────────────────────────────────────

_VALID_OUTPUT_FORMATS = {"CSV_COMMA", "CSV_PIPE", "CSV_TAB", "XML", "FIXED_WIDTH"}
_VALID_AMOUNT_FORMATS = {"DECIMAL_DOT", "DECIMAL_COMMA", "INTEGER_PAISE"}

# Canonical image side names.
# front_bw / front_gray are BOTH mandatory — instrument goes to HOLD if either is missing.
# rear and uv are optional — their absence degrades gracefully.
# Legacy aliases color_front / grey_front are accepted for backward compatibility.
_CANONICAL_MANDATORY = {"front_bw", "front_gray", "color_front", "grey_front"}
_CANONICAL_OPTIONAL  = {"rear", "uv"}

class ScannerConfig(BaseModel):
    """
    Branch-level scanner configuration.

    Tells the drop-folder mapper how to parse a specific OEM's metadata file
    and resolve image paths. Stored in cts.scanner_configs (YugabyteDB) and
    served via config_service (Layer 3, hot-reload).
    """
    scanner_config_id:    str
    bank_id:              str
    branch_id:            Optional[str] = None   # None = bank-wide default
    scanner_oem:          ScannerOEM
    scanner_model:        str
    output_format:        str
    date_format:          str   # strptime pattern, e.g. "%d%m%Y"
    amount_format:        str   # DECIMAL_DOT | DECIMAL_COMMA | INTEGER_PAISE
    field_mapping:        dict[str, str]   # OEM field name → canonical field name
    image_naming_pattern: str
    image_side_mapping:   dict[str, str]  # OEM side codes → color_front|grey_front|rear
    drop_folder_path:     str

    @field_validator("output_format")
    @classmethod
    def _check_output_format(cls, v: str) -> str:
        if v not in _VALID_OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {_VALID_OUTPUT_FORMATS}, got {v!r}")
        return v

    @field_validator("amount_format")
    @classmethod
    def _check_amount_format(cls, v: str) -> str:
        if v not in _VALID_AMOUNT_FORMATS:
            raise ValueError(f"amount_format must be one of {_VALID_AMOUNT_FORMATS}, got {v!r}")
        return v


# ── Canonical output model ─────────────────────────────────────────────────────

@dataclass
class ScannedChequeInput:
    """
    OEM-blind canonical output from the drop-folder mapper.

    File-path based: images are NOT loaded into memory here. They are uploaded
    to MinIO by the subsequent OutwardScanWorkflow activity. Keeping paths
    avoids loading 900KB+ per cheque into worker memory.

    PII handling (mandatory):
      - account_number_hash: HMAC-SHA256(bank_pepper, bank_id:account_number)
      - account_suffix: last 4 digits only — for display as ****4521
      - payee_masked: first initial + *** — never full name stored
    """
    scan_id:             str
    branch_id:           str
    oem:                 ScannerOEM
    scanner_model:       str

    # MICR
    micr_line:           str        # full line — never log in full (PII rule)

    # Account — never stored plain
    account_number_hash: str        # HMAC-SHA256 hex, 64 chars
    account_suffix:      str        # last 4 digits: "4521"

    # Scanner OCR extracted
    amount_figures:      Decimal
    amount_words:        str
    payee_masked:        str        # first initial + ***
    cheque_date:         date

    # Image paths (in drop folder — before MinIO upload)
    # Mandatory: front_bw (image_color_path) + front_gray (image_grey_path)
    # Optional:  image_rear_path, image_uv_path
    image_color_path:    Path       # front B&W — mandatory (OCR)
    image_grey_path:     Path       # front grayscale — mandatory (fraud analysis)

    scan_timestamp:      datetime
    batch_id:            str
    sequence_in_batch:   int

    # Fields with defaults must come last in a dataclass
    oem_confidence:      Optional[float] = None
    image_rear_path:     Optional[Path]  = None   # rear B&W — optional (deposit slip OCR)
    image_uv_path:       Optional[Path]  = None   # UV scan — optional (security features)
    bundle_status:       "BundleStatus"  = None   # COMPLETE | PROCESSABLE | INSTRUMENT_HOLD


# ── Required canonical fields (mapper validates these are present after mapping) ──

_REQUIRED_CANONICAL = {
    "micr_line",
    "amount_figures",
    "amount_words",
    "payee_name",
    "cheque_date",
    "batch_id",
    "sequence_in_batch",
    "account_number",
}

# All canonical image side names (mandatory + optional + legacy aliases).
_SIDE_CANONICAL = {"color_front", "grey_front", "front_bw", "front_gray", "rear", "uv"}


# ── Mapper ────────────────────────────────────────────────────────────────────

class ScannerDropFolderMapper:
    """
    Maps OEM scanner metadata file → list[ScannedChequeInput].

    Usage:
        mapper = ScannerDropFolderMapper(config)
        records = mapper.parse_metadata_file(Path("/drop/BATCH001.dat"))
    """

    def __init__(self, config: ScannerConfig) -> None:
        self._cfg = config
        self._drop = Path(config.drop_folder_path)
        # Invert field_mapping: canonical → OEM
        self._canonical_to_oem: dict[str, str] = {v: k for k, v in config.field_mapping.items()}

    # ── Public API ──────────────────────────────────────────────────────────

    def parse_metadata_file(self, metadata_path: Path) -> list[ScannedChequeInput]:
        """
        Parse OEM metadata file at metadata_path.
        Returns one ScannedChequeInput per cheque in the batch.
        Raises ScannerMappingError on any mapping failure.
        """
        if self._cfg.output_format == "XML":
            raw_records = self._parse_xml(metadata_path)
        else:
            delimiter = self._csv_delimiter()
            raw_records = self._parse_csv(metadata_path, delimiter)

        results: list[ScannedChequeInput] = []
        for raw in raw_records:
            mapped = self._apply_field_mapping(raw)
            self._validate_required_fields(mapped)
            result = self._build_canonical(mapped)
            results.append(result)
        return results

    # ── Amount parsing ───────────────────────────────────────────────────────

    def _parse_amount(self, value: str) -> Decimal:
        """
        Parse amount string per config.amount_format.

        DECIMAL_COMMA: Indian lakh notation  "1,23,456.00"  → 123456.00
        DECIMAL_DOT:   Standard decimal       "123456.50"   → 123456.50
        INTEGER_PAISE: Paise as integer        "12345600"   → 123456.00
        """
        fmt = self._cfg.amount_format
        try:
            if fmt == "INTEGER_PAISE":
                paise = int(value.strip())
                return Decimal(paise) / Decimal(100)
            else:
                # Remove all commas (Indian lakh separators or thousands separators)
                cleaned = value.strip().replace(",", "")
                return Decimal(cleaned)
        except (InvalidOperation, ValueError) as exc:
            raise ScannerMappingError(f"Cannot parse amount {value!r} with format {fmt}: {exc}") from exc

    # ── Date parsing ─────────────────────────────────────────────────────────

    def _parse_date(self, value: str) -> date:
        try:
            return datetime.strptime(value.strip(), self._cfg.date_format).date()
        except ValueError as exc:
            raise ScannerMappingError(
                f"Cannot parse date {value!r} with format {self._cfg.date_format!r}: {exc}"
            ) from exc

    # ── Account masking ───────────────────────────────────────────────────────

    def _process_account(self, account_number: str) -> tuple[str, str]:
        """
        Returns (account_number_hash, account_suffix).

        hash: HMAC-SHA256(bank_id + account_number, key=bank_id).
        Using bank_id as both pepper and HMAC key ensures cross-bank isolation:
        the same account number at two different banks produces different hashes.

        In production, the pepper comes from Vault via config_service.
        For testability, bank_id is used directly — callers that need the real
        pepper should subclass and override _get_pepper().
        """
        acct = account_number.strip()
        pepper = self._get_pepper()
        message = f"{self._cfg.bank_id}:{acct}".encode()
        digest = hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()
        suffix = acct[-4:] if len(acct) >= 4 else acct
        return digest, suffix

    def _get_pepper(self) -> str:
        # Override in production to fetch from Vault via config_service.
        # Default: use bank_id so tests are deterministic without Vault.
        return self._cfg.bank_id

    # ── Internal: CSV ─────────────────────────────────────────────────────────

    def _csv_delimiter(self) -> str:
        return {
            "CSV_COMMA": ",",
            "CSV_PIPE":  "|",
            "CSV_TAB":   "\t",
        }[self._cfg.output_format]

    def _parse_csv(self, path: Path, delimiter: str) -> list[dict[str, str]]:
        text = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [dict(row) for row in reader]

    # ── Internal: XML ─────────────────────────────────────────────────────────

    def _parse_xml(self, path: Path) -> list[dict[str, str]]:
        tree = ET.parse(path)
        root = tree.getroot()
        records: list[dict[str, str]] = []
        # Support both <Batch><Item>...</Item></Batch> and <Items><Item>...</Item></Items>
        for item in root.iter("Item"):
            record: dict[str, str] = {}
            for child in item:
                record[child.tag] = (child.text or "").strip()
            records.append(record)
        return records

    # ── Internal: field mapping ───────────────────────────────────────────────

    def _apply_field_mapping(self, raw: dict[str, str]) -> dict[str, Any]:
        """Map OEM field names → canonical field names."""
        mapped: dict[str, Any] = {}
        for oem_field, value in raw.items():
            oem_field_stripped = oem_field.strip()
            canonical = self._cfg.field_mapping.get(oem_field_stripped)
            if canonical:
                mapped[canonical] = value.strip() if value else ""
        return mapped

    # ── Internal: validation ──────────────────────────────────────────────────

    def _validate_required_fields(self, mapped: dict[str, Any]) -> None:
        for field in _REQUIRED_CANONICAL:
            if field not in mapped or mapped[field] == "":
                raise ScannerMappingError(
                    f"required field {field!r} missing or empty after field mapping. "
                    f"Check field_mapping config for OEM {self._cfg.scanner_oem}."
                )

    # ── Internal: image path resolution ──────────────────────────────────────

    def _resolve_image_paths(
        self, batch_id: str, seq: int
    ) -> tuple[Path, Path, Optional[Path], Optional[Path], "BundleStatus"]:
        """
        Resolve image paths for one instrument.

        Returns (front_bw_path, front_gray_path, rear_path, uv_path, bundle_status).

        front_bw and front_gray are BOTH mandatory — if either is missing, the
        instrument goes to INSTRUMENT_HOLD (not a fatal error for the batch).
        rear and uv are optional — their absence produces PROCESSABLE status.

        Supports two pattern styles:
          1. {side} token: "{batch_id}_{seq:04d}_{side}.tif"
             image_side_mapping maps OEM codes → canonical names.
             Canonical mandatory: front_bw or color_front (legacy alias),
                                  front_gray or grey_front (legacy alias).
             Canonical optional:  rear, uv.
          2. Pipe-separated: "F{seq}.tif|G{seq}.tif|R{seq}.tif"
             Order must be: front_bw | front_gray | rear (3 or 4 parts; 4th = uv).
        """
        pattern = self._cfg.image_naming_pattern
        side_map = self._cfg.image_side_mapping
        # Build reverse: canonical name → OEM side code
        canonical_to_oem: dict[str, str] = {v: k for k, v in side_map.items()}

        # Normalise legacy aliases so lookup logic is uniform
        def _canonical_for(preferred: str, legacy: str) -> Optional[str]:
            if preferred in canonical_to_oem:
                return preferred
            if legacy in canonical_to_oem:
                return legacy
            return None

        front_bw_canon  = _canonical_for("front_bw",   "color_front")
        front_gray_canon = _canonical_for("front_gray", "grey_front")
        rear_canon  = "rear" if "rear" in canonical_to_oem else None
        uv_canon    = "uv"   if "uv"   in canonical_to_oem else None

        if front_bw_canon is None or front_gray_canon is None:
            raise ScannerMappingError(
                "image_side_mapping must include both a front_bw (or color_front) "
                "and a front_gray (or grey_front) entry. "
                f"Got: {list(side_map.values())}"
            )

        if "|" in pattern:
            parts = pattern.split("|")
            if len(parts) not in (3, 4):
                raise ScannerMappingError(
                    f"Pipe-separated image_naming_pattern must have 3 or 4 parts, got {len(parts)}"
                )
            color_path = self._drop / parts[0].format(seq=seq, batch_id=batch_id)
            grey_path  = self._drop / parts[1].format(seq=seq, batch_id=batch_id)
            rear_path_raw = self._drop / parts[2].format(seq=seq, batch_id=batch_id)
            uv_path_raw   = (self._drop / parts[3].format(seq=seq, batch_id=batch_id)) if len(parts) == 4 else None
        else:
            def _path_for(canonical: str) -> Path:
                oem_code = canonical_to_oem[canonical]
                return self._drop / pattern.format(batch_id=batch_id, seq=seq, side=oem_code)

            color_path    = _path_for(front_bw_canon)
            grey_path     = _path_for(front_gray_canon)
            rear_path_raw = _path_for(rear_canon) if rear_canon else None
            uv_path_raw   = _path_for(uv_canon)   if uv_canon   else None

        # Mandatory images: INSTRUMENT_HOLD if either is missing
        missing_mandatory = []
        if not color_path.exists():
            missing_mandatory.append(str(color_path))
        if not grey_path.exists():
            missing_mandatory.append(str(grey_path))

        if missing_mandatory:
            log.warning(
                "scanner.bundle.mandatory_images_missing",
                batch_id=batch_id,
                seq=seq,
                missing=missing_mandatory,
            )
            return (
                color_path, grey_path,
                None, None,
                BundleStatus.INSTRUMENT_HOLD,
            )

        # Optional images: degrade gracefully when absent
        rear_path = rear_path_raw if (rear_path_raw and rear_path_raw.exists()) else None
        uv_path   = uv_path_raw   if (uv_path_raw   and uv_path_raw.exists())   else None

        if rear_path and uv_path:
            status = BundleStatus.COMPLETE
        else:
            status = BundleStatus.PROCESSABLE

        return color_path, grey_path, rear_path, uv_path, status

    # ── Internal: build canonical record ─────────────────────────────────────

    def _build_canonical(self, mapped: dict[str, Any]) -> ScannedChequeInput:
        batch_id = str(mapped["batch_id"])
        seq      = int(mapped["sequence_in_batch"])

        color_path, grey_path, rear_path, uv_path, bundle_status = \
            self._resolve_image_paths(batch_id, seq)

        account_hash, account_suffix = self._process_account(str(mapped["account_number"]))

        payee_raw = str(mapped["payee_name"])
        payee_masked = (payee_raw[0] + "***") if payee_raw else "***"

        confidence_raw = mapped.get("oem_confidence")
        oem_confidence = float(confidence_raw) if confidence_raw and confidence_raw != "" else None

        scan_id = f"SCAN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        return ScannedChequeInput(
            scan_id=scan_id,
            branch_id=self._cfg.branch_id or "",
            oem=self._cfg.scanner_oem,
            scanner_model=self._cfg.scanner_model,
            micr_line=str(mapped["micr_line"]),
            account_number_hash=account_hash,
            account_suffix=account_suffix,
            amount_figures=self._parse_amount(str(mapped["amount_figures"])),
            amount_words=str(mapped["amount_words"]),
            payee_masked=payee_masked,
            cheque_date=self._parse_date(str(mapped["cheque_date"])),
            image_color_path=color_path,
            image_grey_path=grey_path,
            image_rear_path=rear_path,
            image_uv_path=uv_path,
            bundle_status=bundle_status,
            scan_timestamp=datetime.now(tz=timezone.utc),
            batch_id=batch_id,
            sequence_in_batch=seq,
            oem_confidence=oem_confidence,
        )
