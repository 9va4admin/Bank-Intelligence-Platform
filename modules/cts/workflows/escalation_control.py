"""Starting and stopping an incident's escalation from outside a workflow (the API). Best effort: it never raises."""
from __future__ import annotations

from typing import Any

import structlog

from modules.cts.workflows.alert_escalation_workflow import AlertEscalationInput, AlertEscalationWorkflow

log = structlog.get_logger()


def escalation_workflow_id(bank_id: str, incident_id: str) -> str:
    return f"cts-alert-{bank_id}-{incident_id}"


async def start_escalation(client: Any, bank_id: str, incident_id: str, *, started_at: float) -> bool:
    """Start the escalation workflow for an incident. Already running counts as success."""
    if client is None:
        return False
    try:
        await client.start_workflow(AlertEscalationWorkflow.run, AlertEscalationInput(bank_id=bank_id, incident_id=incident_id, started_at=started_at),
                                    id=escalation_workflow_id(bank_id, incident_id), task_queue=f"cts-processing-{bank_id}")
        return True
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "WorkflowAlreadyStartedError":
            return True
        log.warning("escalation.start_failed", bank_id=bank_id, incident_id=incident_id, error=type(exc).__name__)
        return False


async def stop_escalation(client: Any, bank_id: str, incident_id: str, reason: str) -> bool:
    """Tell the escalation the incident was acknowledged or resolved. If it cannot be reached the escalation stops by itself at its next step."""
    if client is None:
        return False
    try:
        await client.get_workflow_handle(escalation_workflow_id(bank_id, incident_id)).signal(AlertEscalationWorkflow.stop, reason)
        return True
    except Exception as exc:  # noqa: BLE001
        log.info("escalation.stop_not_delivered", bank_id=bank_id, incident_id=incident_id, error=type(exc).__name__)
        return False
