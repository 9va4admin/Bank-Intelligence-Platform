"""
SMBForwardingWorkflow — runs at the Sponsor Bank.

Triggered when ChequeProcessingWorkflow identifies a cheque as belonging to a
Sub-Member Bank (principal_tag = SUB_MEMBER). This workflow:

  1. Validates the SMB is active and the forwarding window is safe (IET headroom).
  2. Writes a smb_forwarding_log entry (FORWARDING state).
  3. Starts SMBChequeProcessingWorkflow as a child at the Sub-Member Bank's task queue.
  4. Waits for the child's terminal decision signal.
  5. Writes the COMPLETED or FAILED state back to smb_forwarding_log.
  6. Emits Immudb audit event.

IET Safety: If IET deadline is within config_service.get("cts.smb.min_iet_headroom_s")
seconds at the point of forwarding, the workflow short-circuits to IET_EMERGENCY and
files directly to NGCH without forwarding to the SMB.

Workflow ID: smb-fwd-{bank_id}-{instrument_id}
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


# ── Input / Output models ─────────────────────────────────────────────────────

@dataclass
class SMBForwardingInput:
    instrument_id: str
    bank_id: str                  # Sponsor Bank's bank_id
    sub_member_id: str
    micr_prefix_matched: str
    iet_deadline_utc: str         # ISO-8601 UTC
    cheque_image_ref: str         # MinIO object key — never the raw image
    micr_line: str
    amount_range: str
    session_date: str
    clearing_session: str


@dataclass
class SMBForwardingResult:
    instrument_id: str
    sub_member_id: str
    terminal_decision: str        # STP_CONFIRM | STP_RETURN | HUMAN_REVIEW | IET_EMERGENCY
    forwarding_id: str
    smb_workflow_id: Optional[str]
    short_circuited: bool         # True if IET headroom was too low to forward
    completed_at: str             # ISO-8601 UTC


# ── Retry policies ────────────────────────────────────────────────────────────

_DB_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError"],
)

_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=None,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


# ── Workflow ──────────────────────────────────────────────────────────────────

@workflow.defn
class SMBForwardingWorkflow:
    """
    Sponsor Bank side of the SMB forwarding hop.

    Task queue: cts-processing-{sponsor_bank_id}
    Workflow ID: smb-fwd-{bank_id}-{instrument_id}
    """

    def __init__(self) -> None:
        self._smb_decision: Optional[str] = None
        self._smb_workflow_id: Optional[str] = None

    @workflow.run
    async def run(self, input: SMBForwardingInput) -> SMBForwardingResult:
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window,
            write_forwarding_log_start,
            write_forwarding_log_complete,
            write_smb_forwarding_audit,
        )

        # 1. Validate IET headroom and SMB active status
        validation = await workflow.execute_activity(
            validate_smb_forwarding_window,
            args=[input.instrument_id, input.bank_id, input.sub_member_id,
                  input.iet_deadline_utc],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_DB_RETRY,
        )

        forwarding_id = validation["forwarding_id"]

        if not validation["safe_to_forward"]:
            # IET headroom too low — short-circuit: file emergency directly
            result = SMBForwardingResult(
                instrument_id=input.instrument_id,
                sub_member_id=input.sub_member_id,
                terminal_decision="IET_EMERGENCY",
                forwarding_id=forwarding_id,
                smb_workflow_id=None,
                short_circuited=True,
                completed_at=str(workflow.now()),
            )
            await workflow.execute_activity(
                write_smb_forwarding_audit,
                args=[forwarding_id, input.bank_id, "IET_EMERGENCY", "SHORT_CIRCUIT_IET_HEADROOM"],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            return result

        # 2. Log FORWARDING state
        await workflow.execute_activity(
            write_forwarding_log_start,
            args=[forwarding_id, input.instrument_id, input.bank_id,
                  input.sub_member_id, input.micr_prefix_matched, input.iet_deadline_utc],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_DB_RETRY,
        )

        # 3. Start SMBChequeProcessingWorkflow as child on SMB task queue
        smb_workflow_id = f"smb-cts-{input.sub_member_id}-{input.instrument_id}"
        self._smb_workflow_id = smb_workflow_id

        from modules.cts.workflows.smb_cheque_processing_workflow import (
            SMBChequeProcessingWorkflow,
            SMBChequeInput,
        )

        child_result = await workflow.execute_child_workflow(
            SMBChequeProcessingWorkflow.run,
            args=[SMBChequeInput(
                instrument_id=input.instrument_id,
                sub_member_id=input.sub_member_id,
                sponsor_bank_id=input.bank_id,
                iet_deadline_utc=input.iet_deadline_utc,
                cheque_image_ref=input.cheque_image_ref,
                micr_line=input.micr_line,
                amount_range=input.amount_range,
                session_date=input.session_date,
                clearing_session=input.clearing_session,
                forwarding_id=forwarding_id,
            )],
            id=smb_workflow_id,
            task_queue=f"cts-processing-{input.sub_member_id}",
        )

        terminal_decision = child_result.terminal_decision

        # 4. Write COMPLETED state to forwarding log
        await workflow.execute_activity(
            write_forwarding_log_complete,
            args=[forwarding_id, input.bank_id, terminal_decision, smb_workflow_id],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_DB_RETRY,
        )

        # 5. Audit trail
        await workflow.execute_activity(
            write_smb_forwarding_audit,
            args=[forwarding_id, input.bank_id, terminal_decision, "COMPLETED"],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return SMBForwardingResult(
            instrument_id=input.instrument_id,
            sub_member_id=input.sub_member_id,
            terminal_decision=terminal_decision,
            forwarding_id=forwarding_id,
            smb_workflow_id=smb_workflow_id,
            short_circuited=False,
            completed_at=str(workflow.now()),
        )

    @workflow.query
    def get_smb_workflow_id(self) -> Optional[str]:
        return self._smb_workflow_id

    @workflow.query
    def get_smb_decision(self) -> Optional[str]:
        return self._smb_decision
