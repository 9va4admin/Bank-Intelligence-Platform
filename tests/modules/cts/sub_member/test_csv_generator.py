"""Tests for BatchSummaryCSVGenerator."""
import pytest
from datetime import datetime

from modules.cts.sub_member.models import (
    SubMemberBank, SubMemberBatchLedger, SubMemberReturn, ClearingBucket
)
from modules.cts.sub_member.csv_generator import BatchSummaryCSVGenerator


@pytest.fixture
def smb():
    return SubMemberBank(
        sub_member_id="SMB-MH-001",
        bank_name="Vasavi Co-op Bank",
        sponsor_bank_id="SVCB-DIRECT-001",
        micr_prefix="400053",
        ifsc_prefix="VASB",
        branch_manager_email="bm@vasavi.bank",
        ops_head_email="ops@vasavi.bank",
        gm_email="gm@vasavi.bank",
        return_rate_threshold=0.15,
        soft_hold_threshold=0.25,
    )


@pytest.fixture
def ledger(smb):
    l = SubMemberBatchLedger(
        sub_member_id=smb.sub_member_id,
        session_date="2026-06-19",
        clearing_session="MORNING",
    )
    l.total_received = 100
    l.stp_pass = 70
    l.stp_return = 30
    return l


@pytest.fixture
def returns():
    return [
        SubMemberReturn(
            instrument_id="CHQ-IN-20260619-0042",
            sub_member_id="SMB-MH-001",
            return_reason="SIGNATURE_MISMATCH",
            bucket=ClearingBucket.STP_RETURN,
            amount_range="₹[1L-5L]",
            cheque_number_suffix="7890",
            returned_at=datetime(2026, 6, 19, 11, 30),
        ),
        SubMemberReturn(
            instrument_id="CHQ-IN-20260619-0043",
            sub_member_id="SMB-MH-001",
            return_reason="FUNDS_INSUFFICIENT",
            bucket=ClearingBucket.STP_RETURN,
            amount_range="₹[<1L]",
            cheque_number_suffix="1234",
            returned_at=datetime(2026, 6, 19, 11, 45),
        ),
    ]


@pytest.fixture
def gen():
    return BatchSummaryCSVGenerator()


class TestBatchSummaryCSVGenerator:
    def test_generate_returns_string(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert isinstance(result, str)

    def test_csv_contains_header_columns(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "instrument_id" in result
        assert "cheque_ref_last4" in result
        assert "return_reason" in result
        assert "clearing_bucket" in result
        assert "amount_range" in result
        assert "returned_at" in result

    def test_csv_contains_instrument_ids(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "CHQ-IN-20260619-0042" in result
        assert "CHQ-IN-20260619-0043" in result

    def test_cheque_ref_masked_last4_only(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "****7890" in result
        assert "****1234" in result

    def test_no_full_cheque_number_in_output(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        # cheque suffixes are only 4 digits — ensure they appear masked
        assert "****7890" in result
        # raw suffix without mask shouldn't appear as a standalone field
        lines = result.splitlines()
        data_lines = [l for l in lines if not l.startswith("#")]
        for line in data_lines[1:]:  # skip header
            assert "7890" not in line or "****7890" in line

    def test_amount_range_in_csv_not_exact(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "₹[1L-5L]" in result
        assert "₹[<1L]" in result
        assert "amount_paise" not in result

    def test_metadata_header_present(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "# ASTRA CTS" in result
        assert "Vasavi Co-op Bank" in result
        assert "SMB-MH-001" in result

    def test_session_info_in_header(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "MORNING" in result
        assert "2026-06-19" in result

    def test_footer_summary_contains_totals(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "Total Received" in result
        assert "100" in result

    def test_footer_has_return_rate(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "30.00%" in result

    def test_footer_has_stp_pass_rate(self, gen, smb, ledger, returns):
        result = gen.generate(smb, ledger, returns)
        assert "70.00%" in result

    def test_empty_returns_generates_header_only(self, gen, smb, ledger):
        result = gen.generate(smb, ledger, [])
        assert "instrument_id" in result
        # no data rows — just header and footer
        lines = [l for l in result.splitlines() if not l.startswith("#")]
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) == 1  # just the CSV header row

    def test_generate_rows_masks_cheque_suffix(self, gen, returns):
        rows = gen.generate_rows(returns)
        assert rows[0]["cheque_ref_last4"] == "****7890"
        assert rows[1]["cheque_ref_last4"] == "****1234"

    def test_generate_rows_uses_bucket_value(self, gen, returns):
        rows = gen.generate_rows(returns)
        assert rows[0]["clearing_bucket"] == "STP_RETURN"

    def test_generate_rows_formats_returned_at(self, gen, returns):
        rows = gen.generate_rows(returns)
        assert rows[0]["returned_at"] == "2026-06-19 11:30:00"

    def test_soft_hold_shown_in_footer(self, gen, smb, ledger, returns):
        ledger.soft_hold_active = True
        result = gen.generate(smb, ledger, returns)
        assert "YES" in result

    def test_soft_hold_no_when_inactive(self, gen, smb, ledger, returns):
        ledger.soft_hold_active = False
        result = gen.generate(smb, ledger, returns)
        assert "NO" in result
