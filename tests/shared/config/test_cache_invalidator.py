"""
Tests for shared/config/cache_invalidator.py

CacheInvalidator consumes platform.config.changed Kafka events and
evicts the matching Redis cache keys so config_service serves fresh
values within the 30-second TTL window.

Coverage targets:
  [ ] start() subscribes to TOPIC and creates background task
  [ ] stop() sets _running=False and calls consumer.close()
  [ ] _handle_event: bank_id mismatch → no Redis delete
  [ ] _handle_event: specific key → deletes exact cache key
  [ ] _handle_event: no key → flushes all config:bank_id:* keys via scan
  [ ] _consume_loop: None message → skips without error
  [ ] _consume_loop: error message → skips without error
  [ ] _consume_loop: valid message → calls _handle_event
  [ ] _consume_loop: exception in handler → logs error, continues (no crash)
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from shared.config.cache_invalidator import CacheInvalidator, TOPIC


def _make_msg(value: dict, error=None):
    msg = MagicMock()
    msg.value.return_value = json.dumps(value).encode()
    msg.error.return_value = error
    return msg


def _make_error_msg():
    msg = MagicMock()
    msg.error.return_value = "some kafka error"
    return msg


@pytest.fixture
def redis():
    r = AsyncMock()
    r.delete = AsyncMock(return_value=1)
    r.scan = AsyncMock(return_value=(0, []))
    return r


@pytest.fixture
def consumer():
    c = MagicMock()
    c.subscribe = MagicMock()
    c.close = MagicMock()
    c.poll = MagicMock(return_value=None)
    return c


@pytest.fixture
def invalidator(consumer, redis):
    return CacheInvalidator(consumer, redis, bank_id="test-bank")


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_subscribes_to_topic(invalidator, consumer):
    with patch("asyncio.create_task"):
        await invalidator.start()
    consumer.subscribe.assert_called_once_with([TOPIC])


@pytest.mark.asyncio
async def test_start_sets_running_true(invalidator):
    with patch("asyncio.create_task"):
        await invalidator.start()
    assert invalidator._running is True


@pytest.mark.asyncio
async def test_stop_sets_running_false(invalidator):
    invalidator._running = True
    await invalidator.stop()
    assert invalidator._running is False


@pytest.mark.asyncio
async def test_stop_closes_consumer(invalidator, consumer):
    await invalidator.stop()
    consumer.close.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_event — bank_id filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_event_wrong_bank_id_no_delete(invalidator, redis):
    await invalidator._handle_event({"bank_id": "other-bank", "config_key": "cts.iet_minutes"})
    redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_missing_bank_id_no_delete(invalidator, redis):
    await invalidator._handle_event({"config_key": "cts.iet_minutes"})
    redis.delete.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_event — specific key eviction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_event_specific_key_deletes_cache_key(invalidator, redis):
    await invalidator._handle_event({"bank_id": "test-bank", "config_key": "cts.iet_minutes"})
    redis.delete.assert_called_once_with("config:test-bank:cts.iet_minutes")


@pytest.mark.asyncio
async def test_handle_event_specific_key_correct_format(invalidator, redis):
    await invalidator._handle_event({"bank_id": "test-bank", "config_key": "ej.llm_field_min_confidence"})
    redis.delete.assert_called_once_with("config:test-bank:ej.llm_field_min_confidence")


# ---------------------------------------------------------------------------
# _handle_event — flush all (no specific key)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_event_no_key_scans_all_config_keys(invalidator, redis):
    redis.scan = AsyncMock(return_value=(0, []))
    await invalidator._handle_event({"bank_id": "test-bank"})
    redis.scan.assert_called_once_with(0, match="config:test-bank:*", count=100)


@pytest.mark.asyncio
async def test_handle_event_no_key_deletes_found_keys(invalidator, redis):
    found_keys = ["config:test-bank:cts.iet_minutes", "config:test-bank:cts.stp_threshold"]
    redis.scan = AsyncMock(return_value=(0, found_keys))
    await invalidator._handle_event({"bank_id": "test-bank"})
    redis.delete.assert_called_once_with(*found_keys)


@pytest.mark.asyncio
async def test_handle_event_no_key_empty_scan_no_delete(invalidator, redis):
    redis.scan = AsyncMock(return_value=(0, []))
    await invalidator._handle_event({"bank_id": "test-bank"})
    redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_no_key_paginates_scan(invalidator, redis):
    """scan returns non-zero cursor first → continues until cursor==0."""
    batch1 = ["config:test-bank:key1"]
    batch2 = ["config:test-bank:key2"]
    redis.scan = AsyncMock(side_effect=[
        (42, batch1),   # first call: cursor=42, has keys
        (0,  batch2),   # second call: cursor=0, done
    ])
    await invalidator._handle_event({"bank_id": "test-bank"})
    assert redis.delete.call_count == 2


# ---------------------------------------------------------------------------
# _consume_loop behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consume_loop_none_message_skips(invalidator, consumer):
    consumer.poll.return_value = None
    invalidator._running = True

    async def _stop_after_one():
        await asyncio.sleep(0.05)
        invalidator._running = False

    await asyncio.gather(
        invalidator._consume_loop(),
        _stop_after_one(),
    )
    # No exception raised — test passes if we reach here


@pytest.mark.asyncio
async def test_consume_loop_error_message_skips(invalidator, consumer):
    consumer.poll.return_value = _make_error_msg()
    invalidator._running = True

    async def _stop_after_one():
        await asyncio.sleep(0.05)
        invalidator._running = False

    await asyncio.gather(
        invalidator._consume_loop(),
        _stop_after_one(),
    )


@pytest.mark.asyncio
async def test_consume_loop_valid_message_calls_handle_event(invalidator, consumer, redis):
    event = {"bank_id": "test-bank", "config_key": "cts.iet_minutes"}
    msg = _make_msg(event)

    # Yield one valid message then stop
    call_count = 0
    def _poll(timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return msg
        invalidator._running = False
        return None

    consumer.poll.side_effect = _poll

    invalidator._running = True
    await invalidator._consume_loop()

    redis.delete.assert_called_once_with("config:test-bank:cts.iet_minutes")


@pytest.mark.asyncio
async def test_consume_loop_exception_does_not_crash(invalidator, consumer, redis):
    """Handler exception → logs error, keeps running (no propagation)."""
    consumer.poll.side_effect = Exception("network error")
    invalidator._running = True

    async def _stop():
        await asyncio.sleep(0.15)
        invalidator._running = False

    # Should complete without raising
    await asyncio.gather(invalidator._consume_loop(), _stop())
