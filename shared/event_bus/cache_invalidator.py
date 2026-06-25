"""
Cache invalidation consumer — subscribes to Kafka platform.config.changed
and deletes the affected Redis config key so the next request fetches fresh
from YugabyteDB.

Architecture:
  Admin UI → config-service write → Kafka platform.config.changed
  → CacheInvalidator.run() → Redis DEL config:{bank_id}:{key}
  → Next config_service.get() call fetches from YugabyteDB → re-caches

This closes the loop for Layer 3 config hot-reload:
  - Without this: Redis cache outlives the 30s TTL after a config change
  - With this: Redis key is deleted within seconds of the change
  - Workers see the new value on their next config_service.get() call

Also handles platform.cache.invalidation topic for targeted cache busting
(used by vault-sync-service to invalidate specific vault keys after CBS update).
"""
import asyncio
import json
import signal

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cache_invalidator")


class CacheInvalidator:
    """
    Long-running async consumer. Instantiate once per service instance.
    Run in background via asyncio.create_task(invalidator.run()).
    """

    def __init__(self, redis_cts, kafka_consumer, bank_id: str) -> None:
        self._redis = redis_cts
        self._consumer = kafka_consumer
        self._bank_id = bank_id
        self._running = False

    async def run(self) -> None:
        """
        Main consumer loop. Consumes both config.changed and cache.invalidation topics.
        Stops cleanly on CancelledError (Kubernetes pod shutdown).
        """
        self._running = True
        log.info("cache_invalidator.started", bank_id=self._bank_id)

        try:
            async for message in self._consumer:
                if not self._running:
                    break
                await self._handle_message(message)
        except asyncio.CancelledError:
            log.info("cache_invalidator.stopping", bank_id=self._bank_id)
        except Exception as exc:
            log.error("cache_invalidator.fatal_error", bank_id=self._bank_id, error=str(exc))
        finally:
            self._running = False

    async def _handle_message(self, message) -> None:
        with tracer.start_as_current_span("cache_invalidator.handle") as span:
            try:
                payload = json.loads(message.value)
                event_type = payload.get("event_type", "")
                span.set_attribute("event_type", event_type)

                if event_type == "CONFIG_CHANGED":
                    await self._invalidate_config_key(payload)
                elif event_type == "CACHE_INVALIDATE":
                    await self._invalidate_specific_key(payload)
                elif event_type == "VAULT_SYNC_COMPLETE":
                    # Vault sync completed — clear any stale vault-not-found markers
                    await self._clear_vault_miss_markers(payload)

            except json.JSONDecodeError:
                log.warning("cache_invalidator.invalid_json", bank_id=self._bank_id)
            except Exception as exc:
                log.warning(
                    "cache_invalidator.handle_error",
                    bank_id=self._bank_id,
                    error=str(exc),
                )

    async def _invalidate_config_key(self, payload: dict) -> None:
        """
        Handle CONFIG_CHANGED event from platform.config.changed topic.
        Deletes config:{bank_id}:{key} from Redis so next get() fetches fresh.
        """
        key = payload.get("config_key")
        if not key:
            return

        cache_key = f"config:{self._bank_id}:{key}"
        try:
            deleted = await self._redis.delete(cache_key)
            log.info(
                "cache_invalidator.config_invalidated",
                bank_id=self._bank_id,
                config_key=key,
                cache_key=cache_key,
                deleted=deleted,
            )
        except Exception as exc:
            log.warning(
                "cache_invalidator.invalidation_failed",
                cache_key=cache_key,
                error=str(exc),
            )

    async def _invalidate_specific_key(self, payload: dict) -> None:
        """
        Handle targeted CACHE_INVALIDATE event from platform.cache.invalidation topic.
        Payload carries the exact Redis key(s) to delete.
        """
        keys = payload.get("cache_keys", [])
        if not keys:
            return

        try:
            deleted = await self._redis.delete(*keys)
            log.info(
                "cache_invalidator.keys_invalidated",
                bank_id=self._bank_id,
                keys=keys,
                deleted=deleted,
            )
        except Exception as exc:
            log.warning(
                "cache_invalidator.bulk_invalidation_failed",
                keys=keys,
                error=str(exc),
            )

    async def _clear_vault_miss_markers(self, payload: dict) -> None:
        """
        After VaultSyncWorkflow completes, clear any "vault_miss" markers
        so the next lookup tries Redis fresh (new signatures now loaded).
        Pattern: sig:miss:{bank_id}:* and pps:miss:{bank_id}:*
        """
        try:
            pattern = f"sig:miss:{self._bank_id}:*"
            async for key in self._redis.scan_iter(pattern, count=100):
                await self._redis.delete(key)

            pattern = f"pps:miss:{self._bank_id}:*"
            async for key in self._redis.scan_iter(pattern, count=100):
                await self._redis.delete(key)

            log.info("cache_invalidator.vault_miss_cleared", bank_id=self._bank_id)
        except Exception as exc:
            log.warning("cache_invalidator.vault_miss_clear_failed", error=str(exc))

    def stop(self) -> None:
        self._running = False
