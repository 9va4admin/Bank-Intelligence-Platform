"""
Kafka consumer that listens to platform.config.changed events and evicts
the matching Redis cache keys so config_service serves fresh values within
the 30-second TTL window.  Runs as a background asyncio task — one per pod.
"""
import asyncio
import json
import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.config")

TOPIC = "platform.config.changed"


class CacheInvalidator:
    def __init__(self, kafka_consumer, redis_client, bank_id: str):
        self._consumer = kafka_consumer
        self._redis = redis_client
        self._bank_id = bank_id
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._consumer.subscribe([TOPIC])
        asyncio.create_task(self._consume_loop(), name="config-cache-invalidator")
        log.info("config.cache_invalidator.started", topic=TOPIC, bank_id=self._bank_id)

    async def stop(self) -> None:
        self._running = False
        self._consumer.close()

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None or msg.error():
                    await asyncio.sleep(0.1)
                    continue

                event = json.loads(msg.value())
                await self._handle_event(event)

            except Exception as exc:
                log.error("config.cache_invalidator.error", error=str(exc))
                await asyncio.sleep(1.0)

    async def _handle_event(self, event: dict) -> None:
        with tracer.start_as_current_span("config.cache.invalidate") as span:
            bank_id = event.get("bank_id")
            key = event.get("config_key")

            if bank_id != self._bank_id:
                return

            span.set_attribute("config_key", key or "ALL")
            span.set_attribute("bank_id", bank_id)

            if key:
                cache_key = f"config:{bank_id}:{key}"
                await self._redis.delete(cache_key)
                log.info("config.cache.invalidated", key=key, bank_id=bank_id)
            else:
                # No specific key → flush all config keys for this bank
                pattern = f"config:{bank_id}:*"
                cursor = 0
                while True:
                    cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
                log.info("config.cache.flushed_all", bank_id=bank_id)
