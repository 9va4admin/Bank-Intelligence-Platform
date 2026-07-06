"""
write_audit activity — emit EJ normalisation audit event to Kafka.

Publishes to platform.audit.events; the AuditWriteWorkflow handles HSM
signing and Immudb persistence.  Must be called for ALL outcomes
(NORMALISED, PARSE_FAILED, VALIDATION_FAILED, EJ_INTEGRITY_FAIL).

Caller injects kafka_producer (EventProducer) for production. Test callers
omit it to exercise the activity without a live Kafka broker.
"""
import structlog
from pydantic import BaseModel, ConfigDict

from shared.audit.audit_event import AuditEvent, AuditEventType

log = structlog.get_logger()

_AUDIT_TOPIC = "platform.audit.events"
_SCHEMA_VERSION = "1.0"


class EJWriteAuditResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "WRITTEN" | "SKIPPED"
    bank_id: str


async def write_audit(
    workflow_outcome: str,
    raw_log_hash: str,
    canonical_hash: str | None,
    atm_id: str,
    bank_id: str,
    kafka_producer=None,
) -> EJWriteAuditResult:
    """
    Emit EJNormalisationAuditEvent to platform.audit.events Kafka topic.

    Fire-and-forget from workflow perspective — Temporal retries with unlimited
    attempts (AUDIT_RETRY) so every terminal state is guaranteed to be recorded.
    Production callers must inject kafka_producer (EventProducer, module="ej").
    """
    log.info(
        "ej.write_audit.start",
        workflow_outcome=workflow_outcome,
        atm_id=atm_id,
        bank_id=bank_id,
        raw_log_hash=raw_log_hash[:12],
    )

    audit_ev = AuditEvent(
        event_type=AuditEventType.EJ_PARSED,
        bank_id=bank_id,
        payload={
            "workflow_outcome": workflow_outcome,
            "atm_id": atm_id,
            "raw_log_hash": raw_log_hash,
            "canonical_hash": canonical_hash,
        },
    )

    if kafka_producer is None:
        # Test path — no broker available; log and return without publishing.
        log.warning(
            "ej.write_audit.no_kafka_producer",
            atm_id=atm_id,
            bank_id=bank_id,
        )
        return EJWriteAuditResult(outcome="SKIPPED", bank_id=bank_id)

    await kafka_producer.publish(
        topic=_AUDIT_TOPIC,
        event_type=audit_ev.event_type.value,
        payload=audit_ev.payload,
        schema_version=_SCHEMA_VERSION,
    )

    log.info(
        "ej.write_audit.complete",
        atm_id=atm_id,
        bank_id=bank_id,
        raw_log_hash=raw_log_hash[:12],
        canonical_hash=(canonical_hash or "")[:12],
    )

    return EJWriteAuditResult(outcome="WRITTEN", bank_id=bank_id)
