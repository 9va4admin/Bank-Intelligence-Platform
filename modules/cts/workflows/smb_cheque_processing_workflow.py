"""
SMBChequeProcessingWorkflow — runs at the Sub-Member Bank's task queue.

This is a slimmer version of ChequeProcessingWorkflow tailored for cheques that
arrive via a Sponsor Bank forwarding hop. Key differences from the main workflow:

  - Does NOT spawn its own IETWatchdogWorkflow (the Sponsor's watchdog is already
    running; spawning a second one would cause a duplicate NGCH filing).
  - Uses the sub_member_id-namespaced vault keys for signature + PPS lookups.
  - Files decisions back to NGCH via the Sponsor Bank's ngch_filer activity
    (SMBs are not direct NGCH members).
  - Batch ledger is updated via emit_batch_ledger_update at every decision point.
  - Return Rate Shield is checked after every STP_RETURN — shield status gates
    whether further STP decisions are allowed in the session.

Workflow ID: smb-cts-{sub_member_id}-{instrument_id}
Task queue: cts-processing-{sub_member_id}
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


# ── Input / Output ────────────────────────────────────────────────────────────

@dataclass
class SMBChequeInput:
    instrument_id: str
    sub_member_id: str
    sponsor_bank_id: str          # The Direct NGCH member that forwarded this
    iet_deadline_utc: str         # ISO-8601 UTC — inherited from sponsor
    cheque_image_ref: str         # MinIO object key
    micr_line: str
    amount_range: str
    session_date: str
    clearing_session: str
    forwarding_id: str            # FK to smb_forwarding_log


@dataclass
class SMBChequeResult:
    instrument_id: str
    sub_member_id: str
    terminal_decision: str        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW | IET_EMERGENCY
    fraud_score: Optional[float]
    ocr_confidence: Optional[float]
    signature_score: Optional[float]
    bucket: str
    ledger_updated: bool
    ngch_filed: bool
    audit_written: bool


# ── Retry constants (mirrors CTS standards from CLAUDE.md) ───────────────────

_AI_RETRY = RetryPolicy(
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

_NGCH_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    non_retryable_error_types=["DuplicateFilingError"],
)

_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=None,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


# ── Workflow ──────────────────────────────────────────────────────────────────

@workflow.defn
class SMBChequeProcessingWorkflow:
    """
    Full cheque processing pipeline for a Sub-Member Bank instrument.

    Activity sequence:
      ocr_extract → detect_alteration → verify_signature (SMB vault namespace)
      → lookup_pps (SMB vault namespace) → check_cbs_balance → score_fraud
      → synthesise_decision → check_return_rate_shield → file_to_ngch (via sponsor)
      → emit_batch_ledger_update → write_audit

    Vault key namespace: sig:{sub_member_id}:{hash} and pps:{sub_member_id}:{hash}
    """

    @workflow.run
    async def run(self, input: SMBChequeInput) -> SMBChequeResult:
        # Import activities — late import keeps workflow module importable standalone
        from modules.cts.workflows.activities.ocr import ocr_extract
        from modules.cts.workflows.activities.alteration import detect_alteration
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.workflows.activities.pps import lookup_pps
        from modules.cts.workflows.activities.cbs import check_cbs_balance
        from modules.cts.workflows.activities.fraud import score_fraud
        from modules.cts.workflows.activities.decision import synthesise_decision
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch
        from modules.cts.workflows.activities.write_audit import write_audit
        from modules.cts.sub_member.activities import (
            emit_batch_ledger_update,
            check_return_rate_shield,
            notify_sub_member_return,
        )

        ocr_confidence: Optional[float] = None
        fraud_score: Optional[float] = None
        signature_score: Optional[float] = None

        # ── OCR ───────────────────────────────────────────────────────────────
        try:
            ocr_result = await workflow.execute_activity(
                ocr_extract,
                args=[input.cheque_image_ref, input.micr_line,
                      input.sponsor_bank_id, input.sub_member_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_AI_RETRY,
            )
            ocr_confidence = ocr_result.get("confidence")
        except ActivityError:
            # Degrade: proceed with image-only path
            ocr_result = {"status": "DEGRADED", "confidence": None}

        # ── Alteration detection ──────────────────────────────────────────────
        try:
            alteration_result = await workflow.execute_activity(
                detect_alteration,
                args=[input.cheque_image_ref, input.sponsor_bank_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_AI_RETRY,
            )
        except ActivityError:
            alteration_result = {"tamper_risk": 0.0, "status": "DEGRADED"}

        # ── Signature verification (SMB vault namespace) ──────────────────────
        try:
            sig_result = await workflow.execute_activity(
                verify_signature,
                args=[input.cheque_image_ref, input.sponsor_bank_id,
                      input.sub_member_id],   # sub_member_id drives vault key namespace
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AI_RETRY,
            )
            signature_score = sig_result.get("match_score")
        except ActivityError:
            # Vault miss or model down → human review, never auto-return
            sig_result = {"outcome": "VAULT_MISS", "match_score": None}

        # ── PPS lookup (SMB vault namespace) ──────────────────────────────────
        try:
            pps_result = await workflow.execute_activity(
                lookup_pps,
                args=[input.instrument_id, input.sponsor_bank_id,
                      input.sub_member_id],   # sub_member_id drives vault key namespace
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_DB_RETRY if False else _AI_RETRY,
            )
        except ActivityError:
            pps_result = {"outcome": "VAULT_MISS"}

        # ── CBS balance check ─────────────────────────────────────────────────
        try:
            cbs_result = await workflow.execute_activity(
                check_cbs_balance,
                args=[input.instrument_id, input.sub_member_id],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_CBS_RETRY,
            )
        except ActivityError:
            cbs_result = {"available": None, "status": "UNREACHABLE"}

        # ── Fraud scoring ─────────────────────────────────────────────────────
        try:
            fraud_result = await workflow.execute_activity(
                score_fraud,
                args=[input.instrument_id, input.sponsor_bank_id,
                      ocr_result, alteration_result, sig_result, cbs_result],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_AI_RETRY,
            )
            fraud_score = fraud_result.get("fraud_score")
        except ActivityError:
            fraud_result = {"fraud_score": None, "status": "DEGRADED"}

        # ── Decision synthesis ────────────────────────────────────────────────
        decision = await workflow.execute_activity(
            synthesise_decision,
            args=[input.instrument_id, input.sponsor_bank_id,
                  input.sub_member_id, ocr_result, sig_result,
                  pps_result, cbs_result, fraud_result],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_AI_RETRY,
        )

        terminal_decision: str = decision["decision"]   # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW
        bucket: str = decision["bucket"]

        # ── Return Rate Shield check (only on STP_RETURN) ─────────────────────
        if terminal_decision == "STP_RETURN":
            shield = await workflow.execute_activity(
                check_return_rate_shield,
                args=[input.sponsor_bank_id, input.sub_member_id,
                      input.session_date, input.clearing_session],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_AI_RETRY,
            )
            if shield["shield_status"] in ("SOFT_HOLD", "HARD_STOP"):
                # Override: escalate to human review regardless of fraud score
                terminal_decision = "HUMAN_REVIEW"
                bucket = "EYEBALL"

            # Tier 1 notification for return
            await workflow.execute_activity(
                notify_sub_member_return,
                args=[input.instrument_id, input.sponsor_bank_id,
                      input.sub_member_id, decision.get("return_reason", "UNSPECIFIED"),
                      bucket, input.amount_range,
                      input.instrument_id[-4:]],  # last 4 chars as suffix — PII rule
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_AI_RETRY,
            )

        # ── File to NGCH via Sponsor Bank ─────────────────────────────────────
        # SMB is not a direct NGCH member — all filings go through sponsor's ngch_filer
        ngch_result = await workflow.execute_activity(
            file_to_ngch,
            args=[input.instrument_id, input.sponsor_bank_id, terminal_decision,
                  decision.get("return_reason"), input.iet_deadline_utc,
                  input.forwarding_id],   # forwarding_id enables sponsor to correlate
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_NGCH_RETRY,
        )
        ngch_filed = ngch_result.get("filed", False)

        # ── Batch ledger update ───────────────────────────────────────────────
        await workflow.execute_activity(
            emit_batch_ledger_update,
            args=[input.sponsor_bank_id, input.sub_member_id,
                  input.session_date, input.clearing_session, bucket],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_AI_RETRY,
        )

        # ── Audit write (must succeed — unlimited retries) ─────────────────────
        await workflow.execute_activity(
            write_audit,
            args=[input.instrument_id, input.sponsor_bank_id,
                  input.sub_member_id, terminal_decision, fraud_score,
                  ngch_result.get("ngch_ref"), "SMB_CHEQUE_PROCESSED"],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return SMBChequeResult(
            instrument_id=input.instrument_id,
            sub_member_id=input.sub_member_id,
            terminal_decision=terminal_decision,
            fraud_score=fraud_score,
            ocr_confidence=ocr_confidence,
            signature_score=signature_score,
            bucket=bucket,
            ledger_updated=True,
            ngch_filed=ngch_filed,
            audit_written=True,
        )
