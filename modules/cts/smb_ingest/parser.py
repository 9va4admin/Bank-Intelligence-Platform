"""
SMB CBS push file parser.

Normalises CBS batch exports (Finacle CSV, BaNCS fixed-width, generic CSV)
into canonical Pydantic records. All PII is scrubbed at this layer:
  - account_number  → HMAC-SHA256 via shared.utils.pii_crypto.hash_account_number
                       (requires bank_id + pepper — same algorithm as the vault lookups)
  - payee_name      → SHA-256 (non-reversible identifier, not used for vault key)
  - amount          → range bucket via bucket_amount()

The parser never stores raw account numbers, names, or exact amounts.
pepper MUST be the same bank-specific value used in the vault — mismatch produces
hashes that can never be found in vault lookups.
"""
from __future__ import annotations

import csv
import hashlib
import io
from typing import Union

import structlog

from modules.cts.smb_ingest.models import (
    SMBPushFileType,
    StopPaymentRecord,
    PPSEntry,
    SignatureRecord,
)
from shared.utils.pii_crypto import hash_account_number

log = structlog.get_logger()

ParsedRecord = Union[StopPaymentRecord, PPSEntry, SignatureRecord]

# Required columns per file type
_REQUIRED_STOP = {"account_number", "cheque_number", "amount", "issued_date", "reason"}
_REQUIRED_PPS  = {"account_number", "cheque_number", "amount", "payee_name"}
_REQUIRED_SIG  = {"account_number", "specimen_ref", "captured_at"}


class SMBPushParseError(ValueError):
    pass


def bucket_amount(amount: int) -> str:
    """Convert exact amount (paise or rupees) to a range bucket string."""
    if amount < 100_000:
        return "₹[<1L]"
    elif amount < 500_000:
        return "₹[1L-5L]"
    elif amount < 1_000_000:
        return "₹[5L-10L]"
    elif amount < 10_000_000:
        return "₹[10L-1Cr]"
    else:
        return "₹[>1Cr]"


def _hash_payee(payee_name: str) -> str:
    # Plain SHA-256 is acceptable here — payee name is not a lookup key and
    # carries no cross-bank collision risk. This hash is only stored for
    # non-repudiation; it is never used to locate a vault entry.
    return hashlib.sha256(payee_name.strip().encode()).hexdigest()


class SMBPushParser:

    def __init__(
        self,
        smb_id: str,
        file_type: SMBPushFileType,
        bank_id: str = "",
        pepper: str = "",
    ) -> None:
        """
        bank_id and pepper MUST be provided in production — they are required to
        produce account hashes that match the vault key.  Omitting them (or passing
        empty strings) raises ValueError at parse time so the bug is caught immediately,
        not silently.
        """
        if not bank_id or not pepper:
            raise ValueError(
                "SMBPushParser requires bank_id and pepper. "
                "Fetch pepper from config_service.get_secret(f'banks.{bank_id}.pii_hash_pepper')"
            )
        self.smb_id = smb_id
        self.file_type = file_type
        self._bank_id = bank_id
        self._pepper = pepper

    def parse(self, content: str) -> list[ParsedRecord]:
        if not content or not content.strip():
            raise SMBPushParseError("empty: file content is empty")

        if self.file_type == SMBPushFileType.STOP_PAYMENTS:
            return self._parse_stop_payments(content)
        elif self.file_type == SMBPushFileType.PPS_ENTRIES:
            return self._parse_pps(content)
        elif self.file_type == SMBPushFileType.SIGNATURES:
            return self._parse_signatures(content)
        else:
            raise SMBPushParseError(f"unknown file_type: {self.file_type}")

    def _parse_stop_payments(self, content: str) -> list[StopPaymentRecord]:
        reader = csv.DictReader(io.StringIO(content))
        self._assert_columns(reader.fieldnames or [], _REQUIRED_STOP)
        records = []
        for row in reader:
            acct_hash = hash_account_number(
                row["account_number"].strip(), self._bank_id, self._pepper
            )
            records.append(StopPaymentRecord(
                smb_id=self.smb_id,
                account_number_hash=acct_hash,
                cheque_number=row["cheque_number"].strip(),
                amount_range=bucket_amount(int(float(row["amount"].strip()))),
                issued_date=row["issued_date"].strip(),
                reason=row["reason"].strip(),
            ))
        return records

    def _parse_pps(self, content: str) -> list[PPSEntry]:
        reader = csv.DictReader(io.StringIO(content))
        self._assert_columns(reader.fieldnames or [], _REQUIRED_PPS)
        records = []
        for row in reader:
            acct_hash = hash_account_number(
                row["account_number"].strip(), self._bank_id, self._pepper
            )
            records.append(PPSEntry(
                smb_id=self.smb_id,
                account_number_hash=acct_hash,
                cheque_number=row["cheque_number"].strip(),
                amount_range=bucket_amount(int(float(row["amount"].strip()))),
                payee_hash=_hash_payee(row["payee_name"]),
            ))
        return records

    def _parse_signatures(self, content: str) -> list[SignatureRecord]:
        reader = csv.DictReader(io.StringIO(content))
        self._assert_columns(reader.fieldnames or [], _REQUIRED_SIG)
        records = []
        for row in reader:
            acct_hash = hash_account_number(
                row["account_number"].strip(), self._bank_id, self._pepper
            )
            records.append(SignatureRecord(
                smb_id=self.smb_id,
                account_number_hash=acct_hash,
                specimen_ref=row["specimen_ref"].strip(),
                captured_at=row["captured_at"].strip(),
            ))
        return records

    @staticmethod
    def _assert_columns(fieldnames: list[str], required: set[str]) -> None:
        present = {f.strip() for f in fieldnames if f}
        missing = required - present
        if missing:
            raise SMBPushParseError(
                f"column: missing required columns: {', '.join(sorted(missing))}"
            )
