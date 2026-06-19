from enum import Enum

from .models import SubMemberBank, SubMemberBatchLedger


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
