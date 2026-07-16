"""
Tests for shared/audit/stream_consumer.py -- AuditStreamConsumer.

This is the "audit-service consumer" shared/audit/stream_buffer.py's own
docstring names as the thing that drains the Redis Stream and writes to
Immudb -- buffer_audit_event() (producer) and the raw consume/ack
primitives already existed and were tested; nothing ever tied them
together into the actual continuous loop. This does.

TDD: written BEFORE the implementation.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call


def _make_consumer(redis=None, immudb_writer=None, hsm=None, bank_id="hdfc"):
    from shared.audit.stream_consumer import AuditStreamConsumer
    return AuditStreamConsumer(
        redis_client=redis or AsyncMock(),
        immudb_writer=immudb_writer or AsyncMock(),
        hsm=hsm,
        bank_id=bank_id,
        consumer_name="audit-svc-1",
    )


def _stream_fields(event_type="CTS_DECISION_FILED", bank_id="hdfc", entity_id="INS-1", payload=None):
    return {
        "event_id": "evt-1",
        "event_type": event_type,
        "bank_id": bank_id,
        "entity_type": "cheque_instrument",
        "entity_id": entity_id,
        "actor_id": "cts-agent-worker",
        "timestamp": "1718012345.0",
        "hsm_signed": "false",
        "payload": json.dumps(payload or {"decision": "STP_CONFIRM"}),
    }


class TestProcessBatchHappyPath:
    @pytest.mark.asyncio
    async def test_writes_each_message_to_immudb(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb)

        await consumer._process_batch([("1-0", _stream_fields())])

        immudb.write.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_uses_bank_scoped_collection(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb, bank_id="hdfc")

        await consumer._process_batch([("1-0", _stream_fields(bank_id="hdfc"))])

        kwargs = immudb.write.call_args.kwargs
        assert kwargs["collection"] == "cts_hdfc"

    @pytest.mark.asyncio
    async def test_write_passes_entity_id_as_instrument_id(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb)

        await consumer._process_batch([("1-0", _stream_fields(entity_id="INS-77"))])

        kwargs = immudb.write.call_args.kwargs
        assert kwargs["instrument_id"] == "INS-77"

    @pytest.mark.asyncio
    async def test_write_passes_decoded_payload(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb)

        await consumer._process_batch([("1-0", _stream_fields(payload={"fraud_score": 0.42}))])

        kwargs = immudb.write.call_args.kwargs
        assert kwargs["payload"]["fraud_score"] == 0.42

    @pytest.mark.asyncio
    async def test_acknowledges_successfully_written_messages(self):
        redis = AsyncMock()
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(redis=redis, immudb_writer=immudb)

        await consumer._process_batch([("1-0", _stream_fields())])

        redis.xack.assert_called_once()
        acked_ids = redis.xack.call_args[0][2:]
        assert "1-0" in acked_ids


class TestHsmSigning:
    @pytest.mark.asyncio
    async def test_signs_when_hsm_available(self):
        fake_hsm = MagicMock()
        fake_hsm.sign = MagicMock(return_value=b"signature-bytes")
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb, hsm=fake_hsm)

        await consumer._process_batch([("1-0", _stream_fields())])

        fake_hsm.sign.assert_called_once()
        kwargs = immudb.write.call_args.kwargs
        assert kwargs["payload"].get("signature") is not None

    @pytest.mark.asyncio
    async def test_writes_unsigned_with_warning_when_hsm_unavailable(self):
        """Deliberate choice: matching the existing skip-entirely-if-hsm-is-
        None pattern elsewhere (decision.py) would mean this consumer never
        writes anything until the (separately tracked, not-yet-built) HSM
        backend exists -- reproducing the exact 'looks wired, does nothing'
        problem this consumer exists to fix. Writes unsigned instead, with
        a loud warning, so the audit record actually exists today."""
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        consumer = _make_consumer(immudb_writer=immudb, hsm=None)

        await consumer._process_batch([("1-0", _stream_fields())])

        immudb.write.assert_awaited_once()
        kwargs = immudb.write.call_args.kwargs
        assert kwargs["payload"].get("signature") is None


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_one_bad_message_does_not_block_the_rest_of_the_batch(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(side_effect=[Exception("immudb down"), "TX-2"])
        redis = AsyncMock()
        consumer = _make_consumer(redis=redis, immudb_writer=immudb)

        await consumer._process_batch([
            ("1-0", _stream_fields(entity_id="INS-BAD")),
            ("1-1", _stream_fields(entity_id="INS-GOOD")),
        ])

        assert immudb.write.await_count == 2

    @pytest.mark.asyncio
    async def test_failed_message_is_not_acknowledged(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(side_effect=Exception("immudb down"))
        redis = AsyncMock()
        consumer = _make_consumer(redis=redis, immudb_writer=immudb)

        await consumer._process_batch([("1-0", _stream_fields())])

        redis.xack.assert_not_called()

    @pytest.mark.asyncio
    async def test_succeeded_messages_acknowledged_even_when_another_fails(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(side_effect=[Exception("boom"), "TX-2"])
        redis = AsyncMock()
        consumer = _make_consumer(redis=redis, immudb_writer=immudb)

        await consumer._process_batch([
            ("1-0", _stream_fields()),
            ("1-1", _stream_fields()),
        ])

        redis.xack.assert_called_once()
        acked_ids = redis.xack.call_args[0][2:]
        assert acked_ids == ("1-1",)

    @pytest.mark.asyncio
    async def test_malformed_payload_json_does_not_crash_the_batch(self):
        immudb = AsyncMock()
        immudb.write = AsyncMock(return_value="TX-1")
        redis = AsyncMock()
        consumer = _make_consumer(redis=redis, immudb_writer=immudb)

        bad_fields = _stream_fields()
        bad_fields["payload"] = "{not valid json"

        await consumer._process_batch([
            ("1-0", bad_fields),
            ("1-1", _stream_fields()),
        ])

        # The malformed one is skipped (not acked); the good one still writes+acks.
        immudb.write.assert_awaited_once()
        redis.xack.assert_called_once()
        acked_ids = redis.xack.call_args[0][2:]
        assert acked_ids == ("1-1",)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_ensures_consumer_group(self):
        redis = AsyncMock()
        consumer = _make_consumer(redis=redis, bank_id="hdfc")

        await consumer.start()
        consumer._running = False   # stop the background task from looping further

        redis.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        consumer = _make_consumer()
        consumer._running = True
        await consumer.stop()
        assert consumer._running is False
