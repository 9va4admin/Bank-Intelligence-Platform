# CTS Cheque Routing Policy — Layer 4 (Business Policy Rules)
# ─────────────────────────────────────────────────────────────────────
# This policy determines routing for CTS cheque processing.
# Edited via Admin UI by compliance_officer, approved by bank_it_admin.
# OPA hot-reloads this bundle — no pod restart required on policy change.
# ─────────────────────────────────────────────────────────────────────
package astra.cts.routing

import future.keywords.if
import future.keywords.in

# ── Mandatory Human Review Triggers ──────────────────────────────────
# Any cheque matching these conditions goes to human review
# regardless of AI fraud score or STP threshold.

requires_human_review if {
    input.cheque.drawer_category == "GOVERNMENT"
}

requires_human_review if {
    input.cheque.drawer_category == "COURT_ORDER"
}

requires_human_review if {
    input.cheque.amount > input.config.high_value_amount_threshold
    input.cheque.clearing_day == 1   # first clearing day of the month
}

requires_human_review if {
    input.vault.signature_found == false   # vault miss — never auto-return
}

requires_human_review if {
    input.vault.pps_found == false         # PPS vault miss — never auto-return
}

requires_human_review if {
    input.cbs.account_status == "FROZEN"   # escalate, do not auto-return
}

# ── Mandatory Auto-Return Triggers ───────────────────────────────────
# These override STP threshold — auto-return without human review.
# Use sparingly — only for unambiguous objective conditions.

requires_auto_return if {
    input.cbs.account_status == "CLOSED"
}

requires_auto_return if {
    input.cheque.stale == true    # cheque date > 3 months
}

# ── STP Decision ─────────────────────────────────────────────────────
# Straight-through processing: auto-confirm if score meets threshold
# and no override rules triggered above.

stp_confirm if {
    not requires_human_review
    not requires_auto_return
    input.fraud_score.value <= input.config.stp_auto_confirm_threshold
}

stp_return if {
    not requires_human_review
    not requires_auto_return
    input.fraud_score.value > input.config.stp_auto_confirm_threshold
    input.fraud_score.value <= input.config.human_review_fraud_threshold
    input.cheque.amount < input.config.high_value_amount_threshold
}

# ── Final Decision ───────────────────────────────────────────────────
decision := "HUMAN_REVIEW" if { requires_human_review }
decision := "STP_RETURN"   if { requires_auto_return }
decision := "STP_CONFIRM"  if { stp_confirm }
decision := "STP_RETURN"   if { stp_return }
decision := "HUMAN_REVIEW" if {    # fallback — never default to STP
    not stp_confirm
    not stp_return
    not requires_auto_return
}
