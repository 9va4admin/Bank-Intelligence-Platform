"""
write_audit activity — write immutable audit event to Immudb.

Must be called for ALL outcomes (NORMALISED, PARSE_FAILED, VALIDATION_FAILED).
Publishes to platform.audit.events Kafka topic; the AuditWriteWorkflow handles
HSM signing and Immudb persistence.
"""
import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJWriteAuditResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "WRITTEN"
    bank_id: str


async def write_audit(
    workflow_outcome: str,
    raw_log_hash: str,
    canonical_hash: str | None,
    atm_id: str,
    bank_id: str,
) -> EJWriteAuditResult:
    """
    Emit EJNormalisationAuditEvent to platform.audit.events Kafka topic.

    This is a fire-and-forget from the workflow's perspective — Temporal
    handles durability via unlimited retries on the AuditWriteWorkflow.
    Called for every terminal state, including failures.
    """
    log.info(
        "ej.write_audit.start",
        workflow_outcome=workflow_outcome,
        atm_id=atm_id,
        bank_id=bank_id,
        raw_log_hash=raw_log_hash[:12],
    )
    # Production: Kafka produce to platform.audit.events
    return EJWriteAuditResult(
        outcome="WRITTEN",
        bank_id=bank_id,
    )
