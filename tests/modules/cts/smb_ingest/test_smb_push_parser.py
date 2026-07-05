"""
Tests for SMB CBS push file parser.

SMBs push 3 file types from their CBS to the Agency SFTP every 15 minutes:
  STOP_PAYMENTS  — stop-payment instructions (CSV or fixed-width)
  PPS_ENTRIES    — Positive Pay System entries (amount + payee per cheque)
  SIGNATURES     — new or updated signature specimen references

The parser normalises each format into canonical Pydantic records so that
the rest of the vault update pipeline is format-agnostic.
"""
import pytest
import hashlib

from modules.cts.smb_ingest.models import (
    SMBPushFileType,
    StopPaymentRecord,
    PPSEntry,
    SignatureRecord,
)
from modules.cts.smb_ingest.parser import SMBPushParser, SMBPushParseError


# ── helpers ───────────────────────────────────────────────────────────────

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ── SMBPushFileType ────────────────────────────────────────────────────────

class TestSMBPushFileType:
    def test_all_three_types_defined(self):
        assert SMBPushFileType.STOP_PAYMENTS == "STOP_PAYMENTS"
        assert SMBPushFileType.PPS_ENTRIES == "PPS_ENTRIES"
        assert SMBPushFileType.SIGNATURES == "SIGNATURES"


# ── StopPaymentRecord ──────────────────────────────────────────────────────

class TestStopPaymentRecord:
    def test_fields_present(self):
        r = StopPaymentRecord(
            smb_id="testucb",
            account_number_hash=_hash("1234567890"),
            cheque_number="000123",
            amount_range="₹[1L-5L]",
            issued_date="2026-07-05",
            reason="LOST_CHEQUE",
        )
        assert r.smb_id == "testucb"
        assert r.cheque_number == "000123"
        assert r.amount_range == "₹[1L-5L]"

    def test_frozen(self):
        r = StopPaymentRecord(
            smb_id="testucb",
            account_number_hash=_hash("111"),
            cheque_number="000001",
            amount_range="₹[<1L]",
            issued_date="2026-07-05",
            reason="THEFT",
        )
        with pytest.raises(Exception):
            r.smb_id = "other"


# ── PPSEntry ───────────────────────────────────────────────────────────────

class TestPPSEntry:
    def test_fields_present(self):
        e = PPSEntry(
            smb_id="testucb",
            account_number_hash=_hash("2222"),
            cheque_number="000456",
            amount_range="₹[5L-10L]",
            payee_hash=_hash("ACME Corp"),
        )
        assert e.smb_id == "testucb"
        assert e.cheque_number == "000456"
        assert e.payee_hash == _hash("ACME Corp")


# ── SignatureRecord ────────────────────────────────────────────────────────

class TestSignatureRecord:
    def test_fields_present(self):
        r = SignatureRecord(
            smb_id="testucb",
            account_number_hash=_hash("3333"),
            specimen_ref="minio://astra/signatures/testucb/abc123.jpg",
            captured_at="2026-07-01",
        )
        assert r.specimen_ref.startswith("minio://")
        assert r.captured_at == "2026-07-01"


# ── SMBPushParser — stop payments ─────────────────────────────────────────

STOP_CSV = """\
account_number,cheque_number,amount,issued_date,reason
1234567890,000123,150000,2026-07-05,LOST_CHEQUE
9876543210,000456,5500000,2026-07-04,THEFT
"""

STOP_CSV_HEADER_ONLY = "account_number,cheque_number,amount,issued_date,reason\n"

STOP_BANCS_FIXED = (
    "1234567890     000123150000020260705LOST_CHEQUE    \n"
    "9876543210     000456550000020260704THEFT          \n"
)


class TestSMBPushParserStopPayments:
    def test_parse_generic_csv(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV)
        assert len(records) == 2
        assert all(isinstance(r, StopPaymentRecord) for r in records)

    def test_account_number_hashed(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV)
        # raw account number must NOT appear in output
        assert records[0].account_number_hash != "1234567890"
        assert len(records[0].account_number_hash) == 64   # SHA-256 hex

    def test_amount_bucketed_not_exact(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV)
        # 150000 → ₹[1L-5L]
        assert records[0].amount_range == "₹[1L-5L]"
        # 5500000 → ₹[>1Cr] or ₹[10L-1Cr] range
        assert "₹" in records[1].amount_range

    def test_smb_id_propagated(self):
        parser = SMBPushParser(smb_id="cosmos-ucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV)
        assert all(r.smb_id == "cosmos-ucb" for r in records)

    def test_header_only_returns_empty(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV_HEADER_ONLY)
        assert records == []

    def test_empty_string_raises(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        with pytest.raises(SMBPushParseError, match="empty"):
            parser.parse("")

    def test_missing_required_column_raises(self):
        bad_csv = "account_number,cheque_number\n1234567890,000123\n"
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        with pytest.raises(SMBPushParseError, match="column"):
            parser.parse(bad_csv)

    def test_reason_preserved(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.STOP_PAYMENTS)
        records = parser.parse(STOP_CSV)
        assert records[0].reason == "LOST_CHEQUE"
        assert records[1].reason == "THEFT"


# ── SMBPushParser — PPS entries ────────────────────────────────────────────

PPS_CSV = """\
account_number,cheque_number,amount,payee_name
1111111111,000001,250000,ACME Corporation
2222222222,000002,750000,Rajesh Kumar
"""


class TestSMBPushParserPPS:
    def test_parse_pps_csv(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.PPS_ENTRIES)
        records = parser.parse(PPS_CSV)
        assert len(records) == 2
        assert all(isinstance(r, PPSEntry) for r in records)

    def test_payee_hashed_not_stored_raw(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.PPS_ENTRIES)
        records = parser.parse(PPS_CSV)
        assert records[0].payee_hash != "ACME Corporation"
        assert len(records[0].payee_hash) == 64

    def test_account_hashed_in_pps(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.PPS_ENTRIES)
        records = parser.parse(PPS_CSV)
        assert records[0].account_number_hash != "1111111111"

    def test_amount_bucketed_in_pps(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.PPS_ENTRIES)
        records = parser.parse(PPS_CSV)
        assert "₹" in records[0].amount_range


# ── SMBPushParser — signatures ─────────────────────────────────────────────

SIG_CSV = """\
account_number,specimen_ref,captured_at
1234567890,minio://astra/signatures/testucb/sig_001.jpg,2026-07-01
9876543210,minio://astra/signatures/testucb/sig_002.jpg,2026-06-15
"""


class TestSMBPushParserSignatures:
    def test_parse_signatures_csv(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.SIGNATURES)
        records = parser.parse(SIG_CSV)
        assert len(records) == 2
        assert all(isinstance(r, SignatureRecord) for r in records)

    def test_specimen_ref_preserved_exactly(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.SIGNATURES)
        records = parser.parse(SIG_CSV)
        assert records[0].specimen_ref == "minio://astra/signatures/testucb/sig_001.jpg"

    def test_account_hashed_in_signatures(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.SIGNATURES)
        records = parser.parse(SIG_CSV)
        assert records[0].account_number_hash != "1234567890"
        assert len(records[0].account_number_hash) == 64

    def test_captured_at_preserved(self):
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.SIGNATURES)
        records = parser.parse(SIG_CSV)
        assert records[0].captured_at == "2026-07-01"

    def test_missing_specimen_ref_column_raises(self):
        bad = "account_number,captured_at\n1234567890,2026-07-01\n"
        parser = SMBPushParser(smb_id="testucb", file_type=SMBPushFileType.SIGNATURES)
        with pytest.raises(SMBPushParseError, match="column"):
            parser.parse(bad)


# ── Amount bucketing helper (cross-file-type) ──────────────────────────────

class TestAmountBucketing:
    @pytest.mark.parametrize("amount,expected", [
        (0,           "₹[<1L]"),
        (99999,       "₹[<1L]"),
        (100000,      "₹[1L-5L]"),
        (499999,      "₹[1L-5L]"),
        (500000,      "₹[5L-10L]"),
        (999999,      "₹[5L-10L]"),
        (1000000,     "₹[10L-1Cr]"),
        (9999999,     "₹[10L-1Cr]"),
        (10000000,    "₹[>1Cr]"),
        (99999999,    "₹[>1Cr]"),
    ])
    def test_bucket(self, amount, expected):
        from modules.cts.smb_ingest.parser import bucket_amount
        assert bucket_amount(amount) == expected
