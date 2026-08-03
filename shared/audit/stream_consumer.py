"""
AuditStreamConsumer -- drains the Redis Streams audit buffer and writes each
event to Immudb.

This is the "audit-service consumer" shared/audit/stream_buffer.py's own
module docstring names as the thing that reads the buffer and writes to
Immudb: "Service -> XADD audit:{bank_id}:stream -> audit-service consumer
-> Immudb HSM-signed write -> XACK". buffer_audit_event() (the producer)
and the raw consume/ack primitives already existed, fully tested, but
nothing tied them into an actual running loop -- this does, modelled on
shared/config/cache_invalidator.py's CacheInvalidator (start/stop lifecycle,
background asyncio task, a small per-message handler kept separately
testable from the poll loop).

HSM signing: hsm is optional. When unavailable, this writes UNSIGNED
events with a loud warning rather than skipping the write entirely (unlike
modules/cts/workflows/activities/decision.py's hsm-is-None handling, which
skips the audit write altogether). That's a deliberate difference: HSM
integration is a separate, already-tracked, not-yet-built piece of work
(Vault Transit vs PKCS11 is still an open decision) -- skipping every write
until it lands would mean this consumer never actually populates the audit
trail in the meantime, reproducing the exact "wired but does nothing"
problem it exists to fix.
"""
import asyncio
import json
from typing import Any, Optional

import structlog
from opentelemetry import trace

from shared.audit.stream_buffer import (
    acknowledge_messages,
    consume_pending,
    ensure_consumer_group,
)

log = structlog.get_logger()
tracer = trace.get_tracer("astra.audit_stream_consumer")


class AuditStreamConsumer:
    def __init__(
        self,
        redis_client: Any,
        immudb_writer: Any,
        hsm: Optional[Any],
        bank_id: str,
        consumer_name: str,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._redis = redis_client
        self._immudb = immudb_writer
        self._hsm = hsm
        self._bank_id = bank_id
        self._consumer_name = consumer_name
        self._poll_interval = poll_interval_seconds
        self._running = False

    async def start(self) -> None:
        await ensure_consumer_group(self._redis, self._bank_id)
        self._running = True
        asyncio.create_task(self._consume_loop(), name=f"audit-stream-consumer-{self._bank_id}")
        log.info("audit.stream_consumer.started", bank_id=self._bank_id, consumer=self._consumer_name)

    async def stop(self) -> None:
        self._running = False

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                messages = await consume_pending(
                    self._redis, self._bank_id, self._consumer_name, batch_size=50,
                )
                if not messages:
                    await asyncio.sleep(self._poll_interval)
                    continue
                await self._process_batch(messages)
            except Exception as exc:
                log.error("audit.stream_consumer.loop_error", bank_id=self._bank_id, error=str(exc))
                await asyncio.sleep(1.0)

    async def _process_batch(self, messages: list[tuple[str, dict]]) -> None:
        acked_ids: list[str] = []
        for msg_id, fields in messages:
            with tracer.start_as_current_span("audit.stream_consumer.process_message") as span:
                span.set_attribute("bank_id", self._bank_id)
                span.set_attribute("msg_id", str(msg_id))
                try:
                    await self._write_one(fields)
                    acked_ids.append(msg_id)
                except Exception as exc:
                    # Left un-acked on purpose — redelivered to this consumer
                    # group on the next poll rather than silently dropped.
                    log.error(
                        "audit.stream_consumer.message_failed",
                        bank_id=self._bank_id, msg_id=str(msg_id), error=str(exc),
                    )
        if acked_ids:
            await acknowledge_messages(self._redis, self._bank_id, acked_ids)

    async def _write_one(self, fields: dict) -> None:
        event_type = fields.get("event_type", "")
        bank_id = fields.get("bank_id") or self._bank_id
        entity_id = fields.get("entity_id")
        payload = json.loads(fields.get("payload") or "{}")

        if self._hsm is not None:
            canonical = json.dumps(
                {"event_type": event_type, "bank_id": bank_id, "payload": payload},
                sort_keys=True, default=str,
            ).encode()
            signature = self._hsm.sign(canonical)
            payload = {**payload, "signature": signature.hex()}
        else:
            log.warning(
                "audit.stream_consumer.unsigned_write",
                bank_id=bank_id, event_type=event_type,
                reason="HSM not configured — see CLAUDE.md Phase 9 HSM task",
            )
            payload = {**payload, "signature": None}

        await self._immudb.write(
            collection=f"cts_{bank_id}",
            event_type=event_type,
            bank_id=bank_id,
            instrument_id=entity_id,
            payload=payload,
        )
