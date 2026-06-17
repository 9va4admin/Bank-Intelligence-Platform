"""
EventProducer — Kafka producer for all ASTRA services.

Every message is wrapped in KafkaEventEnvelope before publishing.
Module isolation is enforced: a producer scoped to "cts" cannot publish
to "ej.*" topics, and vice versa. "platform.*" topics are always allowed.

Usage:
    producer = EventProducer(bootstrap_servers=..., bank_id=bank_id, module="cts")
    producer.connect()
    await producer.publish(
        topic=f"cts.inward.{bank_id}",
        event_type="CTS_INWARD",
        payload=cheque_event.model_dump(),
        schema_version="1.0",
    )
"""
import json
import structlog

from shared.event_bus.exceptions import EventBusUnavailableError
from shared.event_bus.schemas import KafkaEventEnvelope

log = structlog.get_logger()

# Topics starting with these prefixes are shared — any module may publish
_SHARED_TOPIC_PREFIXES = ("platform.",)


class EventProducer:
    def __init__(
        self,
        bootstrap_servers: str,
        bank_id: str,
        module: str = "",           # "cts" | "ej" | "" (unrestricted)
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._bank_id = bank_id
        self._module = module
        self._producer = None
        self._ready = False

    def connect(self) -> None:
        """
        Initialise the Kafka producer with exactly-once semantics settings.
        Called once at service startup.
        """
        try:
            from kafka import KafkaProducer  # type: ignore[import]
            self._producer = KafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                acks="all",                         # wait for all replicas
                enable_idempotence=True,            # exactly-once at producer level
                max_in_flight_requests_per_connection=1,
                value_serializer=lambda v: v,       # we serialise manually
                key_serializer=lambda k: k,
            )
        except Exception as exc:
            raise EventBusUnavailableError(f"Kafka producer connect failed: {exc}") from exc
        self._ready = True
        log.info("event_bus.producer.connected", servers=self._bootstrap_servers, module=self._module)

    async def publish(
        self,
        topic: str,
        event_type: str,
        payload: dict,
        schema_version: str,
    ) -> None:
        """
        Wrap payload in KafkaEventEnvelope and publish to the given topic.

        Kafka key = bank_id bytes — ensures all events for a bank go to the
        same partition (ordering guarantee within a bank's event stream).

        Raises ValueError on cross-module topic isolation violation.
        Raises EventBusUnavailableError on Kafka send failure.
        Raises RuntimeError if connect() not called.
        """
        self._assert_ready()
        self._assert_topic_isolation(topic)

        envelope = KafkaEventEnvelope(
            event_type=event_type,
            bank_id=self._bank_id,
            schema_version=schema_version,
            payload=payload,
        )
        value = envelope.model_dump_json().encode()
        key = self._bank_id.encode()

        try:
            self._producer.send(topic, value=value, key=key)
            self._producer.flush()
        except Exception as exc:
            log.error("event_bus.publish_failed", topic=topic, event_type=event_type, error=str(exc))
            raise EventBusUnavailableError(f"publish failed to topic '{topic}': {exc}") from exc

        log.info("event_bus.published", topic=topic, event_type=event_type, bank_id=self._bank_id)

    def _assert_topic_isolation(self, topic: str) -> None:
        if not self._module:
            return
        if any(topic.startswith(p) for p in _SHARED_TOPIC_PREFIXES):
            return
        # Determine the other module's prefix
        other = "ej" if self._module == "cts" else "cts"
        if topic.startswith(f"{other}."):
            raise ValueError(
                f"Module isolation violation: '{self._module}' producer attempted to publish "
                f"to '{topic}' which belongs to module '{other}'. "
                f"Cross-module Kafka publishing is forbidden."
            )

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "EventProducer.connect() has not been called. "
                "Call it in the service startup before publishing events."
            )
