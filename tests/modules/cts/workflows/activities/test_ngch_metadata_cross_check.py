"""
Tests for NGCH metadata cross-check activity (Item 6).

Compares MICR band fields extracted by GOT-OCR2 against the registered
instrument presentment metadata to catch discrepancies before the lot/NGCH
pipeline:
  - Cheque serial mismatch  (MICR first-6 vs registered cheque_number)
  - Drawee IFSC mismatch    (MICR routing-derived IFSC vs registered IFSC)
  - Amount mismatch         (OCR amount_figures vs registered amount)
  - MICR format / absent    → DEGRADED (never blocks clearing)

Outcomes:
  PROCEED      — all checked fields agree (or insufficient data to disagree)
  HUMAN_REVIEW — at least one field mismatch detected
  DEGRADED     — MICR line absent, too short, or unparseable
"""
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_inp(**kwargs):
    from modules.cts.workflows.activities.ngch_metadata_cross_check import (
        NGCHMetadataCrossCheckInput,
    )
    defaults = dict(
        instrument_id="INST-XC-001",
        bank_id="saraswat-coop",
        micr_line="123456789012345678901234567890123456789",   # 39 chars
        registered_cheque_number="123456",
        ifsc_from_ocr=None,
        registered_drawee_ifsc=None,
        registered_amount_str=None,
        amount_from_ocr=None,
    )
    defaults.update(kwargs)
    return NGCHMetadataCrossCheckInput(**defaults)


VALID_MICR = "123456789012345678901234567890123456789012"   # 42 chars; serial=123456


# ── PROCEED paths ─────────────────────────────────────────────────────────────

class TestProceedPaths:
    @pytest.mark.asyncio
    async def test_cheque_serial_matches_registered(self):
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line=VALID_MICR, registered_cheque_number="123456")
        )
        assert result.outcome == "PROCEED"
        assert result.mismatch_fields == []

    @pytest.mark.asyncio
    async def test_no_registered_data_is_proceed(self):
        """If no registered metadata is provided, nothing to cross-check → PROCEED."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number=None,
                registered_drawee_ifsc=None,
                registered_amount_str=None,
            )
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_amount_match_within_tolerance(self):
        """OCR amount "45000.00" == registered "45000" → PROCEED."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                amount_from_ocr="45000.00",
                registered_amount_str="45000",
            )
        )
        assert result.outcome == "PROCEED"
        assert "AMOUNT" not in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_ifsc_match_proceed(self):
        """IFSC from OCR matches registered drawee IFSC → PROCEED."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                ifsc_from_ocr="SBIN0001234",
                registered_drawee_ifsc="SBIN0001234",
            )
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_ifsc_case_insensitive_match(self):
        """IFSC comparison must be case-insensitive."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                ifsc_from_ocr="sbin0001234",
                registered_drawee_ifsc="SBIN0001234",
            )
        )
        assert result.outcome == "PROCEED"


# ── HUMAN_REVIEW paths ────────────────────────────────────────────────────────

class TestHumanReviewPaths:
    @pytest.mark.asyncio
    async def test_cheque_serial_mismatch_triggers_human_review(self):
        """MICR serial '999999' ≠ registered '123456' → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        # Build MICR where first 6 digits are 999999
        mismatch_micr = "9999997890123456789012345678901234567890"
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line=mismatch_micr, registered_cheque_number="123456")
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "CHEQUE_SERIAL" in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_ifsc_mismatch_triggers_human_review(self):
        """OCR IFSC 'HDFC0000001' ≠ registered 'SBIN0001234' → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                ifsc_from_ocr="HDFC0000001",
                registered_drawee_ifsc="SBIN0001234",
            )
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "DRAWEE_IFSC" in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_amount_mismatch_triggers_human_review(self):
        """OCR amount '4500.00' vs registered '45000' (10× off) → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                amount_from_ocr="4500.00",
                registered_amount_str="45000",
            )
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "AMOUNT" in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_multiple_mismatch_fields_all_reported(self):
        """Two mismatches reported together — not short-circuited."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        mismatch_micr = "9999997890123456789012345678901234567890"
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=mismatch_micr,
                registered_cheque_number="123456",    # serial mismatch
                ifsc_from_ocr="HDFC0000001",
                registered_drawee_ifsc="SBIN0001234", # IFSC mismatch
            )
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "CHEQUE_SERIAL" in result.mismatch_fields
        assert "DRAWEE_IFSC" in result.mismatch_fields

    @pytest.mark.asyncio
    async def test_amount_only_one_side_provided_skips_check(self):
        """If only ocr_amount is present but no registered_amount → skip amount check (not HUMAN_REVIEW)."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(
                micr_line=VALID_MICR,
                registered_cheque_number="123456",
                amount_from_ocr="45000.00",
                registered_amount_str=None,   # only one side
            )
        )
        assert "AMOUNT" not in result.mismatch_fields


# ── DEGRADED paths ────────────────────────────────────────────────────────────

class TestDegradedPaths:
    @pytest.mark.asyncio
    async def test_null_micr_line_returns_degraded(self):
        """MICR line is None (OCR missed it) → DEGRADED, never blocks clearing."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line=None, registered_cheque_number="123456")
        )
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_empty_micr_line_returns_degraded(self):
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line="", registered_cheque_number="123456")
        )
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_short_micr_line_returns_degraded(self):
        """MICR line too short to parse serial → DEGRADED."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line="12345", registered_cheque_number="123456")
        )
        assert result.outcome == "DEGRADED"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_degraded_never_raises(self):
        """Activity must always return, never raise — even on garbage input."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line="GARBAGE!@#$%", registered_cheque_number="123456")
        )
        # Garbage MICR that can't be parsed → DEGRADED (not raise)
        assert result.outcome in ("PROCEED", "HUMAN_REVIEW", "DEGRADED")
        assert not result.degraded or result.outcome == "DEGRADED"


# ── result structure ──────────────────────────────────────────────────────────

class TestResultStructure:
    @pytest.mark.asyncio
    async def test_result_has_details_on_mismatch(self):
        """HUMAN_REVIEW result includes details dict for audit trail."""
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        mismatch_micr = "9999997890123456789012345678901234567890"
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line=mismatch_micr, registered_cheque_number="123456")
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "CHEQUE_SERIAL" in result.details
        assert "micr_value" in result.details["CHEQUE_SERIAL"]
        assert "registered_value" in result.details["CHEQUE_SERIAL"]

    @pytest.mark.asyncio
    async def test_proceed_has_empty_mismatch_fields(self):
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata,
        )
        result = await cross_check_ngch_metadata(
            _make_inp(micr_line=VALID_MICR, registered_cheque_number="123456")
        )
        assert result.outcome == "PROCEED"
        assert result.mismatch_fields == []
        assert result.details == {}
