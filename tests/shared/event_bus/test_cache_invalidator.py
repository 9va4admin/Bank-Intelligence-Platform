"""Tests for Kafka-driven cache invalidator."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock


from shared.event_bus.cache_invalidator import CacheInvalidator


def _make_message(event_type: str, config_key: str = "cts.thresholds", bank_id: str = "hdfc"):
    msg = MagicMock()
    msg.value = json.dumps({
        "event_type": event_type,
        "bank_id": bank_id,
        "config_key": config_key,
        "payload": {"key": config_key},
    }).encode()
    return msg


class TestCacheInvalidatorInit:
    def test_instantiates_with_required_args(self):
        redis = AsyncMock()
        consumer = MagicMock()
        inv = CacheInvalidator(redis_cts=redis, kafka_consumer=consumer, bank_id="hdfc")
        assert inv is not None


class TestConfigChangeHandling:
    @pytest.mark.asyncio
    async def test_deletes_config_key_on_config_changed(self):
        redis = AsyncMock()
        redis.delete = AsyncMock(return_value=1)
        consumer = MagicMock()
        inv = CacheInvalidator(redis_cts=redis, kafka_consumer=consumer, bank_id="hdfc")

        msg = _make_message("CONFIG_CHANGED", config_key="cts.thresholds")
        await inv._handle_message(msg)

        redis.delete.assert_called()
        deleted_key = redis.delete.call_args[0][0]
        assert "hdfc" in deleted_key
        assert "cts.thresholds" in deleted_key

    @pytest.mark.asyncio
    async def test_ignores_unknown_event_type(self):
        redis = AsyncMock()
        redis.delete = AsyncMock()
        consumer = MagicMock()
        inv = CacheInvalidator(redis_cts=redis, kafka_consumer=consumer, bank_id="hdfc")

        msg = _make_message("UNKNOWN_EVENT_TYPE")
        await inv._handle_message(msg)

        redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_malformed_message_gracefully(self):
        redis = AsyncMock()
        consumer = MagicMock()
        inv = CacheInvalidator(redis_cts=redis, kafka_consumer=consumer, bank_id="hdfc")

        bad_msg = MagicMock()
        bad_msg.value = b"not valid json {{{"
        # Should not raise
        await inv._handle_message(bad_msg)

    @pytest.mark.asyncio
    async def test_handles_missing_config_key_gracefully(self):
        redis = AsyncMock()
        redis.delete = AsyncMock()
        consumer = MagicMock()
        inv = CacheInvalidator(redis_cts=redis, kafka_consumer=consumer, bank_id="hdfc")

        msg = MagicMock()
        msg.value = json.dumps({"event_type": "CONFIG_CHANGED", "bank_id": "hdfc"}).encode()
        await inv._handle_message(msg)
        # Should not call delete when config_key is missing
        redis.delete.assert_not_called()
