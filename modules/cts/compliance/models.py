"""
CTS-2010 Compliance Certificate — data models.

An InstrumentComplianceRecord validates a single cheque image against CTS-2010 thresholds.
A BatchComplianceCertificate aggregates records for a full lot/batch before NGCH submission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from modules.cts.compliance.cts2010 import CTS2010Standard


# ── URRBCH Return Reason Code Registry ────────────────────────────────────────
# Uniform Regulations and Rules for Bankers' Clearing House — all 92 codes.
# Applies identically to every clearing participant per NPCI mandate.
# Source: CCPs of IDBI Bank, PNB, SBI, Karnataka Bank (all derive from same RBI/IBA framework).

class ReturnReasonCode(str, Enum):
    # ── 01–05: Financial — drawee / refer to drawer ──────────────────────────
    # Source: URRBCH Annexure D codes 1–5 (zero-padded to 2 digits for NGCH wire format)
    INSUFFICIENT_FUNDS              = "01"  # URRBCH 1
    EXCEEDS_ARRANGEMENT             = "02"  # URRBCH 2
    EFFECTS_NOT_CLEARED             = "03"  # URRBCH 3
    REFER_TO_DRAWER                 = "04"  # URRBCH 4
    CONTACT_DRAWER_PRESENT_AGAIN    = "05"  # URRBCH 5
    # ── 10–17: Drawer signature / authority ─────────────────────────────────
    SIGNATURE_INCOMPLETE            = "10"  # URRBCH 10
    SIGNATURE_ILLEGIBLE             = "11"  # URRBCH 11
    SIGNATURE_MISMATCH              = "12"  # URRBCH 12: Drawer's signature differs
    SIGNATURE_REQUIRED              = "13"  # URRBCH 13
    SIGNATURE_NOT_AS_PER_MANDATE    = "14"  # URRBCH 14
    SIGNATURE_TO_OPERATE_NOT_RECV   = "15"  # URRBCH 15
    AUTHORITY_TO_OPERATE_NOT_RECV   = "16"  # URRBCH 16
    ALTERATION_REQUIRES_AUTH        = "17"  # URRBCH 17
    # ── 20–25: Payment stopped / withdrawal frozen ───────────────────────────
    STOP_PAYMENT                    = "20"  # URRBCH 20: Payment stopped by drawer
    PAYMENT_STOPPED_ATTACHMENT      = "21"  # URRBCH 21: Attachment order
    PAYMENT_STOPPED_COURT           = "22"  # URRBCH 22: Court order
    WITHDRAWAL_STOPPED_DEATH        = "23"  # URRBCH 23
    WITHDRAWAL_STOPPED_LUNACY       = "24"  # URRBCH 24
    WITHDRAWAL_STOPPED_INSOLVENCY   = "25"  # URRBCH 25
    # ── 30–42: Date / amount / clearing / endorsement ───────────────────────
    POST_DATED                      = "30"  # URRBCH 30 — NON_CUSTOMER_FAULT
    STALE_CHEQUE                    = "31"  # URRBCH 31 — NON_CUSTOMER_FAULT
    UNDATED                         = "32"  # URRBCH 32 — NON_CUSTOMER_FAULT
    INSTRUMENT_MUTILATED            = "33"  # URRBCH 33 — NON_CUSTOMER_FAULT
    AMOUNT_WORDS_FIGURES_DIFFER     = "34"  # URRBCH 34
    CLEARING_HOUSE_STAMP_REQUIRED   = "35"  # URRBCH 35 — NON_CUSTOMER_FAULT
    WRONGLY_DELIVERED               = "36"  # URRBCH 36 — NON_CUSTOMER_FAULT
    PRESENT_IN_PROPER_ZONE          = "37"  # URRBCH 37 — NON_CUSTOMER_FAULT
    EXTRANEOUS_MATTER               = "38"  # URRBCH 38 — NON_CUSTOMER_FAULT
    IMAGE_NOT_CLEAR                 = "39"  # URRBCH 39 — NON_CUSTOMER_FAULT
    PRESENT_WITH_DOCUMENT           = "40"  # URRBCH 40 — NON_CUSTOMER_FAULT
    ITEM_LISTED_TWICE               = "41"  # URRBCH 41 — NON_CUSTOMER_FAULT
    PAPER_NOT_RECEIVED              = "42"  # URRBCH 42 — NON_CUSTOMER_FAULT
    # ── 50–55: Account status ───────────────────────────────────────────────
    ACCOUNT_CLOSED                  = "50"  # URRBCH 50
    ACCOUNT_TRANSFERRED             = "51"  # URRBCH 51
    NO_SUCH_ACCOUNT                 = "52"  # URRBCH 52
    TITLE_OF_ACCOUNT_REQUIRED       = "53"  # URRBCH 53
    TITLE_OF_ACCOUNT_WRONG          = "54"  # URRBCH 54
    ACCOUNT_FROZEN                  = "55"  # URRBCH 55 — NON_CUSTOMER_FAULT
    # ── 60–68: Crossing / endorsement ───────────────────────────────────────
    CROSSED_TO_TWO_BANKS            = "60"  # URRBCH 60 — NON_CUSTOMER_FAULT
    CROSSING_STAMP_NOT_CANCELLED    = "61"  # URRBCH 61 — NON_CUSTOMER_FAULT
    CLEARING_STAMP_NOT_CANCELLED    = "62"  # URRBCH 62 — NON_CUSTOMER_FAULT
    SPECIALLY_CROSSED_OTHER_BANK    = "63"  # URRBCH 63 — NON_CUSTOMER_FAULT
    PROTECTIVE_CROSSING_INCORRECT   = "64"  # URRBCH 64
    PROTECTIVE_CROSSING_ILLEGIBLE   = "65"  # URRBCH 65
    PAYEES_ENDORSEMENT_REQUIRED     = "66"  # URRBCH 66
    PAYEES_ENDORSEMENT_IRREGULAR    = "67"  # URRBCH 67 — NON_CUSTOMER_FAULT
    THUMB_IMPRESSION_MAGISTRATE     = "68"  # URRBCH 68 — NON_CUSTOMER_FAULT
    # ── 70–76: Advice / SMB settlement ──────────────────────────────────────
    # Numbering follows Citibank/NPCI Annexure C (CBI uses 69–75 for the same range)
    ADVICE_NOT_RECEIVED             = "70"  # URRBCH 70 — NON_CUSTOMER_FAULT
    ADVICE_AMOUNT_NAME_DIFFERS      = "71"  # URRBCH 71 — NON_CUSTOMER_FAULT
    SMB_SPONSOR_FUNDS_INSUFFICIENT  = "72"  # URRBCH 72 — NON_CUSTOMER_FAULT (sub-member settlement)
    PAYEES_SEPARATE_DISCHARGE       = "73"  # URRBCH 73 — NON_CUSTOMER_FAULT
    NOT_PAYABLE_TILL_PROXIMO        = "74"  # URRBCH 74 — NON_CUSTOMER_FAULT
    PAY_ORDER_COUNTER_SIGNATURE     = "75"  # URRBCH 75 — NON_CUSTOMER_FAULT
    INFORMATION_NOT_LEGIBLE         = "76"  # URRBCH 76 — NON_CUSTOMER_FAULT
    # ── 80–88: Technical / connectivity / fraud ──────────────────────────────
    BANK_CERTIFICATE_REQUIRED       = "80"  # URRBCH 80 — NON_CUSTOMER_FAULT
    DRAFT_LOST_ISSUING_OFFICE       = "81"  # URRBCH 81 — NON_CUSTOMER_FAULT
    BANK_BRANCH_BLOCKED             = "82"  # URRBCH 82 — NON_CUSTOMER_FAULT
    DIGITAL_CERT_VALIDATION_FAILURE = "83"  # URRBCH 83 — NON_CUSTOMER_FAULT
    OTHER_CONNECTIVITY_FAILURE      = "84"  # URRBCH 84 — NON_CUSTOMER_FAULT
    ALTERATION_CTS                  = "85"  # URRBCH 85: CTS non-date alteration — customer fault
    FORGED_INSTRUMENT               = "86"  # URRBCH 86: Fake/Forged/Stolen — customer fault
    PAYEES_ACCOUNT_CREDITED_STAMP   = "87"  # URRBCH 87 — NON_CUSTOMER_FAULT
    OTHER_REASON                    = "88"  # URRBCH 88
    # ── 92: Administrative ───────────────────────────────────────────────────
    BANK_EXCLUDE                    = "92"  # URRBCH 92 — NON_CUSTOMER_FAULT (per CBI Annexure D)


# Codes where the customer is NOT at fault — bank must NOT levy return charges.
# Explicit Annexure D list per CBI CCP Section 5.7.3 and Citibank Annexure C,
# translated to Citibank/NPCI numbering for the 70–76 range.
NON_CUSTOMER_FAULT_CODES: frozenset[str] = frozenset({
    # ── Explicit Annexure D non-customer-fault codes ─────────────────────────
    "33",  # Instrument mutilated — requires bank guarantee
    "35",  # Clearing House stamp/date required
    "36",  # Wrongly delivered / not drawn on us
    "37",  # Present in proper zone
    "38",  # Instrument contains extraneous matter
    "39",  # Image not clear — re-scan required
    "40",  # Present with document
    "41",  # Item listed twice — bank/system error
    "42",  # Paper not received
    "60",  # Crossed to two banks
    "61",  # Crossing stamp not cancelled
    "62",  # Clearing stamp not cancelled
    "63",  # Instrument specially crossed to another bank
    "67",  # Payee's endorsement irregular / collecting bank confirmation
    "68",  # Endorsement by mark/thumb impression — Magistrate attestation
    "70",  # Advice not received (Citibank/NPCI code 70; CBI code 69)
    "71",  # Amount/Name differs on advice (Citibank 71; CBI 70)
    "72",  # Drawee bank's funds with sponsor bank insufficient (Citibank 72; CBI 71)
    "73",  # Payee's separate discharge to bank required (Citibank 73; CBI 72)
    "74",  # Not payable till 1st proximo (Citibank 74)
    "75",  # Pay order / cheque requires counter signature (Citibank 75; CBI 74)
    "76",  # Required information not legible/correct (Citibank 76; CBI 75)
    "80",  # Bank's certificate ambiguous/incomplete/required
    "81",  # Draft lost by issuing office
    "82",  # Bank/Branch blocked
    "83",  # Digital Certificate Validation failure
    "84",  # Other reason — connectivity failure
    "87",  # Payee's a/c Credited — Stamp required
    "92",  # Bank exclude (CBI Annexure D)
    # ── By convention: collecting bank timing / procedural failure ───────────
    "30",  # Post-dated — collecting bank should have rejected at intake
    "31",  # Stale cheque — collecting bank should have rejected at intake
    "32",  # Undated — collecting bank error
    "55",  # Account blocked (attachment/court/regulatory — not depositor's fault)
})

# Codes that require re-presentation in the immediate next clearing (max 24 hours).
# Per Karnataka Bank Section 7(ii), SBI, PNB, CBI — universal RBI/NPCI rule.
RE_PRESENTATION_CODES: frozenset[str] = frozenset({
    "35",  # Clearing House stamp/date required — fix and re-present
    "39",  # Image not clear — re-scan and re-present
    "40",  # Present with document — re-present with required documents
    "67",  # Payee's endorsement irregular — collecting bank to resolve and re-present
    "68",  # Endorsement by thumb impression — get Magistrate attestation and re-present
    "83",  # Digital Certificate Validation failure — fix PKI and re-present
})


def is_customer_fault(code: str) -> bool:
    """Returns True if the return reason code implies customer fault (bank may levy charges)."""
    return code not in NON_CUSTOMER_FAULT_CODES


class ComplianceResult(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'


@dataclass
class InstrumentComplianceRecord:
    instrument_id:      str
    cheque_number:      str
    lot_number:         str

    # Front image metrics
    front_dpi:           int
    front_colour_depth:  int
    front_file_size_kb:  float
    front_iqa_score:     float

    # Rear image metrics
    rear_dpi:            int
    rear_colour_depth:   int
    rear_file_size_kb:   float
    rear_iqa_score:      float

    # MICR
    micr_band_score:     float

    def __post_init__(self) -> None:
        self._failure_reasons: list[str] = []
        self._evaluate()

    def _evaluate(self) -> None:
        s = CTS2010Standard
        if self.front_dpi < s.MIN_DPI:
            self._failure_reasons.append('front_dpi')
        if self.rear_dpi < s.MIN_DPI:
            self._failure_reasons.append('rear_dpi')
        if self.front_colour_depth < s.MIN_COLOUR_DEPTH:
            self._failure_reasons.append('front_colour_depth')
        if self.front_file_size_kb > s.MAX_FILE_SIZE_KB:
            self._failure_reasons.append('front_file_size_kb')
        if self.rear_file_size_kb > s.MAX_FILE_SIZE_KB:
            self._failure_reasons.append('rear_file_size_kb')
        if self.front_iqa_score < s.MIN_IQA_SCORE:
            self._failure_reasons.append('front_iqa_score')
        if self.rear_iqa_score < s.MIN_IQA_SCORE:
            self._failure_reasons.append('rear_iqa_score')
        if self.micr_band_score < s.MICR_BAND_MIN_SCORE:
            self._failure_reasons.append('micr_band_score')

    @property
    def failure_reasons(self) -> list[str]:
        return list(self._failure_reasons)

    @property
    def is_compliant(self) -> bool:
        return len(self._failure_reasons) == 0

    @property
    def result(self) -> ComplianceResult:
        return ComplianceResult.PASS if self.is_compliant else ComplianceResult.FAIL


@dataclass
class BatchComplianceCertificate:
    batch_id:    str
    session_id:  str
    bank_ifsc:   str
    issued_at:   datetime
    instruments: list[InstrumentComplianceRecord] = field(default_factory=list)

    @property
    def total_instruments(self) -> int:
        return len(self.instruments)

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.instruments if i.is_compliant)

    @property
    def failed_count(self) -> int:
        return self.total_instruments - self.passed_count

    @property
    def pass_rate(self) -> float:
        if self.total_instruments == 0:
            return 0.0
        return round((self.passed_count / self.total_instruments) * 100, 2)

    @property
    def overall_result(self) -> ComplianceResult:
        return ComplianceResult.PASS if self.failed_count == 0 else ComplianceResult.FAIL
