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
    # 01-19: Financial / account status — customer fault
    INSUFFICIENT_FUNDS              = "01"
    EXCEEDS_ARRANGEMENT             = "02"
    EFFECTS_NOT_CLEARED             = "03"
    FULL_COVER_NOT_RECEIVED         = "04"
    PAYMENT_STOPPED                 = "05"
    PAYMENT_COUNTERMANDED           = "06"
    DRAWER_DECEASED                 = "07"
    INSOLVENCY_LIQUIDATION          = "08"
    ACCOUNT_TRANSFERRED             = "09"
    ACCOUNT_CLOSED                  = "10"
    ACCOUNT_DOES_NOT_EXIST          = "11"
    SIGNATURE_MISMATCH              = "12"
    SIGNATURE_REQUIRED              = "13"
    ITEM_LISTED_TWICE               = "14"
    INSTRUMENT_MUTILATED            = "15"
    INSTRUMENT_INCOMPLETE           = "16"
    ALTERATION_REQUIRES_AUTH        = "17"
    INSTRUMENT_DATE_INVALID         = "18"
    NOT_ARRANGED_FOR                = "19"
    # 20-26: Special instructions / SMB
    STOP_PAYMENT                    = "20"
    ANY_ONE_OR_SURVIVOR_DECEASED    = "21"
    SOLE_OPERATOR_DECEASED          = "22"
    LIQUIDATOR_NOT_APPOINTED        = "23"
    ENDORSEMENT_IRREGULAR           = "24"
    SMB_SPONSOR_FUNDS_INSUFFICIENT  = "25"
    BANK_INSOLVENCY                 = "26"
    # 27-29: reserved / bank-specific
    # 30-42: Date, amount, crossing, endorsement
    POST_DATED                      = "30"
    STALE_CHEQUE                    = "31"
    UNDATED                         = "32"
    CROSSED_CHEQUE_CASH             = "33"
    AMOUNT_WORDS_FIGURES_DIFFER     = "34"
    CROSSING_IRREGULAR              = "35"
    OPEN_CHEQUE_CANNOT_ACCEPT       = "36"
    PRESENT_IN_PROPER_ZONE          = "37"
    DRAWEE_BANK_HOLIDAY             = "38"
    IMAGE_NOT_CLEAR                 = "39"
    PRESENTING_BANK_ENDORSEMENT     = "40"
    PAYEES_ENDORSEMENT_REQUIRED     = "41"
    PAYEES_ENDORSEMENT_IRREGULAR    = "42"
    # 43-54: reserved / bank-specific
    ACCOUNT_FROZEN                  = "55"
    # 56-59: reserved
    # 60-75: Technical / routing / mandate
    CLEARING_ZONE_NOT_SERVED        = "60"
    INSTRUMENT_UNPAID               = "61"
    DRAWER_BANK_NOT_CBLS            = "62"
    NON_CTS_CHEQUE                  = "63"
    MICR_BAND_DEFECTIVE             = "67"
    DIGITAL_CERT_VALIDATION_FAILURE = "68"
    BANK_NOT_ON_CBS                 = "69"
    DRAWEE_BANK_OFFLINE             = "70"
    ROUTING_INCORRECT               = "71"
    MANDATE_EXPIRED                 = "72"
    MANDATE_CANCELLED               = "73"
    MANDATE_AMOUNT_EXCEEDED         = "74"
    MANDATE_REVOKED                 = "75"
    # 80-88: Security / fraud
    TECHNICAL_REASON_80             = "80"
    TECHNICAL_REASON_81             = "81"
    TECHNICAL_REASON_82             = "82"
    TECHNICAL_REASON_83             = "83"
    TECHNICAL_REASON_84             = "84"
    ALTERATION_CTS                  = "85"  # non-date field alteration under CTS-2010
    FORGED_INSTRUMENT               = "86"
    SPURIOUS_INSTRUMENT             = "87"
    FRAUD_SUSPECTED                 = "88"
    # 89-91: reserved
    OTHERS                          = "92"


# Codes where the customer is NOT at fault — bank must NOT levy return charges.
# Per IDBI Annexure IV, SBI Annexure II, Karnataka Bank Section 7, PNB Schedule.
NON_CUSTOMER_FAULT_CODES: frozenset[str] = frozenset({
    "25",  # SMB sponsor funds insufficient (sponsor bank settlement — not customer fault)
    "14",  # Item listed twice (bank/system error)
    "30",  # Post-dated (bank's presentation timing error)
    "31",  # Stale cheque (bank's presentation timing error)
    "32",  # Undated (collecting bank error — should not have accepted)
    "33",  # Crossed cheque presented for cash payment
    "35",  # Crossing irregular (collecting bank error)
    "36",  # Open cheque — collecting bank error
    "37",  # Present in proper zone (wrong zone — collecting bank routing error)
    "38",  # Drawee bank holiday (system error)
    "39",  # Image not clear (scanning/capture error)
    "40",  # Presenting bank endorsement missing/irregular
    "41",  # Payee's endorsement required (collecting bank missed this)
    "42",  # Payee's endorsement irregular (collecting bank error)
    "55",  # Account frozen (regulatory/legal — not customer's clearing fault)
    "60",  # Clearing zone not served (routing error)
    "61",  # Instrument unpaid — technical
    "62",  # Drawer bank not on CBLS
    "63",  # Non-CTS cheque presented in CTS
    "67",  # MICR band defective (scanning issue)
    "68",  # Digital certificate validation failure (PKI/infrastructure)
    "69",  # Bank not on CBS
    "70",  # Drawee bank offline
    "71",  # SMB routing incorrect
    "72",  # Mandate expired
    "73",  # Mandate cancelled
    "74",  # Mandate amount exceeded
    "75",  # Mandate revoked
    "80", "81", "82", "83", "84",  # Technical reasons
    "87",  # Spurious instrument (bank detection)
    "88",  # Fraud suspected (bank detection — customer not charged for bank catching fraud)
    "92",  # Others — technical
})

# Codes that require re-presentation in the immediate next clearing (max 24 hours).
# Per Karnataka Bank Section 7(ii), SBI, PNB — universal RBI/NPCI rule.
RE_PRESENTATION_CODES: frozenset[str] = frozenset({
    "39",  # Image not clear — re-scan and re-present
    "40",  # Presenting bank endorsement — fix and re-present
    "67",  # MICR band defective — re-scan
    "68",  # Digital cert failure — fix PKI and re-present
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
