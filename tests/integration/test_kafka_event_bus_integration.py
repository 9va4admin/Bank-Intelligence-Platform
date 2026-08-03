"""
Real Kafka integration tests for shared/event_bus/producer.py and consumer.py
— against astra-it-kafka (infra/docker-compose.integration.yml), not a mock.

EventConsumer.run() is a blocking `for message in self._consumer:` loop
(kafka-python's KafkaConsumer iterator has no async support and no built-in
timeout) wrapped in `async def` -- there is no clean, non-flaky way to start
and stop it from inside a single-threaded pytest-asyncio test. Rather than
fight kafka-python's thread-safety story (KafkaConsumer is documented as not
safe for concurrent use across threads, which is what stopping a background
`.run()` thread from the test thread would require), these tests exercise
the same real Kafka bytes-over-the-wire path through the pieces that ARE
safely callable synchronously: EventProducer.publish() for real, and
EventConsumer's own already-connected KafkaConsumer via .poll() (a bounded,
timeout-based call the class's constructor already sets up) instead of
.run()'s unbounded iterator. Every deserialisation/isolation/dispatch method
this exercises is the exact same code .run() would call -- only the
outermost "loop forever" wrapper is bypassed.
"""
import json
import time
import uuid

import pytest

from shared.event_bus.consumer import EventConsumer
from shared.event_bus.producer import EventProducer
from shared.event_bus.schemas import KafkaEventEnvelope

pytestmark = pytest.mark.integration

KAFKA_BOOTSTRAP = "localhost:9093"


@pytest.fixture
def bank_id() -> str:
    return f"it-bank-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def topic(bank_id) -> str:
    # Unique-ish topic per test run -- KAFKA_AUTO_CREATE_TOPICS_ENABLE=true on
    # the integration container, so no manual topic provisioning needed.
    return f"cts.it.{bank_id}"


class TestEventProducerAgainstRealKafka:
    def test_publish_lands_a_real_message_readable_by_a_plain_consumer(self, bank_id, topic):
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=bank_id, module="cts")
        producer.connect()

        import asyncio
        asyncio.run(
            producer.publish(
                topic=topic, event_type="CTS_IT_TEST", payload={"instrument_id": "instr-it-1"},
                schema_version="1.0",
            )
        )

        from kafka import KafkaConsumer
        raw_consumer = KafkaConsumer(
            topic, bootstrap_servers=KAFKA_BOOTSTRAP, auto_offset_reset="earliest",
            enable_auto_commit=False, consumer_timeout_ms=8000,
        )
        try:
            records = list(raw_consumer)
        finally:
            raw_consumer.close()

        assert len(records) == 1
        envelope = KafkaEventEnvelope.model_validate(json.loads(records[0].value))
        assert envelope.event_type == "CTS_IT_TEST"
        assert envelope.bank_id == bank_id
        assert envelope.schema_version == "1.0"
        assert envelope.payload == {"instrument_id": "instr-it-1"}
        # Kafka key = bank_id bytes -- ordering-by-bank guarantee producer.py promises.
        assert records[0].key == bank_id.encode()

    def test_cross_module_publish_is_rejected_before_any_network_call(self, bank_id):
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=bank_id, module="cts")
        producer.connect()

        import asyncio
        with pytest.raises(ValueError, match="Module isolation violation"):
            asyncio.run(
                producer.publish(
                    topic=f"ej.raw.ingested.{bank_id}", event_type="EJ_IT_TEST",
                    payload={}, schema_version="1.0",
                )
            )

    def test_platform_prefixed_topic_allowed_from_any_module(self, bank_id):
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=bank_id, module="cts")
        producer.connect()

        import asyncio
        # Must not raise -- platform.* is the documented shared-topic exception.
        asyncio.run(
            producer.publish(
                topic="platform.audit.events", event_type="CTS_IT_AUDIT_PROBE",
                payload={"probe": True}, schema_version="1.0",
            )
        )


class TestEventConsumerAgainstRealKafka:
    def test_connect_and_poll_receives_a_real_published_message(self, bank_id, topic):
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=bank_id, module="cts")
        producer.connect()

        import asyncio
        asyncio.run(
            producer.publish(
                topic=topic, event_type="CTS_IT_CONSUME_TEST",
                payload={"foo": "bar"}, schema_version="1.0",
            )
        )

        consumer = EventConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=f"cg-it-{uuid.uuid4().hex[:8]}",
            bank_id=bank_id,
            topics=[topic],
        )
        consumer.connect()
        try:
            # Bounded poll -- same underlying KafkaConsumer .run() would iterate,
            # just with an explicit timeout instead of blocking forever.
            records = None
            for _ in range(10):
                polled = consumer._consumer.poll(timeout_ms=1000)
                if polled:
                    records = polled
                    break
            assert records is not None, "no message received within poll window"

            messages = [m for batch in records.values() for m in batch]
            assert len(messages) == 1
            envelope = consumer._deserialise(messages[0])
            assert envelope.event_type == "CTS_IT_CONSUME_TEST"
            assert envelope.bank_id == bank_id
            assert consumer._should_process(envelope) is True
        finally:
            consumer._consumer.close()

    @pytest.mark.asyncio
    async def test_dispatch_invokes_the_registered_handler_for_real_message(self, bank_id, topic):
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=bank_id, module="cts")
        producer.connect()
        await producer.publish(
            topic=topic, event_type="CTS_IT_DISPATCH_TEST",
            payload={"decision": "STP_CONFIRM"}, schema_version="1.0",
        )

        consumer = EventConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=f"cg-it-{uuid.uuid4().hex[:8]}",
            bank_id=bank_id,
            topics=[topic],
        )
        consumer.connect()

        received = []

        async def handler(envelope: KafkaEventEnvelope) -> None:
            received.append(envelope)

        consumer.register_handler("CTS_IT_DISPATCH_TEST", handler)

        try:
            records = None
            for _ in range(10):
                polled = consumer._consumer.poll(timeout_ms=1000)
                if polled:
                    records = polled
                    break
            assert records is not None

            for batch in records.values():
                for message in batch:
                    envelope = consumer._deserialise(message)
                    if consumer._should_process(envelope):
                        await consumer._dispatch(envelope)
        finally:
            consumer._consumer.close()

        assert len(received) == 1
        assert received[0].payload == {"decision": "STP_CONFIRM"}

    def test_message_for_a_different_bank_id_is_filtered_out(self, bank_id, topic):
        """_should_process enforces bank_id isolation -- a message published under a
        DIFFERENT bank_id landing on the same topic must not be processed."""
        other_bank_id = f"it-bank-{uuid.uuid4().hex[:8]}"
        producer = EventProducer(bootstrap_servers=KAFKA_BOOTSTRAP, bank_id=other_bank_id, module="cts")
        producer.connect()

        import asyncio
        asyncio.run(
            producer.publish(
                topic=topic, event_type="CTS_IT_WRONG_BANK",
                payload={}, schema_version="1.0",
            )
        )

        consumer = EventConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=f"cg-it-{uuid.uuid4().hex[:8]}",
            bank_id=bank_id,  # different from the publisher's bank_id
            topics=[topic],
        )
        consumer.connect()
        try:
            records = None
            for _ in range(10):
                polled = consumer._consumer.poll(timeout_ms=1000)
                if polled:
                    records = polled
                    break
            assert records is not None
            messages = [m for batch in records.values() for m in batch]
            envelope = consumer._deserialise(messages[0])
            assert consumer._should_process(envelope) is False
        finally:
            consumer._consumer.close()
