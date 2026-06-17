"""
EventConsumer — Kafka consumer for all ASTRA services.

Handles envelope deserialisation, bank_id isolation, schema version routing,
and handler dispatch. Each service registers async handlers per event_type.

Usage:
    consumer = EventConsumer(
        bootstrap_servers=...,
        group_id=f"cg-cts-agent-{bank_id}",
        bank_id=bank_id,
        topics=[f"cts.inward.{bank_id}"],
    )
    consumer.connect()
    consumer.register_handler("CTS_INWARD", handle_inward_cheque)
    await consumer.run()   # blocking poll loop
"""
import json
from typing import Any, Callable, Coroutine

import structlog

from shared.event_bus.exceptions import EventBusUnavailableError, UnknownSchemaVersionError
from shared.event_bus.schemas import KafkaEventEnvelope

log = structlog.get_logger()

Handler = Callable[[KafkaEventEnvelope], Coroutine[Any, Any, None]]


class EventConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        bank_id: str,
        topics: list[str],
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._bank_id = bank_id
        self._topics = topics
        self._consumer = None
        self._ready = False
        self._handlers: dict[str, Handler] = {}

    def connect(self) -> None:
        """Initialise Kafka consumer. Called once at service startup."""
        try:
            from kafka import KafkaConsumer  # type: ignore[import]
            self._consumer = KafkaConsumer(
                *self._topics,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=False,       # manual commit after successful processing
                value_deserializer=lambda v: v, # we deserialise manually
            )
        except Exception as exc:
            raise EventBusUnavailableError(f"Kafka consumer connect failed: {exc}") from exc
        self._ready = True
        log.info("event_bus.consumer.connected",
                 group_id=self._group_id, topics=self._topics, bank_id=self._bank_id)

    def register_handler(self, event_type: str, handler: Handler) -> None:
        """Register an async handler for a specific event_type."""
        self._handlers[event_type] = handler

    async def run(self) -> None:
        """Poll loop — runs until cancelled."""
        self._assert_ready()
        for message in self._consumer:
            try:
                envelope = self._deserialise(message)
                if not self._should_process(envelope):
                    continue
                await self._dispatch(envelope)
                self._consumer.commit()
            except UnknownSchemaVersionError:
                log.error("event_bus.unknown_schema",
                          topic=message.topic, offset=message.offset)
            except Exception as exc:
                log.error("event_bus.processing_error",
                          topic=message.topic, offset=message.offset, error=str(exc))

    # ------------------------------------------------------------------
    # Internal helpers (public for testability)
    # ------------------------------------------------------------------

    def _deserialise(self, message) -> KafkaEventEnvelope:
        try:
            data = json.loads(message.value)
            return KafkaEventEnvelope.model_validate(data)
        except Exception as exc:
            raise ValueError(f"corrupt Kafka message at offset {message.offset}: {exc}") from exc

    def _should_process(self, envelope: KafkaEventEnvelope) -> bool:
        return envelope.bank_id == self._bank_id

    def _assert_known_schema(
        self, envelope: KafkaEventEnvelope, supported_versions: set[str]
    ) -> None:
        if envelope.schema_version not in supported_versions:
            raise UnknownSchemaVersionError(
                f"Unknown schema_version '{envelope.schema_version}' for event "
                f"'{envelope.event_type}'. Supported: {supported_versions}"
            )

    async def _dispatch(self, envelope: KafkaEventEnvelope) -> None:
        handler = self._handlers.get(envelope.event_type)
        if handler is None:
            log.debug("event_bus.no_handler",
                      event_type=envelope.event_type, bank_id=envelope.bank_id)
            return
        await handler(envelope)

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "EventConsumer.connect() has not been called. "
                "Call it in the service startup before running the consumer."
            )
