"""
Decision activity — synthesise terminal CTS decision from all upstream signals.

Decisions: STP_CONFIRM | STP_RETURN | HUMAN_REVIEW

Priority order (hard gates evaluated first):
  0. Kill switch active (KP or KC) → HUMAN_REVIEW  [RBI mandate — supersedes ALL gates]
  1. CBS returned RETURN status     → STP_RETURN  (OPA Layer 4 rule)
  2. Alteration detected            → STP_RETURN
  3. Fraud score > threshold        → HUMAN_REVIEW
  4. OCR confidence < threshold     → HUMAN_REVIEW
  5. Signature match < threshold    → HUMAN_REVIEW
  6. CBS unavailable                → HUMAN_REVIEW
  7. PPS miss                       → HUMAN_REVIEW
  8. CBS HUMAN_REVIEW escalation    → HUMAN_REVIEW
  9. All signals clean + fraud_score < (1 - stp_threshold) → STP_CONFIRM
  else                               → HUMAN_REVIEW

Kill-switch backstop (dual-checkpoint pattern):
  This activity is checkpoint 2. It re-evaluates kill_switch_status independently,
  catching the 120s mid-flight race: kill switch activated after detect_alteration
  started but before decision reached. alteration result may carry kill_switch_mode="NONE"
  yet decision receives kill_switch_status=KP|KC — backstop catches this case.

All thresholds from config dict — never hardcoded.
SHAP values passed through from upstream fraud activity.
"""
from datetime import date
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from temporalio import activity

from modules.cts.compliance.models import (
    NON_CUSTOMER_FAULT_CODES,
    RE_PRESENTATION_CODES,
    is_customer_fault,
)
from modules.cts.workflows.activities.amount_words_parser import parse_amount_words
from shared.utils.masking import mask_amount
from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillSwitchStatus
from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.opa_client import OPAClient, OPAInput

log = structlog.get_logger()

# Maps CBS-reported return reasons to URRBCH codes.
# CBS connectors (Finacle/BaNCS/FlexCube) report bank-internal reason strings;
# this mapping normalises them to the universal NPCI clearing codes.
_CBS_REASON_TO_RETURN_CODE: dict[str, str] = {
    "NSF":                  "01",  # insufficient funds
    "INSUFFICIENT_FUNDS":   "01",
    "EXCEEDS_ARRANGEMENT":  "02",
    "STOP_PAYMENT":         "20",
    "PAYMENT_STOPPED":      "05",
    "ACCOUNT_CLOSED":       "10",
    "ACCOUNT_DOES_NOT_EXIST": "11",
    "ACCOUNT_TRANSFERRED":  "09",
    "ACCOUNT_FROZEN":       "55",
    "ACCOUNT_BLOCKED":      "55",
    "DRAWER_DECEASED":      "07",
    "INSOLVENCY":           "08",
}
_DEFAULT_CBS_RETURN_CODE = "01"  # insufficient funds as safe fallback


def _cbs_reason_to_return_code(cbs_reason: Optional[str]) -> str:
    if not cbs_reason:
        return _DEFAULT_CBS_RETURN_CODE
    return _CBS_REASON_TO_RETURN_CODE.get(cbs_reason.upper(), _DEFAULT_CBS_RETURN_CODE)


class DecisionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    smb_id: Optional[str] = None           # populated for sub-member bank instruments
    fraud_score: float
    ocr_confidence: float
    signature_match_score: float
    cbs_outcome: str            # "PROCEED" | "RETURN" | "HUMAN_REVIEW" | "CBS_UNAVAILABLE"
    cbs_return_reason: Optional[str] = None  # "NSF" | "STOP_PAYMENT" | "ACCOUNT_FROZEN" | etc.
    alteration_detected: bool
    altered_fields: list[str] = []          # which fields were altered (from alteration activity)
    pps_outcome: str            # "FOUND" | "HUMAN_REVIEW"
    available_balance: Optional[float]
    cheque_amount: float
    shap_values: dict[str, Any]  # required — must be computed before decision
    cheque_date: Optional[date] = None      # extracted by OCR; None = undated cheque
    amount_figures: Optional[float] = None  # amount as numeric digits (OCR extracted)
    amount_words: Optional[str] = None      # amount in words text (OCR extracted)
    kill_switch_mode: str = "NONE"          # carried from alteration result
    kill_switch_scope: Optional[str] = None  # carried from alteration result


class DecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    decision: str               # "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    rationale: str
    shap_values: dict[str, Any]
    kill_switch_mode: str = "NONE"          # effective mode at decision time
    kill_switch_scope: Optional[str] = None  # effective scope at decision time
    # URRBCH return reason (set only on STP_RETURN — None for CONFIRM/HUMAN_REVIEW)
    return_reason_code: Optional[str] = None
    # False = bank must NOT levy return charges (non-customer-fault codes per RBI/NPCI)
    is_customer_fault: Optional[bool] = None
    # True = re-present in next clearing within 24h (technical returns per CCPs)
    requires_re_presentation: bool = False


@activity.defn
async def synthesise_decision(
    inp: DecisionInput,
    config: dict[str, Any],
    kill_switch_status: Optional[KillSwitchStatus] = None,
    immudb_client: Optional[Any] = None,
    hsm: Optional[Any] = None,
    opa_client: Optional[OPAClient] = None,
) -> DecisionResult:
    """
    Synthesise terminal cheque decision from all upstream activity signals.
    All thresholds read from config dict — never hardcoded here.

    kill_switch_status is the freshly-resolved kill switch state at decision time.
    It acts as a backstop independent of what alteration.py saw — catching the
    mid-flight race condition where the kill switch was activated during the
    120-second Qwen2-VL call.
    """
    # ── Kill-switch backstop (checkpoint 2 — dual-checkpoint pattern) ─────────
    # Evaluated FIRST — before CBS, alteration, fraud, and all other gates.
    # RBI mandate: when kill switch is active, every instrument goes to human review.
    # KP: Vision AI ran but STP is suppressed.
    # KC: Vision AI was skipped upstream and STP is suppressed.
    effective_ks_mode = "NONE"
    effective_ks_scope: Optional[str] = None

    if kill_switch_status is not None and kill_switch_status.is_active:
        effective_ks_mode = kill_switch_status.mode.value
        effective_ks_scope = kill_switch_status.scope.value if kill_switch_status.scope else None

        log.warning(
            "decision_activity.kill_switch_backstop",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            smb_id=inp.smb_id,
            kill_switch_mode=effective_ks_mode,
            kill_switch_scope=effective_ks_scope,
            upstream_kill_switch_mode=inp.kill_switch_mode,
        )

        # Write immutable per-instrument audit record before returning
        if immudb_client is not None and hsm is not None:
            try:
                audit_ev = AuditEvent(
                    event_type=AuditEventType.CTS_KILL_SWITCH_APPLIED,
                    bank_id=inp.bank_id,
                    payload={
                        "instrument_id": inp.instrument_id,
                        "kill_switch_mode": effective_ks_mode,
                        "kill_switch_scope": effective_ks_scope,
                        "smb_id": inp.smb_id,
                        "checkpoint": "decision_backstop",
                    },
                )
                signed = audit_ev.sign(hsm)
                await immudb_client.write_event(signed.to_json())
            except Exception as exc:
                log.error(
                    "decision_activity.immudb_write_failed",
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    error=str(exc),
                )

        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="HUMAN_REVIEW",
            rationale=f"kill_switch active: mode={effective_ks_mode} scope={effective_ks_scope}",
            shap_values=inp.shap_values,
            kill_switch_mode=effective_ks_mode,
            kill_switch_scope=effective_ks_scope,
        )
    # ── End kill-switch backstop ───────────────────────────────────────────────

    # ── OPA Layer 4 policy evaluation ─────────────────────────────────────────
    # Evaluates bank-configurable Rego business rules that cannot be expressed
    # as numeric thresholds: government cheques, court orders, high-value first-day, etc.
    # OPA unavailable → safe default PROCEED (existing gates below still apply).
    if opa_client is not None:
        opa_input = OPAInput(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            cheque_type=getattr(inp, "cheque_type", "STANDARD"),
            amount=inp.cheque_amount,
            account_status=inp.cbs_outcome,
            is_first_clearing_day=getattr(inp, "is_first_clearing_day", False),
            has_government_flag=getattr(inp, "has_government_flag", False),
            has_court_order_flag=getattr(inp, "has_court_order_flag", False),
        )
        opa_result = await opa_client.decide(opa_input)
        if opa_result.decision == "HUMAN_REVIEW":
            log.info(
                "decision_activity.opa_human_review",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                opa_reason=opa_result.reason,
            )
            return DecisionResult(
                instrument_id=inp.instrument_id,
                decision="HUMAN_REVIEW",
                rationale=f"OPA policy: {opa_result.reason}",
                shap_values=inp.shap_values,
            )
        if opa_result.decision == "AUTO_RETURN":
            log.info(
                "decision_activity.opa_auto_return",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                opa_reason=opa_result.reason,
            )
            return DecisionResult(
                instrument_id=inp.instrument_id,
                decision="STP_RETURN",
                rationale=f"OPA policy: {opa_result.reason}",
                shap_values=inp.shap_values,
            )
    # ── End OPA evaluation ────────────────────────────────────────────────────

    stp_threshold: float = config["stp_auto_confirm_threshold"]
    fraud_threshold: float = config["human_review_fraud_threshold"]
    ocr_min_confidence: float = config["ocr_min_confidence"]
    sig_min_match: float = config["sig_min_match_score"]
    validity_days: int = int(config.get("cheque_validity_days", 90))

    # ── Hard gate 0: Cheque date validity ─────────────────────────────────
    # Evaluated before CBS / alteration — objective date facts need no AI.
    # All three CCP provisions: post-dated=30, stale=31, undated=32.
    today = date.today()
    if inp.cheque_date is None:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale="Undated cheque",
            shap_values=inp.shap_values,
            return_reason_code="32",
            is_customer_fault=is_customer_fault("32"),
        )
    if inp.cheque_date > today:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale=f"Post-dated cheque — cheque date {inp.cheque_date} is in the future",
            shap_values=inp.shap_values,
            return_reason_code="30",
            is_customer_fault=is_customer_fault("30"),
        )
    if (today - inp.cheque_date).days > validity_days:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale=f"Stale cheque — {(today - inp.cheque_date).days} days old (limit {validity_days})",
            shap_values=inp.shap_values,
            return_reason_code="31",
            is_customer_fault=is_customer_fault("31"),
        )

    # ── Hard gate 0.5: Amount in words vs figures cross-check ─────────────
    # Applies when OCR extracted both fields. Mismatch = URRBCH code 34.
    if inp.amount_words and inp.amount_figures is not None:
        parsed_words_amount = parse_amount_words(inp.amount_words)
        if parsed_words_amount is not None:
            tolerance = 1.0  # ₹1 floating-point tolerance
            if abs(parsed_words_amount - inp.amount_figures) > tolerance:
                return DecisionResult(
                    instrument_id=inp.instrument_id,
                    decision="STP_RETURN",
                    rationale=(
                        f"Amount in words/figures differ: "
                        f"words={mask_amount(parsed_words_amount)} "
                        f"figures={mask_amount(inp.amount_figures)}"
                    ),
                    shap_values=inp.shap_values,
                    return_reason_code="34",
                    is_customer_fault=is_customer_fault("34"),
                )

    # ── Hard gate 1: CBS says return immediately ───────────────────────────
    if inp.cbs_outcome == "RETURN":
        rrc = _cbs_reason_to_return_code(inp.cbs_return_reason)
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale=f"CBS account status requires return: {inp.cbs_return_reason or 'unspecified'}",
            shap_values=inp.shap_values,
            return_reason_code=rrc,
            is_customer_fault=is_customer_fault(rrc),
        )

    # ── Hard gate 2: CTS alteration specificity ────────────────────────────
    # Non-date field alterations = CTS code 85 (auto-return, no human review needed).
    # Date-field only = human review (bank policy decision per CCPs).
    non_date_altered = [f for f in inp.altered_fields if f != "date"]
    if non_date_altered:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_RETURN",
            rationale=f"CTS alteration in non-date fields: {non_date_altered}",
            shap_values=inp.shap_values,
            return_reason_code="85",
            is_customer_fault=is_customer_fault("85"),
        )
    # Soft gates → HUMAN_REVIEW
    human_review_reasons = []

    if inp.alteration_detected and not non_date_altered:
        human_review_reasons.append("date_field_alteration_detected")

    if inp.fraud_score >= fraud_threshold:
        human_review_reasons.append(f"fraud_score={inp.fraud_score:.3f} >= threshold={fraud_threshold}")

    if inp.ocr_confidence < ocr_min_confidence:
        human_review_reasons.append(f"ocr_confidence={inp.ocr_confidence:.3f} below minimum")

    if inp.signature_match_score < sig_min_match:
        human_review_reasons.append(f"signature_match={inp.signature_match_score:.3f} below minimum")

    if inp.cbs_outcome in ("CBS_UNAVAILABLE", "HUMAN_REVIEW"):
        human_review_reasons.append(f"cbs_outcome={inp.cbs_outcome}")

    if inp.pps_outcome == "HUMAN_REVIEW":
        human_review_reasons.append("pps_miss")

    if human_review_reasons:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="HUMAN_REVIEW",
            rationale="; ".join(human_review_reasons),
            shap_values=inp.shap_values,
        )

    # STP_CONFIRM: all signals clean, fraud score below threshold, OCR+sig above minimums.
    # STP gate measures quality of extraction (OCR) and identity (signature).
    # Fraud already filtered above; don't penalize again here.
    combined_confidence = inp.ocr_confidence * 0.5 + inp.signature_match_score * 0.5

    if combined_confidence >= stp_threshold:
        return DecisionResult(
            instrument_id=inp.instrument_id,
            decision="STP_CONFIRM",
            rationale=(
                f"All signals clean: fraud_score={inp.fraud_score:.3f}, "
                f"ocr={inp.ocr_confidence:.3f}, sig={inp.signature_match_score:.3f}, "
                f"combined_confidence={combined_confidence:.3f}"
            ),
            shap_values=inp.shap_values,
        )

    return DecisionResult(
        instrument_id=inp.instrument_id,
        decision="HUMAN_REVIEW",
        rationale=f"Combined confidence {combined_confidence:.3f} below STP threshold {stp_threshold}",
        shap_values=inp.shap_values,
    )
