from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

from modules.cts.compliance.models import is_customer_fault as _is_customer_fault
from .models import SubMemberBank, SubMemberBatchLedger

log = structlog.get_logger()


# ── Sponsor settlement position models ────────────────────────────────────────

@dataclass(frozen=True)
class SponsorBatchInfo:
    """Batch summary passed to SponsorSettlementShield before forwarding to NGCH."""
    sub_member_id: str
    sponsor_bank_id: str
    batch_total_amount: float
    instrument_count: int


@dataclass(frozen=True)
class SettlementShieldResult:
    """Result of the settlement position check."""
    status: str                           # "PROCEED" | "BLOCK" | "ESCALATE"
    sub_member_id: str = ""
    return_reason_code: Optional[str] = None   # "25" on BLOCK; None otherwise
    is_customer_fault: Optional[bool] = None   # False on BLOCK; None on PROCEED/ESCALATE


class SponsorSettlementShield:
    """
    Checks whether an SMB's settlement account at the sponsor bank has sufficient
    funds before forwarding the SMB batch to NGCH.

    URRBCH code 25: SMB_SPONSOR_FUNDS_INSUFFICIENT
      - Not customer fault (bank-side settlement failure)
      - Instruments must be returned to the presenting bank with code 25
      - Per Karnataka Bank CCP Section 9, PNB Section 7

    Outcomes:
      PROCEED   — balance >= batch total; batch forwarding may continue
      BLOCK     — balance <  batch total; all instruments returned with code 25
      ESCALATE  — CBS unavailable; hand to ops for manual resolution
    """

    async def check(
        self,
        batch: SponsorBatchInfo,
        cbs,
    ) -> SettlementShieldResult:
        """
        Query CBS for SMB's settlement account balance at the sponsor bank.
        CBS connector must expose get_smb_settlement_balance(sub_member_id, sponsor_bank_id).
        """
        try:
            balance: float = await cbs.get_smb_settlement_balance(
                batch.sub_member_id,
                batch.sponsor_bank_id,
            )
        except Exception as exc:
            log.warning(
                "sponsor_settlement_shield.cbs_unavailable",
                sub_member_id=batch.sub_member_id,
                sponsor_bank_id=batch.sponsor_bank_id,
                error=str(exc),
            )
            return SettlementShieldResult(
                status="ESCALATE",
                sub_member_id=batch.sub_member_id,
            )

        if balance < batch.batch_total_amount:
            log.warning(
                "sponsor_settlement_shield.insufficient",
                sub_member_id=batch.sub_member_id,
                instrument_count=batch.instrument_count,
            )
            return SettlementShieldResult(
                status="BLOCK",
                sub_member_id=batch.sub_member_id,
                return_reason_code="25",
                is_customer_fault=_is_customer_fault("25"),
            )

        return SettlementShieldResult(
            status="PROCEED",
            sub_member_id=batch.sub_member_id,
        )


class ShieldStatus(Enum):
    SAFE = "SAFE"             # Return rate within acceptable bounds
    SOFT_HOLD = "SOFT_HOLD"  # Return rate above threshold — pause remaining STP items
    HARD_STOP = "HARD_STOP"  # Return rate critically high — all items to human review


class ReturnRateShield:
    """
    Evaluates mid-session return rate for a sub-member bank and determines
    whether to apply a soft-hold or hard-stop on remaining STP items.

    Thresholds (per SubMemberBank config — never hardcoded):
      return_rate_threshold: warn boundary (default 15%)
      soft_hold_threshold:   hold boundary (default 25%)
      hard_stop = 2× soft_hold_threshold

    Lodging all remaining items to human EYEBALL when soft_hold is active prevents
    a rogue batch from exceeding the sponsor bank's return-rate exposure.
    """

    def check(self, ledger: SubMemberBatchLedger, sub_member: SubMemberBank) -> ShieldStatus:
        rate = ledger.return_rate
        hard_stop_threshold = sub_member.soft_hold_threshold * 2

        if rate >= hard_stop_threshold:
            return ShieldStatus.HARD_STOP
        if rate >= sub_member.soft_hold_threshold:
            return ShieldStatus.SOFT_HOLD
        return ShieldStatus.SAFE

    def apply(self, ledger: SubMemberBatchLedger, sub_member: SubMemberBank) -> ShieldStatus:
        """Check and mutate ledger if shield is active."""
        status = self.check(ledger, sub_member)
        if status in (ShieldStatus.SOFT_HOLD, ShieldStatus.HARD_STOP):
            ledger.soft_hold_active = True
        return status
