"""
Canonical models for SMB CBS push file records.

All PII is transformed at parse time:
  account_number → HMAC-SHA256 hash (never stored raw)
  payee_name     → SHA-256 hash
  amount         → range bucket (never exact)
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict


class SMBPushFileType(str, Enum):
    STOP_PAYMENTS = "STOP_PAYMENTS"
    PPS_ENTRIES   = "PPS_ENTRIES"
    SIGNATURES    = "SIGNATURES"


class StopPaymentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    smb_id: str
    account_number_hash: str      # HMAC-SHA256 — never raw account number
    cheque_number: str
    amount_range: str             # bucketed: ₹[<1L] | ₹[1L-5L] | etc.
    issued_date: str              # YYYY-MM-DD
    reason: str                   # LOST_CHEQUE | THEFT | DISPUTE | OTHER


class PPSEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    smb_id: str
    account_number_hash: str
    cheque_number: str
    amount_range: str
    payee_hash: str               # SHA-256 of payee_name — never raw name


class SignatureRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    smb_id: str
    account_number_hash: str
    specimen_ref: str             # MinIO object reference: minio://astra/signatures/...
    captured_at: str              # YYYY-MM-DD
