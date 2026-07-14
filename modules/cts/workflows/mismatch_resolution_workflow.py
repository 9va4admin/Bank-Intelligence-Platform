"""
MismatchResolutionWorkflow — branch supervisor resolution for Vision ↔ scanner mismatch.

Triggered by: OutwardScanWorkflow when Vision LLM amount differs from scanner amount.

Flow:
  1. publish_mismatch_hold — publish to cts.mismatch.{bank_id}.{branch_id} Kafka topic
     (EEH SSE feed picks this up → branch portal shows HELD item in real-time)
  2. wait_for_signal      — Temporal signal: GO_AHEAD | REJECTED (or 4-hour timeout)
  3. write_audit          — Immudb audit for all outcomes

Terminal states: GO_AHEAD | REJECTED | TIMEOUT_AUTO_REJECTED
Workflow ID: cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}

ABANDON parent-close policy: this workflow persists even if OutwardScanWorkflow
is interrupted — branch supervisor must still be able to resolve it and the
instrument must be audited regardless of parent state.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

MISMATCH_TIMEOUT_HOURS = 4          # 4-hour resolution window before auto-reject

_KAFKA_PUBLISH_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,   # 0 = unlimited in Temporal Python SDK (None crashes _validate())
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


# ---------------------------------------------------------------------------
# publish_mismatch_hold — Kafka publish so the branch SSE feed picks up the
# hold in real-time (EEH session → branch portal).
# ---------------------------------------------------------------------------

class PublishMismatchHoldInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    bank_id: str
    branch_id: str
    scan_id: str
    instrument_id: str
    scanner_amount_str: str
    vision_amount_str: str
    mismatch_fields: list[str]
    payee_display: str
    session_id: str


class PublishMismatchHoldResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    published: bool


@activity.defn
async def publish_mismatch_hold(
    inp: PublishMismatchHoldInput,
    event_producer: Any = None,
) -> PublishMismatchHoldResult:
    """
    Publishes to cts.mismatch.{bank_id}.{branch_id} via the real
    shared/event_bus/producer.py EventProducer.

    event_producer is worker-level DI (out of this fix's scope, same
    precedent as cbs_connector/redis_client elsewhere) — EventProducer must
    be a single, already-connected instance shared by the worker process,
    not constructed fresh per activity call.
    """
    topic = f"cts.mismatch.{inp.bank_id}.{inp.branch_id}"
    await event_producer.publish(
        topic=topic,
        event_type="CTS_OUT_MISMATCH_HELD",
        payload={
            "mismatch_id": inp.mismatch_id,
            "scan_id": inp.scan_id,
            "instrument_id": inp.instrument_id,
            "scanner_amount": inp.scanner_amount_str,
            "vision_amount": inp.vision_amount_str,
            "mismatch_fields": inp.mismatch_fields,
            "payee_display": inp.payee_display,
            "session_id": inp.session_id,
        },
        schema_version="1.0",
    )
    log.info(
        "publish_mismatch_hold.published",
        mismatch_id=inp.mismatch_id,
        bank_id=inp.bank_id,
        branch_id=inp.branch_id,
        topic=topic,
    )
    return PublishMismatchHoldResult(published=True)


class MismatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    mismatch_id: str
    bank_id: str
    branch_id: str
    scan_id: str
    instrument_id: str
    pu_id: str
    scanner_amount_str: str         # as-read by scanner MICR (string, preserves original)
    vision_amount_str: str          # as-read by Vision LLM
    mismatch_fields: list[str]      # e.g. ["amount_figures", "amount_words"]
    payee_display: str              # masked: R***
    session_id: str                 # EEH session context


class MismatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # GO_AHEAD | REJECTED | TIMEOUT_AUTO_REJECTED
    mismatch_id: str
    bank_id: str
    branch_id: str
    resolved_by: Optional[str]      # operator_id; None on timeout
    audit_written: bool = False


class MismatchSignal(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: str                     # GO_AHEAD | REJECTED
    resolved_by: str                # operator_id
    supervisor_note: str = ""


# Aligned with shared/messages/locales/messages.yaml (CTS_OUT_MISMATCH_* keys,
# already registered — Phase 6 groundwork, never previously wired to code).
_OUTCOME_EVENT_TYPE = {
    "GO_AHEAD": "CTS_OUT_MISMATCH_RESOLVED_GO_AHEAD",
    "REJECTED": "CTS_OUT_MISMATCH_RESOLVED_REJECTED",
    "TIMEOUT_AUTO_REJECTED": "CTS_OUT_MISMATCH_TIMEOUT_AUTO_REJECTED",
}


@workflow.defn
class MismatchResolutionWorkflow:
    def __init__(self) -> None:
        self._signal: Optional[MismatchSignal] = None

    def workflow_id(self, bank_id: str, branch_id: str, mismatch_id: str) -> str:
        return f"cts-mismatch-{bank_id}-{branch_id}-{mismatch_id}"

    def mismatch_kafka_topic(self, bank_id: str, branch_id: str) -> str:
        return f"cts.mismatch.{bank_id}.{branch_id}"

    @workflow.signal
    def resolve(self, signal: MismatchSignal) -> None:
        """Branch supervisor's GO_AHEAD/REJECTED decision, signalled from the
        branch portal API."""
        self._signal = signal

    @workflow.run
    async def run(self, inp: MismatchInput) -> MismatchResult:
        """Production Temporal entry point — see module docstring for the flow."""
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        # Step 1: publish hold event — before any wait, so the branch SSE
        # feed shows it immediately.
        await workflow.execute_activity(
            publish_mismatch_hold,
            PublishMismatchHoldInput(
                mismatch_id=inp.mismatch_id,
                bank_id=inp.bank_id,
                branch_id=inp.branch_id,
                scan_id=inp.scan_id,
                instrument_id=inp.instrument_id,
                scanner_amount_str=inp.scanner_amount_str,
                vision_amount_str=inp.vision_amount_str,
                mismatch_fields=inp.mismatch_fields,
                payee_display=inp.payee_display,
                session_id=inp.session_id,
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_KAFKA_PUBLISH_RETRY,
        )

        # Step 2: wait for branch supervisor signal, or 4-hour timeout.
        try:
            await workflow.wait_condition(
                lambda: self._signal is not None,
                timeout=timedelta(hours=MISMATCH_TIMEOUT_HOURS),
            )
        except asyncio.TimeoutError:
            pass

        if self._signal is not None:
            outcome = self._signal.action   # "GO_AHEAD" | "REJECTED"
            resolved_by = self._signal.resolved_by
            log.info(
                "mismatch_resolution_workflow.resolved",
                mismatch_id=inp.mismatch_id,
                bank_id=inp.bank_id,
                outcome=outcome,
                resolved_by=resolved_by,
            )
        else:
            outcome = "TIMEOUT_AUTO_REJECTED"
            resolved_by = None
            log.warning(
                "mismatch_resolution_workflow.timeout_auto_rejected",
                mismatch_id=inp.mismatch_id,
                bank_id=inp.bank_id,
                branch_id=inp.branch_id,
                timeout_hours=MISMATCH_TIMEOUT_HOURS,
            )

        # Step 3: audit — always written regardless of outcome.
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(
                event_type=_OUTCOME_EVENT_TYPE[outcome],
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                payload={
                    "mismatch_id": inp.mismatch_id,
                    "branch_id": inp.branch_id,
                    "outcome": outcome,
                    "resolved_by": resolved_by,
                    "mismatch_fields": inp.mismatch_fields,
                },
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=_AUDIT_RETRY,
        )

        return MismatchResult(
            outcome=outcome,
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            resolved_by=resolved_by,
            audit_written=True,
        )

    async def run_with_mocks(
        self,
        inp: MismatchInput,
        mock_results: dict,
    ) -> MismatchResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run method;
        mock_results replaces each activity/signal call.

        mock_results keys:
          "kafka"  — Kafka publish result (accessed to confirm publish happens)
          "signal" — MagicMock(action="GO_AHEAD"|"REJECTED", resolved_by=str) or None (timeout)
          "audit"  — audit write result
        """
        # Step 1: Publish hold event to branch Kafka topic (before any wait)
        # In production: workflow.execute_activity(publish_mismatch_hold, ...)
        kafka_result = mock_results["kafka"]   # noqa: F841 — activity call in production
        log.info(
            "mismatch_resolution_workflow.hold_published",
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            topic=self.mismatch_kafka_topic(inp.bank_id, inp.branch_id),
            scanner_amount=inp.scanner_amount_str,
            vision_amount=inp.vision_amount_str,
        )

        # Step 2: Wait for branch supervisor signal (GO_AHEAD | REJECTED)
        # In production: await workflow.wait_condition(...) with 4-hour timeout
        # signal=None simulates timeout
        signal = mock_results["signal"]

        if signal is None:
            outcome = "TIMEOUT_AUTO_REJECTED"
            resolved_by = None
            log.info(
                "mismatch_resolution_workflow.timeout_auto_rejected",
                mismatch_id=inp.mismatch_id,
                bank_id=inp.bank_id,
                branch_id=inp.branch_id,
                timeout_hours=MISMATCH_TIMEOUT_HOURS,
            )
        else:
            action = signal.action          # "GO_AHEAD" | "REJECTED"
            resolved_by = signal.resolved_by
            if action == "GO_AHEAD":
                outcome = "GO_AHEAD"
                log.info(
                    "mismatch_resolution_workflow.go_ahead",
                    mismatch_id=inp.mismatch_id,
                    bank_id=inp.bank_id,
                    resolved_by=resolved_by,
                )
            else:
                outcome = "REJECTED"
                log.info(
                    "mismatch_resolution_workflow.rejected",
                    mismatch_id=inp.mismatch_id,
                    bank_id=inp.bank_id,
                    resolved_by=resolved_by,
                )

        # Step 3: Audit — always written regardless of outcome
        # In production: workflow.execute_activity(write_audit, ...)
        audit_result = mock_results["audit"]   # noqa: F841
        log.info(
            "mismatch_resolution_workflow.audit_written",
            outcome=outcome,
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
        )

        return MismatchResult(
            outcome=outcome,
            mismatch_id=inp.mismatch_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            resolved_by=resolved_by,
            audit_written=True,
        )
