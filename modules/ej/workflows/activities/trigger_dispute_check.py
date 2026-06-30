"""
trigger_dispute_check activity — publish canonical record to Kafka for dispute matching.

Publishes to ej.canonical.{bank_id} so DisputeResolutionWorkflow can attempt
to match this EJ transaction against any outstanding NPCI claims.
"""
import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()
tracer = trace.get_tracer("astra.ej")


class EJTriggerDisputeCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "TRIGGERED" | "SKIPPED"
    bank_id: str


async def trigger_dispute_check(
    canonical_hash: str,
    atm_id: str,
    bank_id: str,
    canonical_record: dict | None = None,
) -> EJTriggerDisputeCheckResult:
    """
    Publish canonical EJ record to ej.canonical.{bank_id} Kafka topic.
    DisputeResolutionWorkflow consumer picks this up and attempts NPCI claim matching.
    """
    with tracer.start_as_current_span("ej.trigger_dispute_check") as span:
        span.set_attribute("atm_id", atm_id)
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("canonical_hash", canonical_hash[:12])

        try:
            from shared.event_bus.producer import KafkaEventProducer
            from shared.config.config_service import config_service

            producer = KafkaEventProducer(
                bootstrap_servers=config_service.get("kafka.bootstrap_servers"),
                module="ej",
            )
            producer.publish(
                topic=f"ej.canonical.{bank_id}",
                event_type="EJ_CANONICAL_READY",
                payload={
                    "canonical_hash": canonical_hash,
                    "atm_id": atm_id,
                    "bank_id": bank_id,
                    **(canonical_record or {}),
                },
                bank_id=bank_id,
            )
            producer.flush()
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
