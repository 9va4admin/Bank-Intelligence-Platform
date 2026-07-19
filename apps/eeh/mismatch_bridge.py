"""
MismatchKafkaBridge — consumes cts.mismatch.{bank_id}.* Kafka events and
relays them to Redis Pub/Sub so the branch portal SSE feed picks them up.

Gap closed: MismatchResolutionWorkflow publishes to Kafka for durability, but
the EEH SSE stream listens on Redis Pub/Sub. Without this bridge, MISMATCH_HOLD
events would never reach the branch operator's screen in real time.

Design:
  - Subscribes with a regex pattern to all cts.mismatch.{bank_id}.* topics.
    This covers any branch_id without having to know them at startup.
  - Per-message failure is isolated: a bad message is logged and skipped;
    the consumer continues without stopping the stream.
  - Graceful shutdown via asyncio.Event so the lifespan context manager can
    await a clean stop before closing Redis.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_KAFKA_RECONNECT_DELAY_S = 5
_POLL_TIMEOUT_MS = 1000


class MismatchKafkaBridge:
    """
    Background asyncio task that bridges cts.mismatch Kafka messages to
    Redis Pub/Sub for EEH SSE delivery.
    """

    def __init__(
        self,
        *,
        redis: Any,
        bank_id: str,
        sse_publisher: Optional[Any] = None,
    ) -> None:
        self._redis = redis
        self._bank_id = bank_id
        self._sse_publisher = sse_publisher
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mismatch-kafka-bridge")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _run(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
            from aiokafka.errors import KafkaConnectionError
        except ImportError:
            log.warning(
                "mismatch_bridge.aiokafka_not_installed",
                hint="pip install aiokafka — bridge will not run without it",
            )
            return

        from shared.config.config_service import config_service

        bootstrap_servers = config_service.get_platform("kafka.bootstrap_servers")
        topic_pattern = f"^cts\\.mismatch\\.{self._bank_id}\\..+"

        while not self._stop_event.is_set():
            consumer = AIOKafkaConsumer(
                group_id=f"cg-eeh-mismatch-bridge-{self._bank_id}",
                bootstrap_servers=bootstrap_servers,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
            consumer.subscribe(pattern=topic_pattern)
            try:
                await consumer.start()
                log.info(
                    "mismatch_bridge.consumer_started",
                    bank_id=self._bank_id,
                    pattern=topic_pattern,
                )
                async for msg in consumer:
                    if self._stop_event.is_set():
                        break
                    await self._relay(msg)
            except KafkaConnectionError as exc:
                log.warning(
                    "mismatch_bridge.kafka_connection_error",
                    error=str(exc),
                    reconnect_delay_s=_KAFKA_RECONNECT_DELAY_S,
                )
                await asyncio.sleep(_KAFKA_RECONNECT_DELAY_S)
            except Exception as exc:
                log.error(
                    "mismatch_bridge.unexpected_error",
                    error=str(exc),
                    reconnect_delay_s=_KAFKA_RECONNECT_DELAY_S,
                )
                await asyncio.sleep(_KAFKA_RECONNECT_DELAY_S)
            finally:
                try:
                    await consumer.stop()
                except Exception:
                    pass

    async def _relay(self, msg: Any) -> None:
        """Relay one Kafka message to Redis Pub/Sub for the appropriate branch."""
        try:
            payload = msg.value if isinstance(msg.value, dict) else {}
            branch_id = payload.get("branch_id") or payload.get("payload", {}).get("branch_id")
            if not branch_id:
                # Extract branch_id from topic name: cts.mismatch.{bank_id}.{branch_id}
                parts = msg.topic.split(".")
                branch_id = parts[-1] if len(parts) >= 4 else None

            if not branch_id:
                log.warning(
                    "mismatch_bridge.no_branch_id",
                    topic=msg.topic,
                    offset=msg.offset,
                )
                return

            # The mismatch event payload from publish_mismatch_hold activity
            inner = payload.get("payload", payload)
            mismatch_id = inner.get("mismatch_id", "unknown")
            scan_id = inner.get("scan_id", "")
            instrument_id = inner.get("instrument_id", "")

            if self._sse_publisher is not None:
                # Use today's date as clearing_date — sessions are intra-day
                clearing_date = date.today()
                await self._sse_publisher.publish_mismatch_hold(
                    branch_id=branch_id,
                    clearing_date=clearing_date,
                    item={
                        "mismatch_id": mismatch_id,
                        "scan_id": scan_id,
                        "instrument_id": instrument_id,
                        "scanner_amount": inner.get("scanner_amount", ""),
                        "vision_amount": inner.get("vision_amount", ""),
                        "mismatch_fields": inner.get("mismatch_fields", []),
                        "payee_display": inner.get("payee_display", ""),
                        "session_id": inner.get("session_id", ""),
                    },
                )
                log.debug(
                    "mismatch_bridge.relayed",
                    branch_id=branch_id,
                    mismatch_id=mismatch_id,
                    topic=msg.topic,
                )
            else:
                # SSE publisher not available — publish directly to Redis channel
                from apps.eeh.sse import sse_channel_key
                channel = sse_channel_key(branch_id, date.today())
                envelope = json.dumps({
                    "type": "MISMATCH_HOLD",
                    "branch_id": branch_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": inner,
                })
                await self._redis.publish(channel, envelope)
                log.debug(
                    "mismatch_bridge.relayed_direct",
                    branch_id=branch_id,
                    mismatch_id=mismatch_id,
                )
        except Exception as exc:
            log.warning(
                "mismatch_bridge.relay_error",
                topic=msg.topic,
                offset=msg.offset,
                error=str(exc),
            )
