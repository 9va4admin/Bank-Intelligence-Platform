"""
orchestrate_msv_validation activity — wraps SignatureOrchestrator.validate() for Temporal.

This is the production Temporal entry point for MSV validation. It accepts the
orchestrator as a keyword-default dependency (injected by BoundMSVActivities at
worker registration time; None in free-function tests where _execute() is used).

Graceful degradation:
  orchestrator is None → AMBER + ORCHESTRATOR_UNAVAILABLE (no crash, no IET risk)

PII rules:
  - instrument_id: safe to log
  - account_number: never logged — handled inside orchestrator
"""
from __future__ import annotations

import structlog
from temporalio import activity

from modules.msv.mandates.models import (
    AccountMandateMeta,
    MSVInput,
    MSVOutcome,
    MSVOutput,
)
from modules.msv.workflows.msv_workflow import MSVWorkflowInput

log = structlog.get_logger()


@activity.defn
async def orchestrate_msv_validation(
    inp: MSVWorkflowInput,
    orchestrator=None,
) -> MSVOutput:
    """
    Call SignatureOrchestrator.validate() inside a Temporal activity boundary.

    All I/O (signature detection, embedding, registry lookup, BRE evaluation)
    happens here — keeping the workflow itself deterministic.

    Args:
        inp:          MSVWorkflowInput containing msv_input + account_meta
        orchestrator: SignatureOrchestrator (injected by BoundMSVActivities;
                      None in free-function tests)
    """
    if orchestrator is None:
        log.warning(
            "msv.orchestrate.no_orchestrator",
            instrument_id=inp.msv_input.instrument_id,
            bank_id=inp.msv_input.bank_id,
        )
        return MSVOutput(
            outcome=MSVOutcome.AMBER,
            confidence=0.0,
            reason_code="ORCHESTRATOR_UNAVAILABLE",
            reason_message=(
                "SignatureOrchestrator not available at worker startup — "
                "routing to human review."
            ),
            matched_signatories=[],
            detected_sig_count=0,
            mandate_rule_type="UNKNOWN",
        )

    try:
        result: MSVOutput = await orchestrator.validate(
            inp.msv_input, inp.account_meta
        )
    except Exception as exc:
        log.error(
            "msv.orchestrate.error",
            instrument_id=inp.msv_input.instrument_id,
            bank_id=inp.msv_input.bank_id,
            error=str(exc),
        )
        # Re-raise so Temporal can retry with MSV_ACTIVITY_RETRY
        raise

    log.info(
        "msv.orchestrate.done",
        instrument_id=inp.msv_input.instrument_id,
        bank_id=inp.msv_input.bank_id,
        outcome=result.outcome.value,
        confidence=result.confidence,
    )
    return result
