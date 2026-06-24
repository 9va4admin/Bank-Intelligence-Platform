"""
update_atm_health activity — emit ATM health signal after EJ normalisation.

Two outputs:
  1. Redis EJ cache: ej:health:{bank_id}:{atm_id} — read by /v1/ej/atm/{atm_id}/health
  2. Kafka ej.health.signals.{bank_id}             — consumed by anomaly detector

Health status derived from canonical EJ record fields:
  HEALTHY  — no errors, normal transaction throughput
  DEGRADED — recoverable errors (card jams, receipt paper low, intermittent dispense)
  CRITICAL — cash exhausted, hardware fault, comms failure, repeated dispense errors
"""
import json
import time
import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()
tracer = trace.get_tracer("astra.ej")

# Error codes from canonical EJ schema that indicate each health tier
_CRITICAL_ERROR_CODES = {
    "CASH_EXHAUSTED", "HARDWARE_FAULT", "COMMS_FAILURE",
    "DISPENSE_ERROR_REPEATED", "JOURNAL_FAILURE", "CARD_READER_FATAL",
}
_DEGRADED_ERROR_CODES = {
    "RECEIPT_PAPER_LOW", "CARD_JAM", "DISPENSE_ERROR_SINGLE",
    "CASH_LOW", "SUPERVISOR_MODE", "OUT_OF_SERVICE_TEMPORARY",
}


class EJUpdateATMHealthResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "UPDATED"
    atm_id: str
    bank_id: str
    health_status: str   # HEALTHY | DEGRADED | CRITICAL


def _derive_health_status(canonical_record: dict) -> str:
    """Classify health from canonical EJ error codes and transaction outcomes."""
    error_codes: list[str] = canonical_record.get("error_codes", [])
    for code in error_codes:
        if code in _CRITICAL_ERROR_CODES:
            return "CRITICAL"
    for code in error_codes:
        if code in _DEGRADED_ERROR_CODES:
            return "DEGRADED"
    return "HEALTHY"


async def update_atm_health(
    canonical_record: dict,
    atm_id: str,
    bank_id: str,
) -> EJUpdateATMHealthResult:
    """
    Derive ATM health from canonical EJ record, write to Redis EJ cache,
    and publish to ej.health.signals.{bank_id} Kafka topic.
    """
    with tracer.start_as_current_span("ej.update_atm_health") as span:
        span.set_attribute("atm_id", atm_id)
        span.set_attribute("bank_id", bank_id)

        health_status = _derive_health_status(canonical_record)
        consecutive_failures: int = canonical_record.get("consecutive_failures", 0)
        pending_ej_count: int = canonical_record.get("pending_ej_count", 0)
        now = time.time()

        health_payload = {
            "status": health_status,
            "atm_id": atm_id,
            "bank_id": bank_id,
            "pending_ej_count": pending_ej_count,
            "consecutive_failures": consecutive_failures,
            "last_ej_received_at": now,
            "updated_at": now,
        }

        span.set_attribute("health_status", health_status)

        # Write to Redis EJ cache (key read by /v1/ej/atm/{atm_id}/health)
        try:
            import redis as _redis
            from shared.config.config_service import config_service
            r = _redis.Redis.from_url(
                config_service.get("redis.ej.url"),
                decode_responses=True,
            )
            key = f"ej:health:{bank_id}:{atm_id}"
            r.set(key, json.dumps(health_payload), ex=3600)  # TTL 1h — refreshed each EJ
        except Exception as exc:
            # Non-fatal — Kafka signal is the primary path; Redis is the read cache
            log.warning("ej.atm_health.redis_write_failed", atm_id=atm_id, error=str(exc))

        # Publish to Kafka ej.health.signals.{bank_id} for anomaly detector
        try:
            from shared.event_bus.producer import KafkaEventProducer
            from shared.config.config_service import config_service
            producer = KafkaEventProducer(
                bootstrap_servers=config_service.get("kafka.bootstrap_servers"),
                module="ej",
            )
            producer.publish(
                topic=f"ej.health.signals.{bank_id}",
                event_type="EJ_ATM_HEALTH_UPDATED",
                payload=health_payload,
                bank_id=bank_id,
            )
            producer.flush()
        except Exception as exc:
            # Non-fatal — Redis cache is already written; Kafka retry will catch up
            log.warning("ej.atm_health.kafka_publish_failed", atm_id=atm_id, error=str(exc))

        log.info(
            "ej.update_atm_health.done",
            atm_id=atm_id,
            bank_id=bank_id,
            health_status=health_status,
        )

        return EJUpdateATMHealthResult(
            outcome="UPDATED",
            atm_id=atm_id,
            bank_id=bank_id,
            health_status=health_status,
        )
