"""
CTS E2E Cheque Fixture Definitions
===================================
Total cheques: 32  (12 Outward · 20 Inward)
Languages:     English · Hindi · Marathi · Tamil · Telugu · Kannada ·
               Gujarati · Bengali · Malayalam · Bilingual EN+HI ·
               Bilingual EN+MR · Bilingual EN+KN

Date constants (today = 24/08/2026):
  TODAY  = valid cheque date
  FUTURE = post-dated (01/01/2027)
  STALE  = >90 days old → stale (01/04/2026, ~145 days ago)

Polarity: "POSITIVE" = expected happy-path outcome
          "NEGATIVE" = expected rejection / hold / human-review
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional


TODAY = "24/08/2026"
FUTURE = "01/01/2027"    # POST_DATED_HELD trigger
STALE = "01/04/2026"     # STALE_CHEQUE trigger — 145 days ago

# IET deadline 3 hours from test runtime (used for all inward inputs)
_IET_DEADLINE: float = time.time() + 3 * 3600

# Default Layer-3 thresholds (mirrors infra/helm/values/_defaults.yaml)
DEFAULT_CTS_CONFIG: dict = {
    "stp_mode": "FULL_STP",
    "stp_auto_confirm_threshold": 0.92,
    "stp_supervised_confirm_threshold": 0.95,
    "human_review_fraud_threshold": 0.72,
    "high_value_amount_threshold": 500_000.0,
    "iet_minutes": 180,
    "vault_miss_action": "HUMAN_REVIEW",
    "payee_match_threshold": 0.82,
}

FULL_MANUAL_CONFIG: dict = {**DEFAULT_CTS_CONFIG, "stp_mode": "FULL_MANUAL"}


@dataclass
class ChequeFixture:
    fixture_id: str
    pipeline: str           # "OUTWARD" | "INWARD"
    language: str
    polarity: str           # "POSITIVE" | "NEGATIVE"
    scenario: str           # short human label
    trigger: str            # key used by mock_builders to wire the scenario
    expected_outcome: str   # result.outcome (outward) or result.decision (inward)

    # Cheque identity
    instrument_id: str
    bank_id: str
    amount: float
    amount_range: str       # masked, e.g. "₹[1L-5L]"
    payee_name: str         # in local script
    account_number: str
    cheque_number: str
    micr_line: str
    cheque_date: str        # DD/MM/YYYY

    # Outward-specific
    scan_id: Optional[str] = None
    bank_ifsc: str = "SBIN0001234"
    session_id: str = "SESS-20260824-AM"
    payee_account_number: Optional[str] = None    # triggers payee validation
    has_uv_image: bool = False
    has_gray_image: bool = False
    branch_id: Optional[str] = None               # SMB branch for outward
    registered_drawee_ifsc: Optional[str] = None  # for NGCH cross-check scenarios
    payee_name_from_slip: Optional[str] = None    # for payee-name-mismatch scenarios

    # Inward-specific
    smb_id: Optional[str] = None
    ngch_ifsc: Optional[str] = None
    cts_config: dict = field(default_factory=lambda: dict(DEFAULT_CTS_CONFIG))

    # Checklist: which step IDs are expected to have run (in order)
    # Empty = test will auto-derive from trigger
    expected_steps: list[str] = field(default_factory=list)

    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# OUTWARD FIXTURES  (12 cheques — processed first in test run)
# ─────────────────────────────────────────────────────────────────────────────

OUTWARD_FIXTURES: list[ChequeFixture] = [

    # ── POSITIVE ──────────────────────────────────────────────────────────────

    ChequeFixture(
        fixture_id="OUT-01",
        pipeline="OUTWARD",
        language="English",
        polarity="POSITIVE",
        scenario="Clean cheque — all steps pass",
        trigger="ALL_PASS",
        expected_outcome="ACCEPTED",
        instrument_id="OUT-01-ENG-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-01-20260824",
        amount=45_000.0,
        amount_range="₹[<1L]",
        payee_name="Rajan Pillai",
        account_number="123456789012",
        cheque_number="100001",
        micr_line="100001 724020003 123456789012",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        notes="Standard SB clean path — all 14 outward steps pass",
    ),

    ChequeFixture(
        fixture_id="OUT-02",
        pipeline="OUTWARD",
        language="Hindi",
        polarity="POSITIVE",
        scenario="Hindi payee — NGCH cross-check present and passing",
        trigger="ALL_PASS_XCHECK",
        expected_outcome="ACCEPTED",
        instrument_id="OUT-02-HIN-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-02-20260824",
        amount=1_25_000.0,
        amount_range="₹[1L-5L]",
        payee_name="राजेश कुमार",
        account_number="234567890123",
        cheque_number="100002",
        micr_line="100002 724020003 234567890123",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        registered_drawee_ifsc="SBIN0001234",
        notes="Devanagari payee name; NGCH metadata cross-check wired and passing",
    ),

    ChequeFixture(
        fixture_id="OUT-03",
        pipeline="OUTWARD",
        language="Marathi",
        polarity="POSITIVE",
        scenario="SMB-presented cheque — all pass, branch_id set",
        trigger="ALL_PASS",
        expected_outcome="ACCEPTED",
        instrument_id="OUT-03-MAR-20260824",
        bank_id="saraswat-coop",
        scan_id="SCAN-OUT-03-20260824",
        amount=78_500.0,
        amount_range="₹[<1L]",
        payee_name="सुनील पाटील",
        account_number="345678901234",
        cheque_number="200001",
        micr_line="200001 743020003 345678901234",
        cheque_date=TODAY,
        bank_ifsc="SRCB0000001",
        branch_id="SMB-PUNE-BRANCH-01",
        notes="Marathi payee; SMB-presented via branch_id",
    ),

    # ── NEGATIVE ──────────────────────────────────────────────────────────────

    ChequeFixture(
        fixture_id="OUT-04",
        pipeline="OUTWARD",
        language="Tamil",
        polarity="NEGATIVE",
        scenario="Post-dated cheque — future date → POST_DATED_HELD",
        trigger="POST_DATED",
        expected_outcome="POST_DATED_HELD",
        instrument_id="OUT-04-TAM-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-04-20260824",
        amount=2_50_000.0,
        amount_range="₹[1L-5L]",
        payee_name="கணேஷ் குமார்",
        account_number="456789012345",
        cheque_number="300001",
        micr_line="300001 724020003 456789012345",
        cheque_date=FUTURE,
        bank_ifsc="FDRL0001234",
        notes="Tamil script payee; cheque dated 01/01/2027 → POST_DATED_HELD",
    ),

    ChequeFixture(
        fixture_id="OUT-05",
        pipeline="OUTWARD",
        language="Telugu",
        polarity="NEGATIVE",
        scenario="Stale cheque — date >90 days old → CTS_REJECTED",
        trigger="STALE_DATE",
        expected_outcome="CTS_REJECTED",
        instrument_id="OUT-05-TEL-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-05-20260824",
        amount=15_000.0,
        amount_range="₹[<1L]",
        payee_name="వెంకటేశ్వర రావు",
        account_number="567890123456",
        cheque_number="400001",
        micr_line="400001 724020003 567890123456",
        cheque_date=STALE,
        bank_ifsc="FDRL0001234",
        notes="Telugu script; cheque dated 01/04/2026 = 145 days old → stale",
    ),

    ChequeFixture(
        fixture_id="OUT-06",
        pipeline="OUTWARD",
        language="Kannada",
        polarity="NEGATIVE",
        scenario="CTS-2010 non-compliant — DPI below minimum → CTS_REJECTED",
        trigger="CTS2010_FAIL",
        expected_outcome="CTS_REJECTED",
        instrument_id="OUT-06-KAN-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-06-20260824",
        amount=32_000.0,
        amount_range="₹[<1L]",
        payee_name="ರಾಜೇಶ್ ಕುಮಾರ್",
        account_number="678901234567",
        cheque_number="500001",
        micr_line="500001 724020003 678901234567",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        notes="Kannada script; scanner DPI 150 (below 200 minimum)",
    ),

    ChequeFixture(
        fixture_id="OUT-07",
        pipeline="OUTWARD",
        language="Gujarati",
        polarity="NEGATIVE",
        scenario="NGCH metadata mismatch — MICR IFSC ≠ registered IFSC → CTS_REJECTED",
        trigger="NGCH_MISMATCH",
        expected_outcome="CTS_REJECTED",
        instrument_id="OUT-07-GUJ-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-07-20260824",
        amount=95_000.0,
        amount_range="₹[<1L]",
        payee_name="રાજેશ પટેલ",
        account_number="789012345678",
        cheque_number="600001",
        micr_line="600001 724020003 789012345678",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        registered_drawee_ifsc="HDFC0000123",   # ← deliberately mismatches bank_ifsc
        notes="Gujarati script; registered IFSC differs from MICR IFSC",
    ),

    ChequeFixture(
        fixture_id="OUT-08",
        pipeline="OUTWARD",
        language="Bengali",
        polarity="NEGATIVE",
        scenario="Payee account not found in CBS → CTS_REJECTED",
        trigger="PAYEE_NOT_FOUND",
        expected_outcome="CTS_REJECTED",
        instrument_id="OUT-08-BEN-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-08-20260824",
        amount=55_000.0,
        amount_range="₹[<1L]",
        payee_name="রাজেশ কুমার",
        account_number="890123456789",
        cheque_number="700001",
        micr_line="700001 724020003 890123456789",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        payee_account_number="999999999999",   # triggers payee validation
        notes="Bengali script; payee account does not exist in CBS",
    ),

    ChequeFixture(
        fixture_id="OUT-09",
        pipeline="OUTWARD",
        language="Malayalam",
        polarity="NEGATIVE",
        scenario="Vision LLM detects amount mismatch → MISMATCH_HELD",
        trigger="VISION_MISMATCH",
        expected_outcome="MISMATCH_HELD",
        instrument_id="OUT-09-MAL-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-09-20260824",
        amount=3_00_000.0,
        amount_range="₹[1L-5L]",
        payee_name="ജോർജ്ജ് മാത്യൂ",
        account_number="901234567890",
        cheque_number="800001",
        micr_line="800001 724020003 901234567890",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        notes="Malayalam Christian name; Qwen2-VL detects amount_in_words ≠ MICR amount",
    ),

    ChequeFixture(
        fixture_id="OUT-10",
        pipeline="OUTWARD",
        language="Bilingual EN+HI",
        polarity="NEGATIVE",
        scenario="Payee name mismatch — OCR name vs deposit slip → MISMATCH_HELD",
        trigger="PAYEE_NAME_MISMATCH",
        expected_outcome="MISMATCH_HELD",
        instrument_id="OUT-10-BIHI-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-10-20260824",
        amount=1_80_000.0,
        amount_range="₹[1L-5L]",
        payee_name="Rajesh Kumar / राजेश कुमार",
        account_number="012345678901",
        cheque_number="900001",
        micr_line="900001 724020003 012345678901",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        payee_account_number="111111111111",
        payee_name_from_slip="Suresh Kumar",   # ← deliberately different from cheque payee
        notes="Bilingual payee; name on slip 'Suresh Kumar' ≠ 'Rajesh Kumar' on cheque",
    ),

    ChequeFixture(
        fixture_id="OUT-11",
        pipeline="OUTWARD",
        language="Bilingual EN+MR",
        polarity="NEGATIVE",
        scenario="UV security check fails — void pantograph absent → MISMATCH_HELD",
        trigger="UV_FAIL",
        expected_outcome="MISMATCH_HELD",
        instrument_id="OUT-11-BIMR-20260824",
        bank_id="saraswat-coop",
        scan_id="SCAN-OUT-11-20260824",
        amount=4_50_000.0,
        amount_range="₹[1L-5L]",
        payee_name="Sunil Patil / सुनील पाटील",
        account_number="123123123123",
        cheque_number="200002",
        micr_line="200002 743020003 123123123123",
        cheque_date=TODAY,
        bank_ifsc="SRCB0000001",
        has_uv_image=True,
        notes="Bilingual EN+MR; UV lamp scan shows void pantograph missing",
    ),

    ChequeFixture(
        fixture_id="OUT-12",
        pipeline="OUTWARD",
        language="Bilingual EN+KN",
        polarity="NEGATIVE",
        scenario="Alteration detected on gray image — amount field erased → MISMATCH_HELD",
        trigger="ALTERATION_DETECTED",
        expected_outcome="MISMATCH_HELD",
        instrument_id="OUT-12-BIKN-20260824",
        bank_id="federal-bank",
        scan_id="SCAN-OUT-12-20260824",
        amount=75_000.0,
        amount_range="₹[<1L]",
        payee_name="Rajesh Kumar / ರಾಜೇಶ್ ಕುಮಾರ್",
        account_number="456456456456",
        cheque_number="500002",
        micr_line="500002 724020003 456456456456",
        cheque_date=TODAY,
        bank_ifsc="FDRL0001234",
        has_gray_image=True,
        notes="Bilingual EN+KN; gray-image alteration detection flags amount field erasure",
    ),
]



# ─────────────────────────────────────────────────────────────────────────────
# INWARD FIXTURES  (20 cheques — processed after all outward)
# ─────────────────────────────────────────────────────────────────────────────

INWARD_FIXTURES: list[ChequeFixture] = [

    # ── POSITIVE (STP_CONFIRM) ────────────────────────────────────────────────

    ChequeFixture(
        fixture_id="IN-01",
        pipeline="INWARD",
        language="English",
        polarity="POSITIVE",
        scenario="All checks pass — FULL_STP → STP_CONFIRM",
        trigger="ALL_PASS",
        expected_outcome="STP_CONFIRM",
        instrument_id="IN-01-ENG-20260824",
        bank_id="federal-bank",
        amount=45_000.0,
        amount_range="₹[<1L]",
        payee_name="Rajan Pillai",
        account_number="123456789012",
        cheque_number="100001",
        micr_line="100001 724020003 123456789012",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Golden path — all 24 steps pass under FULL_STP mode",
    ),

    ChequeFixture(
        fixture_id="IN-02",
        pipeline="INWARD",
        language="Hindi",
        polarity="POSITIVE",
        scenario="High-value cheque below threshold — FULL_STP → STP_CONFIRM",
        trigger="ALL_PASS",
        expected_outcome="STP_CONFIRM",
        instrument_id="IN-02-HIN-20260824",
        bank_id="federal-bank",
        amount=4_80_000.0,
        amount_range="₹[1L-5L]",
        payee_name="राजेश कुमार",
        account_number="234567890123",
        cheque_number="100002",
        micr_line="100002 724020003 234567890123",
        cheque_date=TODAY,
        ngch_ifsc="SBIN0001234",
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="₹4.8L — below ₹5L threshold; Hindi Devanagari payee; IFSC present and valid",
    ),

    ChequeFixture(
        fixture_id="IN-03",
        pipeline="INWARD",
        language="Marathi",
        polarity="POSITIVE",
        scenario="SMB-presented cheque — all pass → STP_CONFIRM + SMB ledger update",
        trigger="ALL_PASS_SMB",
        expected_outcome="STP_CONFIRM",
        instrument_id="IN-03-MAR-20260824",
        bank_id="saraswat-coop",
        amount=65_000.0,
        amount_range="₹[<1L]",
        payee_name="सुनील पाटील",
        account_number="345678901234",
        cheque_number="200001",
        micr_line="200001 743020003 345678901234",
        cheque_date=TODAY,
        smb_id="SMB-PUNE-001",
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Marathi script; smb_id set → emit_batch_ledger_update must be called",
    ),

    # ── NEGATIVE (STP_RETURN) ─────────────────────────────────────────────────

    ChequeFixture(
        fixture_id="IN-04",
        pipeline="INWARD",
        language="Tamil",
        polarity="NEGATIVE",
        scenario="Stop payment — confirmed CBS hit → STP_RETURN",
        trigger="STOP_PAYMENT_STP",
        expected_outcome="STP_RETURN",
        instrument_id="IN-04-TAM-20260824",
        bank_id="federal-bank",
        amount=1_20_000.0,
        amount_range="₹[1L-5L]",
        payee_name="கணேஷ் குமார்",
        account_number="456789012345",
        cheque_number="300001",
        micr_line="300001 724020003 456789012345",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Tamil script; stop_payment.outcome=STP_RETURN after CBS confirmation",
    ),

    ChequeFixture(
        fixture_id="IN-05",
        pipeline="INWARD",
        language="Telugu",
        polarity="NEGATIVE",
        scenario="CBS balance insufficient → STP_RETURN",
        trigger="CBS_INSUFFICIENT",
        expected_outcome="STP_RETURN",
        instrument_id="IN-05-TEL-20260824",
        bank_id="federal-bank",
        amount=5_50_000.0,
        amount_range="₹[5L-10L]",
        payee_name="వెంకటేశ్వర రావు",
        account_number="567890123456",
        cheque_number="400001",
        micr_line="400001 724020003 567890123456",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Telugu script; CBS balance check returns RETURN (insufficient funds)",
    ),

    ChequeFixture(
        fixture_id="IN-06",
        pipeline="INWARD",
        language="Kannada",
        polarity="NEGATIVE",
        scenario="Account FROZEN in CBS → STP_RETURN",
        trigger="ACCOUNT_FROZEN",
        expected_outcome="STP_RETURN",
        instrument_id="IN-06-KAN-20260824",
        bank_id="federal-bank",
        amount=2_30_000.0,
        amount_range="₹[1L-5L]",
        payee_name="ರಾಜೇಶ್ ಕುಮಾರ್",
        account_number="678901234567",
        cheque_number="500001",
        micr_line="500001 724020003 678901234567",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Kannada script; account_status=FROZEN → mandatory STP_RETURN",
    ),

    ChequeFixture(
        fixture_id="IN-07",
        pipeline="INWARD",
        language="Gujarati",
        polarity="NEGATIVE",
        scenario="Cheque series invalid — series not registered → STP_RETURN",
        trigger="CHEQUE_SERIES_STP",
        expected_outcome="STP_RETURN",
        instrument_id="IN-07-GUJ-20260824",
        bank_id="federal-bank",
        amount=40_000.0,
        amount_range="₹[<1L]",
        payee_name="રાજેશ પટેલ",
        account_number="789012345678",
        cheque_number="600001",
        micr_line="600001 724020003 789012345678",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Gujarati script; cheque_series CBS check returns STP_RETURN with RRC-21",
    ),

    ChequeFixture(
        fixture_id="IN-08",
        pipeline="INWARD",
        language="Bengali",
        polarity="NEGATIVE",
        scenario="SMB cheque — stop payment → STP_RETURN + sub-member notify",
        trigger="STOP_PAYMENT_STP",
        expected_outcome="STP_RETURN",
        instrument_id="IN-08-BEN-20260824",
        bank_id="saraswat-coop",
        amount=85_000.0,
        amount_range="₹[<1L]",
        payee_name="রাজেশ কুমার",
        account_number="890123456789",
        cheque_number="700001",
        micr_line="700001 743020003 890123456789",
        cheque_date=TODAY,
        smb_id="SMB-KOLKATA-001",
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Bengali script; SMB-tagged; stop payment → early exit BEFORE SMB ledger section",
    ),

    # ── NEGATIVE (HUMAN_REVIEW) ───────────────────────────────────────────────

    ChequeFixture(
        fixture_id="IN-09",
        pipeline="INWARD",
        language="Malayalam",
        polarity="NEGATIVE",
        scenario="OCR low confidence — Indic script extraction failed → HUMAN_REVIEW",
        trigger="OCR_LOW_CONF",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-09-MAL-20260824",
        bank_id="federal-bank",
        amount=18_000.0,
        amount_range="₹[<1L]",
        payee_name="ജോർജ്ജ് മാത്യൂ",
        account_number="901234567890",
        cheque_number="800001",
        micr_line="800001 724020003 901234567890",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Malayalam Christian name; OCR confidence below ocr_min_confidence threshold",
    ),

    ChequeFixture(
        fixture_id="IN-10",
        pipeline="INWARD",
        language="Bilingual EN+HI",
        polarity="NEGATIVE",
        scenario="Alteration detected — amount field tampered → HUMAN_REVIEW",
        trigger="ALTERATION",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-10-BIHI-20260824",
        bank_id="federal-bank",
        amount=3_00_000.0,
        amount_range="₹[1L-5L]",
        payee_name="Rajesh Kumar / राजेश कुमार",
        account_number="012345678901",
        cheque_number="900001",
        micr_line="900001 724020003 012345678901",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Bilingual EN+HI; Qwen2-VL detects alteration_detected=True on amount field",
    ),

    ChequeFixture(
        fixture_id="IN-11",
        pipeline="INWARD",
        language="Bilingual EN+TA",
        polarity="NEGATIVE",
        scenario="Security feature absent — void pantograph missing → HUMAN_REVIEW",
        trigger="SECURITY_FEAT_FAIL",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-11-BITA-20260824",
        bank_id="federal-bank",
        amount=60_000.0,
        amount_range="₹[<1L]",
        payee_name="Ganesh Kumar / கணேஷ் குமார்",
        account_number="111222333444",
        cheque_number="100003",
        micr_line="100003 724020003 111222333444",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Bilingual EN+TA; security_features check returns HUMAN_REVIEW (void pantograph absent)",
    ),

    ChequeFixture(
        fixture_id="IN-12",
        pipeline="INWARD",
        language="Mixed HI+MR",
        polarity="NEGATIVE",
        scenario="CTS-2010 non-compliant received image — DPI sub-standard → HUMAN_REVIEW",
        trigger="CTS2010_FAIL",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-12-HIMR-20260824",
        bank_id="saraswat-coop",
        amount=22_000.0,
        amount_range="₹[<1L]",
        payee_name="राजेश कुमार / सुनील पाटील",
        account_number="222333444555",
        cheque_number="200003",
        micr_line="200003 743020003 222333444555",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Mixed HI+MR payee; inward image DPI below CTS-2010 minimum",
    ),

    ChequeFixture(
        fixture_id="IN-13",
        pipeline="INWARD",
        language="Hindi",
        polarity="NEGATIVE",
        scenario="Stop payment bloom hit — probabilistic, not confirmed → HUMAN_REVIEW",
        trigger="STOP_PAYMENT_BLOOM",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-13-HIN-20260824",
        bank_id="federal-bank",
        amount=90_000.0,
        amount_range="₹[<1L]",
        payee_name="सुरेश शर्मा",
        account_number="333444555666",
        cheque_number="100004",
        micr_line="100004 724020003 333444555666",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Hindi; bloom filter hit → stop_payment.outcome=HUMAN_REVIEW (may be false positive)",
    ),

    ChequeFixture(
        fixture_id="IN-14",
        pipeline="INWARD",
        language="Hindi",
        polarity="NEGATIVE",
        scenario="IFSC not in registry → HUMAN_REVIEW",
        trigger="IFSC_INVALID",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-14-HIN-20260824",
        bank_id="federal-bank",
        amount=1_50_000.0,
        amount_range="₹[1L-5L]",
        payee_name="प्रदीप वर्मा",
        account_number="444555666777",
        cheque_number="100005",
        micr_line="100005 724020003 444555666777",
        cheque_date=TODAY,
        ngch_ifsc="UNKN0000000",   # IFSC not in ASTRA registry
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Hindi; IFSC UNKN0000000 not in ASTRA IFSC registry → HUMAN_REVIEW",
    ),

    ChequeFixture(
        fixture_id="IN-15",
        pipeline="INWARD",
        language="Marathi",
        polarity="NEGATIVE",
        scenario="Signature mismatch — Siamese score below threshold → HUMAN_REVIEW via decision",
        trigger="SIG_MISMATCH",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-15-MAR-20260824",
        bank_id="saraswat-coop",
        amount=3_20_000.0,
        amount_range="₹[1L-5L]",
        payee_name="अनिल देशपांडे",
        account_number="555666777888",
        cheque_number="200004",
        micr_line="200004 743020003 555666777888",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Marathi; sig match score 0.41 < 0.85 threshold → decision=HUMAN_REVIEW",
    ),

    ChequeFixture(
        fixture_id="IN-16",
        pipeline="INWARD",
        language="English",
        polarity="NEGATIVE",
        scenario="Fraud score above threshold — XGBoost ensemble flag → HUMAN_REVIEW",
        trigger="FRAUD_HIGH",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-16-ENG-20260824",
        bank_id="federal-bank",
        amount=8_00_000.0,
        amount_range="₹[5L-10L]",
        payee_name="Robert D'Souza",
        account_number="666777888999",
        cheque_number="100006",
        micr_line="100006 724020003 666777888999",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="High-value English; XGBoost fraud score 0.85 > 0.72 threshold",
    ),

    ChequeFixture(
        fixture_id="IN-17",
        pipeline="INWARD",
        language="English",
        polarity="NEGATIVE",
        scenario="CBS unreachable — degrade gracefully → HUMAN_REVIEW",
        trigger="CBS_UNAVAILABLE",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-17-ENG-20260824",
        bank_id="federal-bank",
        amount=55_000.0,
        amount_range="₹[<1L]",
        payee_name="Priya Nair",
        account_number="777888999000",
        cheque_number="100007",
        micr_line="100007 724020003 777888999000",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="CBS connector timeout; workflow degrades to image-only path → HUMAN_REVIEW",
    ),

    ChequeFixture(
        fixture_id="IN-18",
        pipeline="INWARD",
        language="English",
        polarity="NEGATIVE",
        scenario="Account DORMANT — CBS account status check → HUMAN_REVIEW",
        trigger="ACCOUNT_DORMANT",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-18-ENG-20260824",
        bank_id="federal-bank",
        amount=12_000.0,
        amount_range="₹[<1L]",
        payee_name="Sathish Reddy",
        account_number="888999000111",
        cheque_number="100008",
        micr_line="100008 724020003 888999000111",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="DORMANT account → HUMAN_REVIEW (never auto-return without human confirmation)",
    ),

    ChequeFixture(
        fixture_id="IN-19",
        pipeline="INWARD",
        language="English",
        polarity="NEGATIVE",
        scenario="STP mode FULL_MANUAL — AI says CONFIRM but mode forces human review",
        trigger="STP_FULL_MANUAL",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-19-ENG-20260824",
        bank_id="federal-bank",
        amount=35_000.0,
        amount_range="₹[<1L]",
        payee_name="Kavitha Menon",
        account_number="999000111222",
        cheque_number="100009",
        micr_line="100009 724020003 999000111222",
        cheque_date=TODAY,
        cts_config=FULL_MANUAL_CONFIG,   # FULL_MANUAL → all AI confirms go to ops desk
        notes="AI decision=STP_CONFIRM but stp_mode=FULL_MANUAL → downgraded to HUMAN_REVIEW",
    ),

    ChequeFixture(
        fixture_id="IN-20",
        pipeline="INWARD",
        language="English",
        polarity="NEGATIVE",
        scenario="Multi-signature cheque — MSV=RED (mandate not met) → HUMAN_REVIEW",
        trigger="MULTI_SIG_MSV_RED",
        expected_outcome="HUMAN_REVIEW",
        instrument_id="IN-20-ENG-20260824",
        bank_id="federal-bank",
        amount=12_00_000.0,
        amount_range="₹[10L-1Cr]",
        payee_name="ASTRA Technologies Ltd",
        account_number="000111222333",
        cheque_number="100010",
        micr_line="100010 724020003 000111222333",
        cheque_date=TODAY,
        cts_config=dict(DEFAULT_CTS_CONFIG),
        notes="Corp cheque; 2 signatures required; MSV=RED (only 1 signatory verified)",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Convenience accessors
# ─────────────────────────────────────────────────────────────────────────────

ALL_FIXTURES: list[ChequeFixture] = OUTWARD_FIXTURES + INWARD_FIXTURES

OUTWARD_COUNT = len(OUTWARD_FIXTURES)   # 12
INWARD_COUNT = len(INWARD_FIXTURES)     # 20
TOTAL_CHEQUES = len(ALL_FIXTURES)       # 32


def fresh_iet_deadline() -> float:
    return time.time() + 3 * 3600
