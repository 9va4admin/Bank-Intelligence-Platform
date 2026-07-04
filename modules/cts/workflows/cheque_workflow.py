"""
ChequeProcessingWorkflow — main CTS workflow: one cheque, one agent (drawee side).

Workflow ID: cts-{bank_id}-{instrument_id} (deterministic, exactly-once).
IETWatchdogWorkflow spawned as first child before any activity — non-negotiable.

Phase 3 activity order (drawee inward):
  detect_alteration → validate_cts2010 → stop_payment → pps
  → signature → fraud → cbs_balance → account_status → decision

Rationale:
  - OCR removed: NGCH provides MICR data; scanner not on inward side.
  - Vision LLM FIRST: trust Vision on drawee side; early tamper discard saves CBS calls.
  - account_status separated from cbs_balance: independent step, runs after balance check.
  - Human review topic: smb-scoped when instrument tagged to a sub-member bank.
"""
import time
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from modules.cts.sub_member.activities import (
    check_return_rate_shield,
    emit_batch_ledger_update,
    notify_sub_member_return,
)

log = structlog.get_logger()

_IET_EMERGENCY_BUFFER_SECONDS = 30


# ---------------------------------------------------------------------------
# Lightweight early-exit decision stubs (used when workflow short-circuits
# before the main decision activity runs)
# ---------------------------------------------------------------------------

class _EarlyDecision:
    def __init__(self, instrument_id: str, decision: str, rationale: str) -> None:
        self.instrument_id = instrument_id
        self.decision = decision
        self.rationale = rationale
        self.shap_values: dict = {}


def _make_early_human_review(instrument_id: str, reason: str) -> _EarlyDecision:
    return _EarlyDecision(instrument_id, "HUMAN_REVIEW", reason)


def _make_early_stp_return(instrument_id: str, reason: str) -> _EarlyDecision:
    return _EarlyDecision(instrument_id, "STP_RETURN", reason)


class ChequeWorkflowInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_url: str
    account_number: str
    cheque_number: str
    presented_amount: float
    presented_payee: str
    iet_deadline: float            # Unix timestamp
    smb_id: Optional[str] = None  # Phase 3: set when instrument is tagged to a sub-member bank


class ChequeWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    decision: str                  # "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    rationale: str
    shap_values: Optional[dict[str, Any]] = None
    emergency_iet_filed: bool = False
    sub_member_notified: bool = False
    ledger_updated: bool = False


class ChequeProcessingWorkflow:
    def __init__(self) -> None:
        self._watchdog_spawned: bool = False

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-{bank_id}-{instrument_id}"

    def iet_watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    def human_review_topic(self, bank_id: str, smb_id: Optional[str]) -> str:
        """Return the Kafka human-review topic. SMB-scoped when smb_id is set."""
        if smb_id:
            return f"cts.human.review.{bank_id}.{smb_id}"
        return f"cts.human.review.{bank_id}"

    async def run_with_mocks(
        self,
        inp: ChequeWorkflowInput,
        mock_results: dict,
        on_watchdog_spawn: Optional[Callable] = None,
    ) -> ChequeWorkflowResult:
        """
        Testable orchestration method: accepts pre-built activity results.
        Production Temporal @workflow.run method wraps this logic.

        Phase 3 mock_results keys (no 'ocr' — OCR removed for drawee side):
          alteration, compliance, stop_payment, pps, signature,
          fraud, cbs, account_status, decision, audit
        """
        # Step 1: Spawn IET watchdog FIRST — before any activity (non-negotiable)
        self._watchdog_spawned = False
        if on_watchdog_spawn:
            await on_watchdog_spawn(
                watchdog_id=self.iet_watchdog_id(inp.bank_id, inp.instrument_id),
                iet_deadline=inp.iet_deadline,
            )
        self._watchdog_spawned = True

        # Step 2: detect_alteration — Vision LLM FIRST on drawee side
        # Tampered cheque exits immediately — saves all downstream CBS/PPS/signature calls.
        alteration_result = mock_results["alteration"]
        if alteration_result.alteration_detected:
            log.info(
                "cheque_workflow.tampered_early_exit",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                tamper_risk=getattr(alteration_result, "tamper_risk_score", 0.0),
            )
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale="alteration_detected",
                shap_values={},
            )

        # Step 3: validate_cts2010 — image quality check on received inward image
        compliance_result = mock_results["compliance"]
        if not compliance_result.is_compliant:
            log.info(
                "cheque_workflow.cts2010_non_compliant",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                violations=compliance_result.violations,
            )
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale=f"cts2010_violation: {compliance_result.violations}",
                shap_values={},
            )

        # Step 4: Bloom filter / stop-payment pre-check
        # Bloom hit → HUMAN_REVIEW (probabilistic — may be false positive, never auto-return).
        stop_payment_result = mock_results["stop_payment"]
        if stop_payment_result.outcome == "STP_RETURN":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"Stop payment: {stop_payment_result.stop_reason}",
                shap_values={},
            )
        if stop_payment_result.outcome == "HUMAN_REVIEW":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale=f"Stop payment check: {stop_payment_result.stop_reason or 'bloom_hit_or_cbs_unavailable'}",
                shap_values={},
            )

        # Step 5: PPS lookup
        pps_result = mock_results["pps"]

        # Step 6: Signature verification
        sig_result = mock_results["signature"]

        # Step 7: Fraud scoring (always includes SHAP)
        fraud_result = mock_results["fraud"]

        # Step 8: CBS balance check — degrade gracefully on CBS unavailability
        cbs_result = mock_results["cbs"]
        if cbs_result.outcome == "CBS_UNAVAILABLE":
            log.warning(
                "cheque_workflow.cbs_unavailable_degrade",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            )
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale="cbs_unavailable_image_only_path",
                shap_values={},
            )
        if cbs_result.outcome in ("RETURN",):
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"CBS balance check: {cbs_result.outcome}",
                shap_values={},
            )

        # Step 9: Account status check (FROZEN/CLOSED/NPA → RETURN, DORMANT → HUMAN_REVIEW)
        account_status_result = mock_results["account_status"]
        if account_status_result.outcome == "RETURN":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"Account status: {account_status_result.account_status}",
                shap_values={},
            )
        if account_status_result.outcome == "HUMAN_REVIEW":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale=f"Account status review: {account_status_result.account_status}",
                shap_values={},
            )

        # Step 10: Synthesise decision
        decision_result = mock_results["decision"]

        # Step 9: Sub-Member Bank activities (only for sub-member-tagged instruments)
        sub_member_id = mock_results.get("sub_member_id")
        sub_member_notified = False
        ledger_updated = False

        if sub_member_id:
            # Map workflow decision to clearing bucket
            decision_to_bucket = {
                "STP_CONFIRM": "STP_PASS",
                "STP_RETURN": "STP_RETURN",
                "HUMAN_REVIEW": "EYEBALL",
                "FRAUD_HOLD": "FRAUD_HOLD",
            }
            bucket = decision_to_bucket.get(decision_result.decision, "EYEBALL")

            # Notify sub-member on returns or fraud holds
            if decision_result.decision in ("STP_RETURN", "FRAUD_HOLD"):
                await notify_sub_member_return(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    sub_member_id=sub_member_id,
                    return_reason=decision_result.rationale,
                    bucket=bucket,
                    amount_range=mock_results.get("amount_range", "₹[<1L]"),
                    cheque_number_suffix=inp.cheque_number[-4:],
                )
                sub_member_notified = True

            # Always emit ledger update for sub-member instruments
            await emit_batch_ledger_update(
                bank_id=inp.bank_id,
                sub_member_id=sub_member_id,
                session_date=mock_results.get("session_date", ""),
                clearing_session=mock_results.get("clearing_session", "MORNING"),
                bucket=bucket,
            )
            ledger_updated = True

        log.info(
            "cheque_workflow.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            decision=decision_result.decision,
        )

        return ChequeWorkflowResult(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            decision=decision_result.decision,
            rationale=decision_result.rationale,
            shap_values=decision_result.shap_values,
            sub_member_notified=sub_member_notified,
            ledger_updated=ledger_updated,
        )

    async def run_shield_check(
        self,
        bank_id: str,
        sub_member_id: str,
        session_date: str,
        clearing_session: str,
        mock_shield_status: Optional[str] = None,
    ) -> dict:
        """
        Periodic shield check — represents what ReturnRateMonitor triggers on schedule.
        Calls check_return_rate_shield and returns the shield assessment.
        """
        return await check_return_rate_shield(
            bank_id=bank_id,
            sub_member_id=sub_member_id,
            session_date=session_date,
            clearing_session=clearing_session,
            mock_shield_status=mock_shield_status,
        )
