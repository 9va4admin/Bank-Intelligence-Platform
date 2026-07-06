"""
trigger_dispute_check activity — publish canonical record to Kafka for dispute matching.

Publishes to ej.canonical.{bank_id} so DisputeResolutionWorkflow can attempt
to match this EJ transaction against any outstanding NPCI claims.
"""
from typing import Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.ej")

_TOPIC_PREFIX = "ej.canonical"


class EJTriggerDisputeCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "TRIGGERED" | "SKIPPED"
    bank_id: str


@activity.defn
async def trigger_dispute_check(
    canonical_hash: str,
    atm_id: str,
    bank_id: str,
    canonical_record: Optional[dict] = None,
    kafka_producer=None,
) -> EJTriggerDisputeCheckResult:
    """
    Publish canonical EJ record to ej.canonical.{bank_id} Kafka topic.
    DisputeResolutionWorkflow consumer picks this up and attempts NPCI claim matching.

    kafka_producer: injected in production (EventProducer instance); None in tests.
    """
    with tracer.start_as_current_span("ej.trigger_dispute_check") as span:
        span.set_attribute("atm_id", atm_id)
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("canonical_hash", canonical_hash[:12])

        if kafka_producer is None:
            log.warning(
                "ej.trigger_dispute_check.no_producer",
                atm_id=atm_id,
                bank_id=bank_id,
            )
            span.set_attribute("kafka.published", False)
            return EJTriggerDisputeCheckResult(outcome="SKIPPED", bank_id=bank_id)

        try:
            await kafka_producer.publish(
                topic=f"{_TOPIC_PREFIX}.{bank_id}",
                event_type="EJ_CANONICAL_READY",
                payload={
                    "canonical_hash": canonical_hash,
                    "atm_id": atm_id,
                    "bank_id": bank_id,
                    **(canonical_record or {}),
                },
                schema_version="1.0",
            )
            span.set_attribute("kafka.published", True)
        except Exception as exc:
            # Non-fatal — dispute matching can be triggered via manual NPCI claim route
            log.warning(
                "ej.trigger_dispute_check.kafka_failed",
                atm_id=atm_id,
                bank_id=bank_id,
                error=str(exc),
            )
            span.set_attribute("kafka.published", False)
            return EJTriggerDisputeCheckResult(outcome="SKIPPED", bank_id=bank_id)

        log.info(
            "ej.trigger_dispute_check.done",
            atm_id=atm_id,
            bank_id=bank_id,
            canonical_hash=canonical_hash[:12],
        )
        return EJTriggerDisputeCheckResult(outcome="TRIGGERED", bank_id=bank_id)
