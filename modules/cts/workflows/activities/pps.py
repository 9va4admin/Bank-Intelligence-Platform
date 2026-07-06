"""
PPS (Positive Pay System) activity — verify presented cheque details against
bank's pre-registered cheque registry stored in PPSVault.

Vault miss → HUMAN_REVIEW (invariant — never auto-return).
Amount or payee mismatch → HUMAN_REVIEW (escalate, not auto-return).
Exact match → PROCEED.
Amount tolerance: ±₹1 for floating-point rounding.
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from temporalio import activity

from shared.utils.masking import mask_amount, mask_customer_name

log = structlog.get_logger()

_AMOUNT_TOLERANCE = 1.0  # ₹1 tolerance for floating-point


class PPSActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    account_number: str
    cheque_number: str
    presented_amount: float
    presented_payee: str


class PPSActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                         # "PROCEED" | "HUMAN_REVIEW"
    mismatch_reason: Optional[str] = None


@activity.defn
async def lookup_pps(
    inp: PPSActivityInput,
    vault=None,
) -> PPSActivityResult:
    """
    Look up cheque in PPS vault and verify amount + payee match.
    Miss and mismatches always escalate to HUMAN_REVIEW.
    """
    vault_result = await vault.lookup(inp.account_number, inp.bank_id, inp.cheque_number)

    if vault_result.outcome != "FOUND":
        log.info(
            "pps_activity.vault_miss",
            instrument_id=inp.instrument_id,
            miss_reason=vault_result.miss_reason,
        )
        return PPSActivityResult(outcome="HUMAN_REVIEW", mismatch_reason=vault_result.miss_reason)

    entry = vault_result.pps_entry
    reasons = []

    registered_amount = entry.get("amount")
    if registered_amount is not None:
        if abs(inp.presented_amount - float(registered_amount)) > _AMOUNT_TOLERANCE:
            reasons.append(
                f"amount_mismatch: presented={mask_amount(inp.presented_amount)} "
                f"registered={mask_amount(float(registered_amount))}"
            )

    registered_payee = entry.get("payee", "")
    if registered_payee and inp.presented_payee.strip().lower() != registered_payee.strip().lower():
        reasons.append(
            f"payee_mismatch: presented={mask_customer_name(inp.presented_payee)} "
            f"registered={mask_customer_name(registered_payee)}"
        )

    if reasons:
        log.info(
            "pps_activity.mismatch",
            instrument_id=inp.instrument_id,
            reasons=reasons,
        )
        return PPSActivityResult(outcome="HUMAN_REVIEW", mismatch_reason="; ".join(reasons))

    return PPSActivityResult(outcome="PROCEED")
