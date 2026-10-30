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
from shared.messages import get_message


@dataclass(frozen=True)
class _ReturnCodeMeta:
    code: str
    description: str


class RBIReturnCode(Enum):
    """
    Return reason codes a DRAWEE bank may send in a Return Request File.

    Source of truth: RBI/NPCI CTS Specifications for Continuous Clearing, Rev 3.0 (26 Mar 2025), Appendix DD / section 4.5.3.3.1, verified
    2026-10-14 and held as data in docs/npci/return_reason_codes.json (a conformance test pins this table to it).
    An earlier version of this table invented codes ('06' signature differs, '14' post-dated, '15' stale,
    '16' words/figures, '20' image quality ...); those were wrong and would have put a wrong legal reason on a return.
    Only the codes ASTRA can actually decide are listed; code 99 (Deemed Accepted) is assigned by the clearing house
    and a drawee bank must never send it.
    """
    # 01-05 funds / reference to drawer
    FUNDS_INSUFFICIENT          = _ReturnCodeMeta('01', get_message("UI_DECISIONSLOG_FUNDS_INSUFFICIENT"))
    EXCEED_ARRANGEMENT          = _ReturnCodeMeta('02', get_message("CTS_EXCEEDS_ARRANGEMENT"))
    EFFECTS_NOT_CLEARED         = _ReturnCodeMeta('03', get_message("CTS_EFFECTS_NOT_CLEARED_PRESENT_AGAIN"))
    REFER_TO_DRAWER             = _ReturnCodeMeta('04', get_message("UI_DECISIONSLOG_REFER_TO_DRAWER"))
    CONTACT_DRAWER_OR_DRAWEE    = _ReturnCodeMeta('05', get_message("CTS_KINDLY_CONTACT_DRAWER_DRAWEE_BANK"))
    # 10-17 signature
    SIGNATURE_INCOMPLETE        = _ReturnCodeMeta('10', get_message("UI_RETURNREASONS_DRAWER_S_SIGNATURE_INCOMPLETE"))
    SIGNATURE_ILLEGIBLE         = _ReturnCodeMeta('11', get_message("UI_RETURNREASONS_DRAWER_S_SIGNATURE_ILLEGIBLE"))
    SIGNATURE_DIFFERS           = _ReturnCodeMeta('12', get_message("CTS_DRAWER_S_SIGNATURE_DIFFERS"))
    SIGNATURE_REQUIRED          = _ReturnCodeMeta('13', get_message("UI_RETURNREASONS_DRAWER_S_SIGNATURE_REQUIRED"))
    ALTERATION_REQUIRES_AUTH    = _ReturnCodeMeta('17', get_message("CTS_ALTERATION_REQUIRES_DRAWER_S_AUTHENT"))
    # 20-25 stop payment
    PAYMENT_STOPPED             = _ReturnCodeMeta('20', get_message("UI_RETURNREASONS_PAYMENT_STOPPED_BY_DRAWER"))
    STOPPED_ATTACHMENT_ORDER    = _ReturnCodeMeta('21', get_message("CTS_PAYMENT_STOPPED_BY_ATTACHMENT_ORDER"))
    STOPPED_COURT_ORDER         = _ReturnCodeMeta('22', get_message("CTS_PAYMENT_STOPPED_BY_COURT_ORDER"))
    DRAWER_DECEASED             = _ReturnCodeMeta('23', get_message("CTS_WITHDRAWAL_STOPPED_OWING_TO_DEATH"))
    DRAWER_LUNACY               = _ReturnCodeMeta('24', get_message("CTS_WITHDRAWAL_STOPPED_OWING_TO_LUNACY"))
    DRAWER_INSOLVENT            = _ReturnCodeMeta('25', get_message("CTS_WITHDRAWAL_STOPPED_OWING_TO_INSOLVEN"))
    # 30-42 instrument
    CHEQUE_POST_DATED           = _ReturnCodeMeta('30', get_message("CTS_INSTRUMENT_POST_DATED"))
    CHEQUE_STALE                = _ReturnCodeMeta('31', get_message("CTS_INSTRUMENT_OUT_DATED_STALE"))
    CHEQUE_UNDATED              = _ReturnCodeMeta('32', get_message("CTS_INSTRUMENT_UNDATED_WITHOUT_PROPER_DA"))
    CHEQUE_MUTILATED            = _ReturnCodeMeta('33', get_message("CTS_INSTRUMENT_MUTILATED_REQUIRES_BANK_S"))
    WORDS_FIGURES_DIFFER        = _ReturnCodeMeta('34', get_message("CTS_CHEQUE_IRREGULARLY_DRAWN_AMOUNT_IN"))
    NOT_DRAWN_ON_US             = _ReturnCodeMeta('36', get_message("CTS_WRONGLY_DELIVERED_NOT_DRAWN_ON"))
    EXTRANEOUS_MATTER           = _ReturnCodeMeta('38', get_message("UI_RETURNREASONS_INSTRUMENT_CONTAINS_EXTRANEOUS_MATTE"))
    IMAGE_NOT_CLEAR             = _ReturnCodeMeta('39', get_message("CTS_IMAGE_NOT_CLEAR_PRESENT_AGAIN"))
    PRESENT_WITH_DOCUMENT       = _ReturnCodeMeta('40', get_message("UI_RETURNREASONS_PRESENT_WITH_DOCUMENT"))
    ITEM_LISTED_TWICE           = _ReturnCodeMeta('41', get_message("UI_RETURNREASONS_ITEM_LISTED_TWICE"))
    # 50-55 account
    ACCOUNT_CLOSED              = _ReturnCodeMeta('50', get_message("UI_RETURNREASONS_ACCOUNT_CLOSED"))
    NO_SUCH_ACCOUNT             = _ReturnCodeMeta('52', get_message("UI_RETURNREASONS_NO_SUCH_ACCOUNT"))
    ACCOUNT_BLOCKED             = _ReturnCodeMeta('55', get_message("CTS_ACCOUNT_BLOCKED_SITUATION_COVERED_IN"))
    # 60-68 crossing / endorsement
    CROSSED_TO_TWO_BANKS        = _ReturnCodeMeta('60', get_message("CTS_CROSSED_TO_TWO_BANKS"))
    PAYEE_ENDORSEMENT_REQUIRED  = _ReturnCodeMeta('66', get_message("UI_RETURNREASONS_PAYEE_S_ENDORSEMENT_REQUIRED"))
    PAYEE_ENDORSEMENT_IRREGULAR = _ReturnCodeMeta('67', get_message("CTS_PAYEE_S_ENDORSEMENT_IRREGULAR_REQUIR"))
    # 70-76 RBI / government (current numbering; the 2018 guideline used 69-75)
    REQUIRED_INFO_NOT_LEGIBLE   = _ReturnCodeMeta('76', get_message("CTS_REQUIRED_INFORMATION_NOT_LEGIBLE_COR"))
    # 80-88 miscellaneous
    DIGITAL_CERT_FAILURE        = _ReturnCodeMeta('83', get_message("UI_RETURNREASONS_DIGITAL_CERTIFICATE_VALIDATION_FAILU"))
    ALTERATION_PROHIBITED_CTS   = _ReturnCodeMeta('85', get_message("CTS_ALTERATIONS_CORRECTIONS_ON_INSTRUMEN"))
    FAKE_FORGED_STOLEN          = _ReturnCodeMeta('86', get_message("CTS_FAKE_FORGED_STOLEN_DRAFT_CHEQUE"))
    # Code 88: free-text reason; ReturnReasonComment is mandatory and must not start with a digit or a space
    OTHER_REASON                = _ReturnCodeMeta('88', get_message("CTS_OTHER_REASONS_PLEASE_SPECIFY"))
    # Code 00: positive response for On Realization sessions (ClearingType=14) only
    ON_REALIZATION_POSITIVE     = _ReturnCodeMeta('00', get_message("CTS_POSITIVE_RESPONSE"))
    # Code 99 (Deemed Accepted) is intentionally absent: the clearing house assigns it when the IET expires;
    # a drawee bank never sends it in an RRF.

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def description(self) -> str:
        return self.value.description

    @classmethod
    def from_ui_reason(cls, ui_reason: str) -> 'RBIReturnCode':
        """Map UI-facing return reason strings to clearing-house codes."""
        reason = ui_reason.lower()
        if 'signature' in reason:
            return cls.SIGNATURE_DIFFERS
        if 'insufficient' in reason or 'funds' in reason:
            return cls.FUNDS_INSUFFICIENT
        if 'words' in reason and ('figure' in reason or 'differ' in reason):
            return cls.WORDS_FIGURES_DIFFER
        if 'alteration' in reason or 'tamper' in reason:
            return cls.ALTERATION_REQUIRES_AUTH
        if 'closed' in reason:
            return cls.ACCOUNT_CLOSED
        if 'dormant' in reason or 'frozen' in reason or 'blocked' in reason:
            return cls.ACCOUNT_BLOCKED
        if 'post-dated' in reason or 'post dated' in reason:
            return cls.CHEQUE_POST_DATED
        if 'stale' in reason or 'out dated' in reason or 'outdated' in reason:
            return cls.CHEQUE_STALE
        if 'undated' in reason:
            return cls.CHEQUE_UNDATED
        if 'mutilat' in reason or 'damage' in reason or 'torn' in reason:
            return cls.CHEQUE_MUTILATED
        if 'duplicate' in reason or 'listed twice' in reason:
            return cls.ITEM_LISTED_TWICE
        if 'payee' in reason and ('name' in reason or 'discrepan' in reason):
            return cls.PAYEE_ENDORSEMENT_REQUIRED     # product decision pending: no spec code means "payee name differs"
        if 'no specimen' in reason or 'cannot verify' in reason:
            return cls.REFER_TO_DRAWER
        if 'stopped' in reason:
            return cls.PAYMENT_STOPPED
        if 'micr' in reason:
            return cls.REQUIRED_INFO_NOT_LEGIBLE
        if 'image' in reason or 'quality' in reason:
            return cls.IMAGE_NOT_CLEAR
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
            c = self.return_reason_comment
            if not c or not c.strip():
                raise ValueError(
                    get_message("CTS_RETURNREASONCOMMENT_IS_MANDATORY_WHE")
                )
            if c[0].isspace() or c[0].isdigit():
                raise ValueError(
                    get_message("CTS_RETURNREASONCOMMENT_FOR_CODE_88_MUST")
                )

    @property
    def filed_within_iet(self) -> bool:
        return self.returned_at <= self.iet_deadline


@dataclass
class RRFDocument:
    bank_ifsc: str
    bank_id: str
    session_id: str
    generated_at: datetime
    returns: list[ReturnItem]

    @property
    def total_returns(self) -> int:
        return len(self.returns)
