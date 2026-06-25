"""
Tests for Redis Streams audit buffer.

Verifies: XADD fields, MAXLEN cap, consumer group creation, consume+ack flow,
fail-open on Redis unavailability.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.audit.stream_buffer import (
    buffer_audit_event,
    ensure_consumer_group,
    consume_pending,
    acknowledge_messages,
    _stream_key,
)


class TestStreamKey:
    def test_key_includes_bank_id(self):
        key = _stream_key("hdfc-bank")
        assert "hdfc-bank" in key
        assert "audit" in key

    def test_different_banks_different_keys(self):
        k1 = _stream_key("hdfc")
        k2 = _stream_key("axis")
        assert k1 != k2


class TestBufferAuditEvent:
    @pytest.mark.asyncio
    async def test_returns_message_id_on_success(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1718012345678-0")

        msg_id = await buffer_audit_event(
            redis=redis,
            bank_id="hdfc",
            event_type="CTS_DECISION_FILED",
            entity_type="cheque_instrument",
            entity_id="INS-001",
            actor_id="cts-agent-worker",
            payload={"decision": "STP_CONFIRM", "fraud_score": 0.12},
        )
        assert msg_id == "1718012345678-0"

    @pytest.mark.asyncio
    async def test_xadd_called_with_correct_fields(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1234-0")

        await buffer_audit_event(
            redis=redis,
            bank_id="hdfc",
            event_type="CTS_DECISION_FILED",
            entity_type="cheque_instrument",
            entity_id="INS-001",
            actor_id="service",
            payload={"decision": "STP_CONFIRM"},
        )

        redis.xadd.assert_called_once()
        call_args = redis.xadd.call_args
        key, fields = call_args[0][0], call_args[0][1]
        assert "hdfc" in key
        assert fields["event_type"] == "CTS_DECISION_FILED"
        assert fields["bank_id"] == "hdfc"
        assert fields["entity_id"] == "INS-001"
        payload_data = json.loads(fields["payload"])
        assert payload_data["decision"] == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_xadd_uses_maxlen_cap(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1234-0")

        await buffer_audit_event(
            redis=redis,
            bank_id="hdfc",
            event_type="TEST_EVENT",
            entity_type="test",
            entity_id="e1",
            actor_id="svc",
            payload={},
        )

        call_kwargs = redis.xadd.call_args.kwargs
        assert "maxlen" in call_kwargs
        assert call_kwargs["maxlen"] == 1000

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_is_none(self):
        """Fail-open: no Redis → returns None, caller uses Kafka path."""
        msg_id = await buffer_audit_event(
            redis=None,
            bank_id="hdfc",
            event_type="TEST_EVENT",
            entity_type="test",
            entity_id="e1",
            actor_id="svc",
            payload={},
        )
        assert msg_id is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(side_effect=ConnectionError("Redis down"))

        msg_id = await buffer_audit_event(
            redis=redis,
            bank_id="hdfc",
            event_type="TEST_EVENT",
            entity_type="test",
            entity_id="e1",
            actor_id="svc",
            payload={},
        )
        assert msg_id is None

    @pytest.mark.asyncio
    async def test_hsm_signed_flag_stored_in_fields(self):
        redis = AsyncMock()
        redis.xadd = AsyncMock(return_value="1234-0")

        await buffer_audit_event(
            redis=redis,
            bank_id="hdfc",
            event_type="AUDIT_SIGNED",
            entity_type="test",
            entity_id="e1",
            actor_id="audit-svc",
            payload={},
            hsm_signed=True,
        )

        fields = redis.xadd.call_args[0][1]
        assert fields["hsm_signed"] == "true"


class TestEnsureConsumerGroup:
    @pytest.mark.asyncio
    async def test_creates_group_on_first_call(self):
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(return_value=True)
        await ensure_consumer_group(redis, "hdfc")
        redis.xgroup_create.assert_called_once()
        call_args = redis.xgroup_create.call_args
        assert "hdfc" in str(call_args)

    @pytest.mark.asyncio
    async def test_ignores_busygroup_error(self):
        """Group already exists — should not raise."""
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(
            side_effect=Exception("BUSYGROUP Consumer Group name already exists")
        )
        # Should NOT raise
        await ensure_consumer_group(redis, "hdfc")

    @pytest.mark.asyncio
    async def test_uses_mkstream_true(self):
        """mkstream=True creates stream if it doesn't exist yet."""
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(return_value=True)
        await ensure_consumer_group(redis, "hdfc")
        call_kwargs = redis.xgroup_create.call_args.kwargs
        assert call_kwargs.get("mkstream") is True


class TestConsumePending:
    @pytest.mark.asyncio
    async def test_returns_messages_from_stream(self):
        redis = AsyncMock()
        # xreadgroup returns: [(stream_key, [(msg_id, fields_dict), ...])]
        stream_key = b"audit:hdfc:stream"
        redis.xreadgroup = AsyncMock(return_value=[
            (stream_key, [
                ("1234-0", {"event_type": "CTS_DECISION_FILED", "bank_id": "hdfc"}),
                ("1234-1", {"event_type": "EJ_CANONICAL_STORED", "bank_id": "hdfc"}),
            ])
        ])

        messages = await consume_pending(redis, "hdfc", "consumer-1", batch_size=10)
        assert len(messages) == 2
        assert messages[0][0] == "1234-0"
        assert messages[1][0] == "1234-1"

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_messages(self):
        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=None)
        messages = await consume_pending(redis, "hdfc", "consumer-1")
        assert messages == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_redis_error(self):
        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=ConnectionError("Redis down"))
        messages = await consume_pending(redis, "hdfc", "consumer-1")
        assert messages == []


class TestAcknowledgeMessages:
    @pytest.mark.asyncio
    async def test_calls_xack_with_message_ids(self):
        redis = AsyncMock()
        redis.xack = AsyncMock(return_value=2)
        await acknowledge_messages(redis, "hdfc", ["1234-0", "1234-1"])
        redis.xack.assert_called_once()
        call_args = redis.xack.call_args[0]
        assert "1234-0" in call_args
        assert "1234-1" in call_args

    @pytest.mark.asyncio
    async def test_skips_empty_list(self):
        redis = AsyncMock()
        await acknowledge_messages(redis, "hdfc", [])
        redis.xack.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self):
        redis = AsyncMock()
        redis.xack = AsyncMock(side_effect=ConnectionError("Redis down"))
        # Should not raise
        await acknowledge_messages(redis, "hdfc", ["1234-0"])
