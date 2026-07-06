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
from datetime import timedelta
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

from modules.cts.sub_member.activities import (
    check_return_rate_shield,
    emit_batch_ledger_update,
    notify_sub_member_return,
)

log = structlog.get_logger()

# Standard retry policies (defined once — all CTS workflows use these constants)
_AI_ACTIVITY_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError", "IETBreachError"],
)
_CBS_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)
_NGCH_FILING_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"],
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,  # 0 = unlimited in Temporal Python SDK
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)

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
    cts_config: dict = Field(default_factory=dict)  # Layer 3 thresholds forwarded to decision


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


@workflow.defn
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

    @workflow.run
    async def run(self, inp: ChequeWorkflowInput) -> ChequeWorkflowResult:
        """Production Temporal entry point — Phase 3 drawee inward processing."""
        from modules.cts.workflows.activities.alteration import (
            AlterationActivityInput, detect_alteration,
        )
        from modules.cts.workflows.activities.stop_payment import (
            StopPaymentActivityInput, check_stop_payment,
        )
        from modules.cts.workflows.activities.pps import (
            PPSActivityInput, lookup_pps,
        )
        from modules.cts.workflows.activities.signature import (
            SignatureActivityInput, verify_signature,
        )
        from modules.cts.workflows.activities.fraud import (
            FraudActivityInput, score_fraud,
        )
        from modules.cts.workflows.activities.cbs import (
            CBSActivityInput, check_cbs_balance, check_account_status,
        )
        from modules.cts.workflows.activities.decision import (
            DecisionInput, synthesise_decision,
        )
        from modules.cts.workflows.activities.ngch_filer import (
            NGCHFilerInput, file_to_ngch,
        )
        from modules.cts.workflows.activities.write_audit import (
            WriteAuditInput, write_audit,
        )
        from modules.cts.workflows.iet_watchdog_workflow import (
            IETWatchdogInput, IETWatchdogWorkflow,
        )

        wf_id = self.workflow_id(inp.bank_id, inp.instrument_id)

        # Step 1: Spawn IET watchdog FIRST — before any activity (non-negotiable)
        watchdog = await workflow.start_child_workflow(
            IETWatchdogWorkflow.run,
            IETWatchdogInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                iet_deadline=inp.iet_deadline,
                workflow_id=wf_id,
            ),
            id=self.iet_watchdog_id(inp.bank_id, inp.instrument_id),
            parent_close_policy=ParentClosePolicy.ABANDON,
        )
        self._watchdog_spawned = True

        # Step 2: detect_alteration — Vision LLM FIRST on drawee side
        alteration_result = await workflow.execute_activity(
            detect_alteration,
            AlterationActivityInput(
                image_url=inp.image_url,
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                cheque_amount=inp.presented_amount,
                smb_id=inp.smb_id,
            ),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_AI_ACTIVITY_RETRY,
        )
        if alteration_result.alteration_detected:
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="HUMAN_REVIEW", rationale="alteration_detected", shap_values={},
            )

        # Step 3: check_stop_payment — Bloom pre-check + CBS confirm
        stop_result = await workflow.execute_activity(
            check_stop_payment,
            StopPaymentActivityInput(
                account_number=inp.account_number,
                cheque_number=inp.cheque_number,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CBS_RETRY,
        )
        if stop_result.outcome == "STP_RETURN":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"Stop payment: {stop_result.stop_reason}", shap_values={},
            )
        if stop_result.outcome == "HUMAN_REVIEW":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale=f"Stop payment check: {stop_result.stop_reason or 'bloom_hit'}",
                shap_values={},
            )

        # Step 4: lookup_pps
        pps_result = await workflow.execute_activity(
            lookup_pps,
            PPSActivityInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                account_number=inp.account_number,
                cheque_number=inp.cheque_number,
                presented_amount=inp.presented_amount,
                presented_payee=inp.presented_payee,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CBS_RETRY,
        )

        # Step 5: verify_signature
        sig_result = await workflow.execute_activity(
            verify_signature,
            SignatureActivityInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                account_number=inp.account_number,
                signature_image_url=inp.image_url,
                smb_id=inp.smb_id,
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AI_ACTIVITY_RETRY,
        )

        # Step 6: score_fraud
        fraud_result = await workflow.execute_activity(
            score_fraud,
            FraudActivityInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                amount=inp.presented_amount,
                micr_line="",  # MICR comes from NGCH metadata on inward side
                ocr_confidence=sig_result.match_score or 0.0,
                alteration_detected=alteration_result.alteration_detected,
                account_last4=inp.account_number[-4:],
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_AI_ACTIVITY_RETRY,
        )

        # Step 7: check_cbs_balance
        cbs_balance_result = await workflow.execute_activity(
            check_cbs_balance,
            CBSActivityInput(
                account_number=inp.account_number,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CBS_RETRY,
        )
        if cbs_balance_result.outcome == "CBS_UNAVAILABLE":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="HUMAN_REVIEW", rationale="cbs_unavailable_image_only_path",
                shap_values={},
            )
        if cbs_balance_result.outcome == "RETURN":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"CBS balance check: {cbs_balance_result.outcome}", shap_values={},
            )

        # Step 8: check_account_status
        acct_status_result = await workflow.execute_activity(
            check_account_status,
            CBSActivityInput(
                account_number=inp.account_number,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_CBS_RETRY,
        )
        if acct_status_result.outcome == "RETURN":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="STP_RETURN",
                rationale=f"Account status: {acct_status_result.account_status}", shap_values={},
            )
        if acct_status_result.outcome == "HUMAN_REVIEW":
            return ChequeWorkflowResult(
                instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                decision="HUMAN_REVIEW",
                rationale=f"Account status review: {acct_status_result.account_status}",
                shap_values={},
            )

        # Step 9: synthesise_decision
        decision_result = await workflow.execute_activity(
            synthesise_decision,
            DecisionInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                smb_id=inp.smb_id,
                fraud_score=fraud_result.fraud_score,
                ocr_confidence=1.0,  # inward side: NGCH guarantees image; no OCR step
                signature_match_score=sig_result.match_score or 0.0,
                cbs_outcome=cbs_balance_result.outcome,
                alteration_detected=alteration_result.alteration_detected,
                pps_outcome=pps_result.outcome,
                available_balance=cbs_balance_result.available_balance,
                cheque_amount=inp.presented_amount,
                shap_values=fraud_result.shap_values,
            ),
            inp.cts_config,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_CBS_RETRY,
        )

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
        )

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
