"""
Tests for Kafka consumer — envelope deserialisation, schema version routing,
handler dispatch, and error paths.

TDD: written BEFORE the implementation.
"""
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio

from shared.event_bus.consumer import EventConsumer
from shared.event_bus.exceptions import EventBusUnavailableError, UnknownSchemaVersionError
from shared.event_bus.schemas import KafkaEventEnvelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_kafka_message(payload: dict, schema_version: str = "1.0", event_type: str = "CTS_INWARD") -> MagicMock:
    envelope = KafkaEventEnvelope(
        event_type=event_type,
        bank_id="test-bank",
        schema_version=schema_version,
        payload=payload,
    )
    msg = MagicMock()
    msg.value = envelope.model_dump_json().encode()
    msg.topic = "cts.inward.test-bank"
    msg.partition = 0
    msg.offset = 42
    return msg


@pytest.fixture
def consumer() -> EventConsumer:
    c = EventConsumer(
        bootstrap_servers="kafka:9092",
        group_id="cg-cts-agent-test-bank",
        bank_id="test-bank",
        topics=["cts.inward.test-bank"],
    )
    mock_kafka = MagicMock()
    mock_kafka.__iter__ = MagicMock(return_value=iter([]))
    mock_kafka.commit = MagicMock()
    c._consumer = mock_kafka
    c._ready = True
    return c


# ---------------------------------------------------------------------------
# Deserialisation
# ---------------------------------------------------------------------------

def test_deserialise_valid_message_returns_envelope(consumer):
    msg = _make_kafka_message({"instrument_id": "instr-001"})
    envelope = consumer._deserialise(msg)
    assert isinstance(envelope, KafkaEventEnvelope)
    assert envelope.event_type == "CTS_INWARD"
    assert envelope.bank_id == "test-bank"
    assert envelope.schema_version == "1.0"


def test_deserialise_preserves_payload(consumer):
    msg = _make_kafka_message({"instrument_id": "instr-001", "amount": 50000})
    envelope = consumer._deserialise(msg)
    assert envelope.payload["instrument_id"] == "instr-001"
    assert envelope.payload["amount"] == 50000


def test_deserialise_raises_on_corrupt_json(consumer):
    msg = MagicMock()
    msg.value = b"not-json{"
    with pytest.raises(ValueError, match="corrupt"):
        consumer._deserialise(msg)


# ---------------------------------------------------------------------------
# Schema version routing
# ---------------------------------------------------------------------------

def test_consumer_raises_on_unknown_schema_version(consumer):
    msg = _make_kafka_message({}, schema_version="99.0")
    envelope = consumer._deserialise(msg)
    with pytest.raises(UnknownSchemaVersionError, match="99.0"):
        consumer._assert_known_schema(envelope, supported_versions={"1.0", "2.0"})


def test_consumer_accepts_supported_schema_version(consumer):
    msg = _make_kafka_message({}, schema_version="1.0")
    envelope = consumer._deserialise(msg)
    consumer._assert_known_schema(envelope, supported_versions={"1.0", "2.0"})  # no exception


# ---------------------------------------------------------------------------
# Bank isolation — consumer rejects events for wrong bank
# ---------------------------------------------------------------------------

def test_consumer_ignores_event_for_different_bank(consumer):
    """Events from a different bank_id on the same topic must be skipped."""
    wrong_bank_envelope = KafkaEventEnvelope(
        event_type="CTS_INWARD",
        bank_id="other-bank",
        schema_version="1.0",
        payload={},
    )
    msg = MagicMock()
    msg.value = wrong_bank_envelope.model_dump_json().encode()

    # _should_process returns False for wrong bank
    envelope = consumer._deserialise(msg)
    assert consumer._should_process(envelope) is False


def test_consumer_processes_event_for_own_bank(consumer):
    msg = _make_kafka_message({"instrument_id": "instr-001"})
    envelope = consumer._deserialise(msg)
    assert consumer._should_process(envelope) is True


# ---------------------------------------------------------------------------
# Handler registration and dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_handler_and_dispatch(consumer):
    handler = AsyncMock()
    consumer.register_handler("CTS_INWARD", handler)

    msg = _make_kafka_message({"instrument_id": "instr-001"})
    envelope = consumer._deserialise(msg)
    await consumer._dispatch(envelope)

    handler.assert_awaited_once_with(envelope)


@pytest.mark.asyncio
async def test_dispatch_unknown_event_type_is_noop(consumer):
    """No handler registered for event type — must not raise."""
    msg = _make_kafka_message({}, event_type="UNKNOWN_TYPE")
    envelope = consumer._deserialise(msg)
    await consumer._dispatch(envelope)  # no exception


@pytest.mark.asyncio
async def test_dispatch_calls_correct_handler_by_event_type(consumer):
    handler_cts = AsyncMock()
    handler_vault = AsyncMock()
    consumer.register_handler("CTS_INWARD", handler_cts)
    consumer.register_handler("CTS_VAULT_SYNC", handler_vault)

    msg = _make_kafka_message({}, event_type="CTS_INWARD")
    envelope = consumer._deserialise(msg)
    await consumer._dispatch(envelope)

    handler_cts.assert_awaited_once()
    handler_vault.assert_not_awaited()


# ---------------------------------------------------------------------------
# connect / assert_ready
# ---------------------------------------------------------------------------

def test_assert_ready_raises_if_not_connected():
    c = EventConsumer(
        bootstrap_servers="kafka:9092",
        group_id="cg-cts",
        bank_id="test-bank",
        topics=["cts.inward.test-bank"],
    )
    with pytest.raises(RuntimeError, match="connect()"):
        c._assert_ready()


# ---------------------------------------------------------------------------
# connect() — success and failure paths
# ---------------------------------------------------------------------------

def test_connect_success_sets_ready(monkeypatch):
    """connect() with a mocked KafkaConsumer should set _ready=True."""
    import sys

    fake_kafka_consumer_instance = MagicMock()
    fake_kafka_consumer_class = MagicMock(return_value=fake_kafka_consumer_instance)
    fake_kafka_module = MagicMock()
    fake_kafka_module.KafkaConsumer = fake_kafka_consumer_class
    monkeypatch.setitem(sys.modules, "kafka", fake_kafka_module)

    c = EventConsumer(
        bootstrap_servers="kafka:9092",
        group_id="cg-cts-test-bank",
        bank_id="test-bank",
        topics=["cts.inward.test-bank"],
    )
    c.connect()

    assert c._ready is True
    assert c._consumer is fake_kafka_consumer_instance


def test_connect_failure_raises_event_bus_unavailable(monkeypatch):
    """connect() when KafkaConsumer raises must wrap in EventBusUnavailableError."""
    import sys

    fake_kafka_module = MagicMock()
    fake_kafka_module.KafkaConsumer.side_effect = Exception("broker unreachable")
    monkeypatch.setitem(sys.modules, "kafka", fake_kafka_module)

    c = EventConsumer(
        bootstrap_servers="kafka:9092",
        group_id="cg-cts-test-bank",
        bank_id="test-bank",
        topics=["cts.inward.test-bank"],
    )
    with pytest.raises(EventBusUnavailableError, match="consumer connect failed"):
        c.connect()


# ---------------------------------------------------------------------------
# run() — poll loop with messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_dispatches_two_messages(consumer):
    handler = AsyncMock()
    consumer.register_handler("CTS_INWARD", handler)

    msg1 = _make_kafka_message({"instrument_id": "instr-001"})
    msg2 = _make_kafka_message({"instrument_id": "instr-002"})
    consumer._consumer.__iter__ = MagicMock(return_value=iter([msg1, msg2]))

    await consumer.run()

    assert handler.await_count == 2
    consumer._consumer.commit.call_count == 2


@pytest.mark.asyncio
async def test_run_skips_unknown_schema_version(consumer):
    """UnknownSchemaVersionError during dispatch must log and continue — not crash."""
    # Register a handler that raises UnknownSchemaVersionError
    async def bad_handler(envelope):
        raise UnknownSchemaVersionError("schema 99.0 unknown")

    consumer.register_handler("CTS_INWARD", bad_handler)
    msg = _make_kafka_message({"instrument_id": "instr-001"})
    consumer._consumer.__iter__ = MagicMock(return_value=iter([msg]))

    # Must not raise — the loop handles UnknownSchemaVersionError internally
    await consumer.run()


@pytest.mark.asyncio
async def test_run_handles_generic_exception_without_crashing(consumer):
    """A generic Exception during dispatch must log and continue — not crash."""
    async def failing_handler(envelope):
        raise RuntimeError("unexpected error")

    consumer.register_handler("CTS_INWARD", failing_handler)
    msg = _make_kafka_message({"instrument_id": "instr-001"})
    consumer._consumer.__iter__ = MagicMock(return_value=iter([msg]))

    # Must not raise
    await consumer.run()


@pytest.mark.asyncio
async def test_run_skips_message_for_different_bank(consumer):
    """Messages for a different bank_id must be skipped (continue on line 76)."""
    handler = AsyncMock()
    consumer.register_handler("CTS_INWARD", handler)

    # Build a message for a different bank
    wrong_bank_envelope = KafkaEventEnvelope(
        event_type="CTS_INWARD",
        bank_id="other-bank",   # consumer is for "test-bank"
        schema_version="1.0",
        payload={"instrument_id": "instr-999"},
    )
    msg = MagicMock()
    msg.value = wrong_bank_envelope.model_dump_json().encode()
    msg.topic = "cts.inward.test-bank"
    msg.partition = 0
    msg.offset = 99

    consumer._consumer.__iter__ = MagicMock(return_value=iter([msg]))

    await consumer.run()

    # Handler must NOT have been called — message was skipped
    handler.assert_not_awaited()
