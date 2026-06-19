from enum import Enum
from typing import Optional

from .models import SubMemberBank, SubMemberBatchLedger, SubMemberReturn


class NotificationTier(Enum):
    TIER1_IMMEDIATE = "TIER1_IMMEDIATE"       # Per-cheque rejection → branch manager
    TIER2_BATCH_SUMMARY = "TIER2_BATCH_SUMMARY"  # End-of-session summary → BM + ops head
    TIER3_GM_ESCALATION = "TIER3_GM_ESCALATION"  # Return rate breach → GM


class BatchRejectionEmailer:
    """
    Builds email payloads for sub-member bank rejection notifications.
    Returns a dict describing the email to be dispatched.
    Actual sending is delegated to shared/notifications/dispatcher.py via Kafka.

    PII rules:
    - Never include exact cheque amounts — use amount_range only
    - Never include full account numbers — use last-4 suffix only
    - Customer contact is OUT OF SCOPE — handled externally via Kafka webhook
    """

    def send_tier1_immediate(
        self, sub_member: SubMemberBank, return_item: SubMemberReturn
    ) -> dict:
        """Immediate single-cheque rejection notification to branch manager."""
        subject = (
            f"[ASTRA CTS] Cheque Return — {sub_member.bank_name} | "
            f"Ref ...{return_item.cheque_number_suffix}"
        )
        body = self._tier1_body(sub_member, return_item)
        return {
            "tier": NotificationTier.TIER1_IMMEDIATE.value,
            "to": sub_member.branch_manager_email,
            "cc": [],
            "subject": subject,
            "body": body,
            "status": "QUEUED",
            "attachment_type": None,
        }

    def send_tier2_batch_summary(
        self,
        sub_member: SubMemberBank,
        ledger: SubMemberBatchLedger,
        returns: list[SubMemberReturn],
    ) -> dict:
        """End-of-session batch summary with CSV attachment to branch manager + ops head."""
        subject = (
            f"[ASTRA CTS] Session Summary — {sub_member.bank_name} "
            f"| {ledger.clearing_session} {ledger.session_date}"
        )
        body = self._tier2_body(sub_member, ledger, returns)
        return {
            "tier": NotificationTier.TIER2_BATCH_SUMMARY.value,
            "to": sub_member.branch_manager_email,
            "cc": [sub_member.ops_head_email],
            "subject": subject,
            "body": body,
            "status": "QUEUED",
            "attachment_type": "CSV",
        }

    def send_tier3_gm_alert(
        self, sub_member: SubMemberBank, ledger: SubMemberBatchLedger
    ) -> dict:
        """Return rate threshold breach escalation to GM — aggregate only, no cheque details."""
        return_pct = ledger.return_rate * 100
        subject = (
            f"[ASTRA CTS ALERT] High Return Rate — {sub_member.bank_name} "
            f"| {return_pct:.2f}% | Immediate Action Required"
        )
        body = self._tier3_body(sub_member, ledger)
        return {
            "tier": NotificationTier.TIER3_GM_ESCALATION.value,
            "to": sub_member.gm_email,
            "cc": [sub_member.ops_head_email],
            "subject": subject,
            "body": body,
            "status": "QUEUED",
            "priority": "HIGH",
            "attachment_type": None,
        }

    # ── Private body builders ─────────────────────────────────────────────

    def _tier1_body(self, smb: SubMemberBank, r: SubMemberReturn) -> str:
        return (
            f"Dear Branch Manager,\n\n"
            f"A cheque presented by {smb.bank_name} has been returned.\n\n"
            f"  Reference (last 4): ...{r.cheque_number_suffix}\n"
            f"  Return Reason     : {r.return_reason}\n"
            f"  Amount Range      : {r.amount_range}\n"
            f"  Returned At       : {r.returned_at.strftime('%Y-%m-%d %H:%M:%S')} IST\n"
            f"  Clearing Bucket   : {r.bucket.value}\n\n"
            f"Please advise your customer to re-present with corrections.\n\n"
            f"Regards,\nASTRA CTS — Automated Clearing Intelligence"
        )

    def _tier2_body(
        self, smb: SubMemberBank, ledger: SubMemberBatchLedger, returns: list[SubMemberReturn]
    ) -> str:
        return_pct = ledger.return_rate * 100
        stp_pct = ledger.stp_rate * 100
        rows = "\n".join(
            f"  ...{r.cheque_number_suffix}  |  {r.return_reason}  |  {r.amount_range}"
            for r in returns
        )
        return (
            f"Dear Branch Manager,\n\n"
            f"Session summary for {smb.bank_name} — {ledger.clearing_session} {ledger.session_date}\n\n"
            f"BUCKET BREAKDOWN\n"
            f"  STP Pass       : {ledger.stp_pass} ({stp_pct:.2f}%)\n"
            f"  STP Return     : {ledger.stp_return} ({return_pct:.2f}%)\n"
            f"  Eyeball Queue  : {ledger.eyeball}\n"
            f"  Fraud Hold     : {ledger.fraud_hold}\n"
            f"  IET Emergency  : {ledger.iet_emergency}\n"
            f"  TOTAL          : {ledger.total_received}\n\n"
            f"RETURN DETAILS (CSV attached)\n"
            f"{rows}\n\n"
            f"Please review the attached CSV for full return list.\n\n"
            f"Regards,\nASTRA CTS — Automated Clearing Intelligence"
        )

    def _tier3_body(self, smb: SubMemberBank, ledger: SubMemberBatchLedger) -> str:
        return_pct = ledger.return_rate * 100
        threshold_pct = smb.return_rate_threshold * 100
        return (
            f"Dear GM,\n\n"
            f"RETURN RATE ALERT — {smb.bank_name}\n\n"
            f"  Current Return Rate : {return_pct:.2f}%\n"
            f"  Configured Threshold: {threshold_pct:.2f}%\n"
            f"  Session             : {ledger.clearing_session} {ledger.session_date}\n"
            f"  Total Instruments   : {ledger.total_received}\n"
            f"  Total Returns       : {ledger.stp_return}\n\n"
            f"Immediate review and corrective action is required.\n"
            f"Contact your Ops Head and Branch Manager for details.\n\n"
            f"Regards,\nASTRA CTS — Automated Clearing Intelligence"
        )
