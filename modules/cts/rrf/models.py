"""
RRF (Return Reason File) domain models.
RBI/NPCI CTS standard return reason codes — filed to NGCH for returned instruments.
Reference: CTS-2010 operational guidelines, NPCI circular on IET enforcement Jan 2026.
CTS Spec Rev 3.0 additions: code 88 (Other Reason) requires ReturnReasonComment;
code 00 (On Realization Positive) valid for ClearingType=14 sessions only;
code 99 (Deemed Accepted by CCH) is NEVER sent by a bank — CCH assigns it only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class _ReturnCodeMeta:
    code: str
    description: str


class RBIReturnCode(Enum):
    """
    RBI-mandated return reason codes for CTS instruments.
    These are the ONLY codes accepted by NGCH in the RRF XML.
    """
    FUNDS_INSUFFICIENT          = _ReturnCodeMeta('01', 'Funds Insufficient')
    EXCEED_ARRANGEMENT          = _ReturnCodeMeta('02', 'Exceeds Arrangement')
    EFFECTS_NOT_CLEARED         = _ReturnCodeMeta('03', 'Effects Not Cleared — Present Again')
    REFER_TO_DRAWER             = _ReturnCodeMeta('04', 'Refer to Drawer')
    EXCEEDS_LIMIT               = _ReturnCodeMeta('05', 'Exceeds Limit')
    SIGNATURE_DIFFERS           = _ReturnCodeMeta('06', 'Drawer Signature Differs')
    ALTERATION_REQUIRES_AUTH    = _ReturnCodeMeta('07', 'Alterations Require Authentication')
    PAYMENT_STOPPED             = _ReturnCodeMeta('08', 'Payment Stopped by Drawer')
    PAYEE_ENDORSEMENT_REQUIRED  = _ReturnCodeMeta('09', "Payee's Endorsement Required")
    PAYEE_ENDORSEMENT_IRREGULAR = _ReturnCodeMeta('10', "Payee's Endorsement Irregular/Illegible")
    ENDORSEMENT_NEEDS_BANK_CONF = _ReturnCodeMeta('11', "Payee's Endorsement Requires Bank Confirmation")
    DRAWER_DECEASED_INSOLVENT   = _ReturnCodeMeta('12', 'Drawer Deceased / Insolvent / Insane')
    ACCOUNT_CLOSED              = _ReturnCodeMeta('13', 'Account Closed / Transferred / Not Traceable')
    CHEQUE_POST_DATED           = _ReturnCodeMeta('14', 'Cheque Post-Dated')
    CHEQUE_STALE_MUTILATED      = _ReturnCodeMeta('15', 'Cheque Stale / Mutilated / Torn')
    WORDS_FIGURES_DIFFER        = _ReturnCodeMeta('16', 'Amount in Words and Figures Differs')
    CROSSED_CHEQUE              = _ReturnCodeMeta('17', 'Crossed Cheque — Cannot Pay in Cash')
    CHEQUE_VOID                 = _ReturnCodeMeta('18', 'Cheque Void / Invalid Instrument')
    MICR_INCORRECT              = _ReturnCodeMeta('19', 'MICR Field Incorrect / Unreadable')
    IMAGE_POOR_QUALITY          = _ReturnCodeMeta('20', 'Image Not Received / Poor Quality — Resend')

    # CTS Spec Rev 3.0 additions
    # Code 88: free-text reason required in ReturnReasonComment (mandatory per spec)
    OTHER_REASON                = _ReturnCodeMeta('88', 'Other Reason')
    # Code 00: positive response for On Realization sessions (ClearingType=14) only
    ON_REALIZATION_POSITIVE     = _ReturnCodeMeta('00', 'On Realization — Positive Confirmation')
    # Code 99 (Deemed Accepted by CCH) is intentionally absent — drawee bank MUST NOT send it.
    # CCH assigns code 99 when IET expires; the bank never sends it in an RRF.

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def description(self) -> str:
        return self.value.description

    @classmethod
    def from_ui_reason(cls, ui_reason: str) -> 'RBIReturnCode':
        """Map UI-facing return reason strings to RBI codes."""
        reason = ui_reason.lower()
        if 'signature' in reason:
            return cls.SIGNATURE_DIFFERS
        if 'insufficient' in reason or 'funds' in reason:
            return cls.FUNDS_INSUFFICIENT
        if 'words' in reason and ('figure' in reason or 'differ' in reason):
            return cls.WORDS_FIGURES_DIFFER
        if 'alteration' in reason or 'tamper' in reason:
            return cls.ALTERATION_REQUIRES_AUTH
        if 'dormant' in reason or 'frozen' in reason or 'closed' in reason:
            return cls.ACCOUNT_CLOSED
        if 'post-dated' in reason or 'post dated' in reason:
            return cls.CHEQUE_POST_DATED
        if 'mutilat' in reason or 'damage' in reason or 'torn' in reason:
            return cls.CHEQUE_STALE_MUTILATED
        if 'payee' in reason and ('name' in reason or 'discrepan' in reason):
            return cls.PAYEE_ENDORSEMENT_REQUIRED
        if 'no specimen' in reason or 'cannot verify' in reason:
            return cls.REFER_TO_DRAWER
        if 'stopped' in reason:
            return cls.PAYMENT_STOPPED
        if 'micr' in reason:
            return cls.MICR_INCORRECT
        if 'image' in reason or 'quality' in reason:
            return cls.IMAGE_POOR_QUALITY
        return cls.REFER_TO_DRAWER


@dataclass
class ReturnItem:
    instrument_id: str
    micr_code: str
    return_code: RBIReturnCode
    drawee_ifsc: str
    presenting_ifsc: str
    iet_deadline: datetime
    returned_at: datetime
    decided_by: str
    amount_range: str
    bank_id: str
    workflow_id: Optional[str] = None
    return_reason_comment: Optional[str] = None

    def __post_init__(self) -> None:
        if self.return_code.code == '88':
            if not self.return_reason_comment or not self.return_reason_comment.strip():
                raise ValueError(
                    "ReturnReasonComment is mandatory when ReturnReasonCode is 88 (Other Reason). "
                    "Provide a non-empty description of the return reason."
                )

    @property
    def filed_within_iet(self) -> bool:
        return self.returned_at <= self.iet_deadline


@dataclass
class RRFDocument:
    bank_ifsc: str
    bank_id: str
    session_id: str
    clearing_zone: str
    generated_at: datetime
    returns: list[ReturnItem]

    @property
    def total_returns(self) -> int:
        return len(self.returns)
