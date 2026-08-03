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


# ── Exception ─────────────────────────────────────────────────────────────────

class ScannerMappingError(Exception):
    """Raised when OEM metadata cannot be mapped to the canonical model."""


# ── Config model ──────────────────────────────────────────────────────────────

_VALID_OUTPUT_FORMATS = {"CSV_COMMA", "CSV_PIPE", "CSV_TAB", "XML", "FIXED_WIDTH"}
_VALID_AMOUNT_FORMATS = {"DECIMAL_DOT", "DECIMAL_COMMA", "INTEGER_PAISE"}

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
    image_color_path:    Path
    image_grey_path:     Path
    image_rear_path:     Path

    scan_timestamp:      datetime
    batch_id:            str
    sequence_in_batch:   int
    oem_confidence:      Optional[float]


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

_SIDE_CANONICAL = {"color_front", "grey_front", "rear"}


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
    ) -> tuple[Path, Path, Path]:
        """
        Resolve the three image paths (color_front, grey_front, rear).

        Supports two pattern styles:
          1. Single pattern with {side} token: "{batch_id}_{seq:04d}_{side}.tif"
             Side values come from image_side_mapping values (→ color_front/grey_front/rear).
          2. Triple pattern separated by |: "DCF{seq:06d}.tif|DCG{seq:06d}.tif|DCR{seq:06d}.tif"
             Order: color_front|grey_front|rear.
        """
        pattern = self._cfg.image_naming_pattern

        if "|" in pattern:
            parts = pattern.split("|")
            if len(parts) != 3:
                raise ScannerMappingError(
                    f"Pipe-separated image_naming_pattern must have 3 parts, got {len(parts)}"
                )
            color_path = self._drop / parts[0].format(seq=seq, batch_id=batch_id)
            grey_path  = self._drop / parts[1].format(seq=seq, batch_id=batch_id)
            rear_path  = self._drop / parts[2].format(seq=seq, batch_id=batch_id)
        else:
            # {side} token — need to find which OEM codes map to which canonical side
            side_map = self._cfg.image_side_mapping
            # Validate all three canonical sides are covered
            covered = set(side_map.values())
            for canonical_side in _SIDE_CANONICAL:
                if canonical_side not in covered:
                    raise ScannerMappingError(
                        f"image_side_mapping missing canonical side {canonical_side!r}. "
                        f"All three are required: {_SIDE_CANONICAL}"
                    )
            # Build reverse: canonical → OEM side code
            canonical_to_oem_side: dict[str, str] = {v: k for k, v in side_map.items()}

            def _resolve(canonical_side: str) -> Path:
                oem_side = canonical_to_oem_side[canonical_side]
                filename = pattern.format(batch_id=batch_id, seq=seq, side=oem_side)
                return self._drop / filename

            color_path = _resolve("color_front")
            grey_path  = _resolve("grey_front")
            rear_path  = _resolve("rear")

        # Validate all three exist
        for p in (color_path, grey_path, rear_path):
            if not p.exists():
                raise ScannerMappingError(
                    f"image file not found: {p}. "
                    f"Ensure scanner software wrote images before metadata file."
                )

        return color_path, grey_path, rear_path

    # ── Internal: build canonical record ─────────────────────────────────────

    def _build_canonical(self, mapped: dict[str, Any]) -> ScannedChequeInput:
        batch_id = str(mapped["batch_id"])
        seq      = int(mapped["sequence_in_batch"])

        color_path, grey_path, rear_path = self._resolve_image_paths(batch_id, seq)

        account_hash, account_suffix = self._process_account(str(mapped["account_number"]))

        # Mask payee: first initial + ***
        payee_raw = str(mapped["payee_name"])
        payee_masked = (payee_raw[0] + "***") if payee_raw else "***"

        # oem_confidence is optional — absent → None
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
            scan_timestamp=datetime.now(tz=timezone.utc),
            batch_id=batch_id,
            sequence_in_batch=seq,
            oem_confidence=oem_confidence,
        )
