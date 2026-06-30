"""
Tests for Kafka producer — envelope wrapping, schema_version, topic routing,
exactly-once semantics config, and error handling.

TDD: written BEFORE the implementation.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from shared.event_bus.producer import EventProducer
from shared.event_bus.exceptions import EventBusUnavailableError
from shared.event_bus.schemas import KafkaEventEnvelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def producer() -> EventProducer:
    p = EventProducer(bootstrap_servers="kafka:9092", bank_id="test-bank")
    mock_producer = MagicMock()
    mock_producer.send = MagicMock(return_value=MagicMock())
    mock_producer.flush = MagicMock()
    p._producer = mock_producer
    p._ready = True
    return p


# ---------------------------------------------------------------------------
# KafkaEventEnvelope schema
# ---------------------------------------------------------------------------

def test_envelope_has_required_fields():
    env = KafkaEventEnvelope(
        event_type="CTS_INWARD",
        bank_id="test-bank",
        schema_version="1.0",
        payload={"instrument_id": "instr-001"},
    )
    assert env.event_id is not None
    assert env.schema_version == "1.0"
    assert env.bank_id == "test-bank"


def test_envelope_auto_generates_event_id():
    e1 = KafkaEventEnvelope(event_type="X", bank_id="b", schema_version="1.0", payload={})
    e2 = KafkaEventEnvelope(event_type="X", bank_id="b", schema_version="1.0", payload={})
    assert e1.event_id != e2.event_id


def test_envelope_is_json_serialisable():
    env = KafkaEventEnvelope(
        event_type="CTS_INWARD",
        bank_id="test-bank",
        schema_version="1.0",
        payload={"key": "value"},
    )
    raw = env.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["event_type"] == "CTS_INWARD"
    assert "event_id" in parsed
    assert "timestamp" in parsed


def test_envelope_missing_schema_version_raises():
    with pytest.raises(Exception):
        KafkaEventEnvelope(event_type="X", bank_id="b", payload={})  # schema_version required


# ---------------------------------------------------------------------------
# EventProducer.publish — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_calls_kafka_send(producer):
    await producer.publish(
        topic="cts.inward.test-bank",
        event_type="CTS_INWARD",
        payload={"instrument_id": "instr-001"},
        schema_version="1.0",
    )
    producer._producer.send.assert_called_once()


@pytest.mark.asyncio
async def test_publish_wraps_in_envelope(producer):
    await producer.publish(
        topic="cts.inward.test-bank",
        event_type="CTS_INWARD",
        payload={"instrument_id": "instr-001"},
        schema_version="1.0",
    )
    call_args = producer._producer.send.call_args
    topic_sent = call_args[0][0]
    value_sent = call_args[1].get("value") or call_args[0][1]
    parsed = json.loads(value_sent)

    assert topic_sent == "cts.inward.test-bank"
    assert parsed["event_type"] == "CTS_INWARD"
    assert parsed["bank_id"] == "test-bank"
    assert parsed["schema_version"] == "1.0"
    assert "event_id" in parsed


@pytest.mark.asyncio
async def test_publish_uses_bank_id_as_key(producer):
    """Kafka key = bank_id ensures all events for a bank go to same partition."""
    await producer.publish(
        topic="cts.inward.test-bank",
        event_type="CTS_INWARD",
        payload={},
        schema_version="1.0",
    )
    call_args = producer._producer.send.call_args
    key_sent = call_args[1].get("key") or (call_args[0][2] if len(call_args[0]) > 2 else None)
    assert key_sent == b"test-bank"


@pytest.mark.asyncio
async def test_publish_flushes_after_send(producer):
    await producer.publish(
        topic="cts.decisions.test-bank",
        event_type="CTS_DECISION",
        payload={"decision": "STP_CONFIRM"},
        schema_version="1.0",
    )
    producer._producer.flush.assert_called_once()


# ---------------------------------------------------------------------------
# EventProducer.publish — error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_raises_if_not_ready():
    p = EventProducer(bootstrap_servers="kafka:9092", bank_id="test-bank")
    with pytest.raises(RuntimeError, match="connect()"):
        await p.publish(topic="t", event_type="E", payload={}, schema_version="1.0")


@pytest.mark.asyncio
async def test_publish_raises_event_bus_unavailable_on_kafka_error(producer):
    producer._producer.send.side_effect = Exception("leader not available")
    with pytest.raises(EventBusUnavailableError, match="publish failed"):
        await producer.publish(
            topic="cts.inward.test-bank",
            event_type="CTS_INWARD",
            payload={},
            schema_version="1.0",
        )


# ---------------------------------------------------------------------------
# Topic naming guard — CTS/EJ isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cts_producer_cannot_publish_to_ej_topic(producer):
    """CTS producers must not cross into ej.* topics."""
    producer._module = "cts"
    with pytest.raises(ValueError, match="isolation"):
        await producer.publish(
            topic="ej.canonical.test-bank",
            event_type="EJ_PARSED",
            payload={},
            schema_version="1.0",
        )


@pytest.mark.asyncio
async def test_ej_producer_cannot_publish_to_cts_topic():
    p = EventProducer(bootstrap_servers="kafka:9092", bank_id="test-bank", module="ej")
    p._producer = MagicMock()
    p._producer.send = MagicMock(return_value=MagicMock())
    p._producer.flush = MagicMock()
    p._ready = True

    with pytest.raises(ValueError, match="isolation"):
        await p.publish(
            topic="cts.inward.test-bank",
            event_type="CTS_INWARD",
            payload={},
            schema_version="1.0",
        )


@pytest.mark.asyncio
async def test_platform_topic_allowed_from_any_module(producer):
    """platform.* topics (audit, notifications, config) are shared — always allowed."""
    producer._module = "cts"
    await producer.publish(
        topic="platform.audit.events",
        event_type="AUDIT_WRITE",
        payload={"event_type": "CTS_DECISION"},
        schema_version="1.0",
    )
    producer._producer.send.assert_called_once()


# ---------------------------------------------------------------------------
# connect() — success and failure paths
# ---------------------------------------------------------------------------

def test_connect_success_sets_ready(monkeypatch):
    """connect() with a mocked KafkaProducer should set _ready=True."""
    import sys

    fake_producer_instance = MagicMock()
    fake_kafka_module = MagicMock()
    fake_kafka_module.KafkaProducer.return_value = fake_producer_instance
    monkeypatch.setitem(sys.modules, "kafka", fake_kafka_module)

    p = EventProducer(bootstrap_servers="kafka:9092", bank_id="test-bank", module="cts")
    p.connect()

    assert p._ready is True
    assert p._producer is fake_producer_instance


def test_connect_failure_raises_event_bus_unavailable(monkeypatch):
    """connect() when KafkaProducer raises must wrap in EventBusUnavailableError."""
    import sys

    fake_kafka_module = MagicMock()
    fake_kafka_module.KafkaProducer.side_effect = Exception("broker unavailable")
    monkeypatch.setitem(sys.modules, "kafka", fake_kafka_module)

    p = EventProducer(bootstrap_servers="kafka:9092", bank_id="test-bank")
    with pytest.raises(EventBusUnavailableError, match="producer connect failed"):
        p.connect()
