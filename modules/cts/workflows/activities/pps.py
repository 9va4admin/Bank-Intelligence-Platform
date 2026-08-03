"""
PPS (Positive Pay System) activity — verify presented cheque details against
bank's pre-registered cheque registry stored in PPSVault.

5-flag NPCI decision tree (Karnataka Bank Section 8, universal NPCI mandate):
  P — Positive match → PROCEED
  D — Duplicate presentation → AUTO_RETURN (URRBCH code 41, not customer fault)
  Y — Financial mismatch → HUMAN_REVIEW (financial reason outranks PPS reason)
  Z — Data not available → check pps_mandatory_threshold from config:
       amount >= threshold → HUMAN_REVIEW (PPS_MANDATORY_MISSING)
       amount <  threshold → PROCEED
  N — Not registered (issuer opted out) → PROCEED

Vault miss: same routing as flag Z — threshold check.
Old match logic (no NPCI flag in vault): falls back to amount/payee comparison.
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from temporalio import activity

from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
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
    outcome: str                              # "PROCEED" | "HUMAN_REVIEW" | "AUTO_RETURN"
    npci_flag: Optional[str] = None           # P | D | Y | Z | N (from vault entry)
    return_reason_code: Optional[str] = None  # URRBCH code (set on AUTO_RETURN)
    is_customer_fault: Optional[bool] = None  # None = N/A (no return); False = bank/system
    mismatch_reason: Optional[str] = None
    financial_reason_takes_priority: bool = False  # True for flag Y — downstream decision uses this


def _is_customer_fault(code: str) -> bool:
    return code not in NON_CUSTOMER_FAULT_CODES


def _threshold_route(presented_amount: float, config: dict[str, Any]) -> PPSActivityResult:
    """
    Shared routing for flag Z and vault miss:
    amount >= mandatory_threshold → HUMAN_REVIEW; below → PROCEED.
    Threshold from config (Layer 3) — never hardcoded.
    """
    mandatory_threshold: float = config.get("pps_mandatory_threshold", 500000.0)
    if presented_amount >= mandatory_threshold:
        return PPSActivityResult(
            outcome="HUMAN_REVIEW",
            mismatch_reason="PPS_MANDATORY_MISSING",
        )
    return PPSActivityResult(outcome="PROCEED")


@activity.defn
async def lookup_pps(
    inp: PPSActivityInput,
    vault,
    config: Optional[dict[str, Any]] = None,
) -> PPSActivityResult:
    """
    Look up cheque in PPS vault and apply 5-flag NPCI decision tree.
    config must provide 'pps_mandatory_threshold' (Layer 3 — bank-configurable).
    """
    if config is None:
        config = {}

    vault_result = await vault.lookup(inp.account_number, inp.bank_id, inp.cheque_number)

    if vault_result.outcome != "FOUND":
        log.info(
            "pps_activity.vault_miss",
            instrument_id=inp.instrument_id,
            miss_reason=vault_result.miss_reason,
        )
        return _threshold_route(inp.presented_amount, config)

    entry = vault_result.pps_entry
    npci_flag: Optional[str] = entry.get("npci_flag")

    # ── 5-flag NPCI decision tree ──────────────────────────────────────────
    if npci_flag == "P":
        return PPSActivityResult(outcome="PROCEED", npci_flag="P")

    if npci_flag == "D":
        code = "41"
        return PPSActivityResult(
            outcome="AUTO_RETURN",
            npci_flag="D",
            return_reason_code=code,
            is_customer_fault=_is_customer_fault(code),
        )

    if npci_flag == "Y":
        return PPSActivityResult(
            outcome="HUMAN_REVIEW",
            npci_flag="Y",
            financial_reason_takes_priority=True,
            mismatch_reason="PPS_FINANCIAL_MISMATCH",
        )

    if npci_flag == "Z":
        result = _threshold_route(inp.presented_amount, config)
        return PPSActivityResult(
            outcome=result.outcome,
            npci_flag="Z",
            mismatch_reason=result.mismatch_reason,
        )

    if npci_flag == "N":
        return PPSActivityResult(outcome="PROCEED", npci_flag="N")

    # ── Legacy path: no NPCI flag in vault entry — use amount/payee match ─
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
