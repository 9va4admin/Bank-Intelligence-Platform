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
