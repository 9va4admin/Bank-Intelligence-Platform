"""
Redis Streams audit buffer — durable in-memory staging before Immudb write.

Architecture:
  Service → XADD audit:{bank_id}:stream → audit-service consumer → Immudb HSM-signed write → XACK

Why Redis Streams instead of direct Immudb:
  - Immudb writes are synchronous gRPC — adds 10-20ms to every audit-worthy request
  - Redis XADD is sub-millisecond — decouples audit latency from request latency
  - Redis Streams guarantee ordering (per shard) and at-least-once delivery via consumer groups
  - audit-service retries Immudb write on failure; original service is already done
  - Kafka platform.audit.events is the durable backup path (longer retention, disk-backed)

Max buffer: 1000 messages per bank stream (MAXLEN). Kafka topic is primary durability.

Key: audit:{bank_id}:stream
Consumer group: cg-audit-immudb-{bank_id}
"""
import json
import time
import uuid
from typing import Any, Optional

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.audit_stream")

_MAX_STREAM_LEN = 1000        # approximate cap (MAXLEN ~ 1000)
_STREAM_KEY_TEMPLATE = "audit:{bank_id}:stream"
_CONSUMER_GROUP_TEMPLATE = "cg-audit-immudb-{bank_id}"


def _stream_key(bank_id: str) -> str:
    return _STREAM_KEY_TEMPLATE.format(bank_id=bank_id)


async def buffer_audit_event(
    redis,
    bank_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_id: str,
    payload: dict[str, Any],
    hsm_signed: bool = False,
) -> Optional[str]:
    """
    Append an audit event to the Redis Stream for this bank.

    Returns the Redis Stream message ID (e.g. "1718012345678-0") on success,
    None on Redis unavailability (caller should fall back to Kafka platform.audit.events).

    Arguments:
        redis       — redis.asyncio.Redis client (redis-cts cluster)
        bank_id     — bank identifier (scopes the stream key)
        event_type  — e.g. "CTS_DECISION_FILED", "EJ_CANONICAL_STORED"
        entity_type — e.g. "cheque_instrument", "ej_canonical_record"
        entity_id   — the entity's ID (instrument_id, canonical_hash, etc.)
        actor_id    — user_id or service name that caused the event
        payload     — serialisable dict with event-specific fields
        hsm_signed  — True if payload has already been HSM-signed (skip in audit-service)
    """
    if redis is None:
        return None

    with tracer.start_as_current_span("audit.stream.buffer") as span:
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("event_type", event_type)
        span.set_attribute("entity_type", entity_type)

        event_id = str(uuid.uuid4())
        fields = {
            "event_id": event_id,
            "event_type": event_type,
            "bank_id": bank_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": actor_id,
            "timestamp": str(time.time()),
            "hsm_signed": "true" if hsm_signed else "false",
            "payload": json.dumps(payload),
        }

        try:
            key = _stream_key(bank_id)
            msg_id = await redis.xadd(
                key,
                fields,
                maxlen=_MAX_STREAM_LEN,
                approximate=True,  # MAXLEN ~ 1000 (faster, close enough)
            )
            span.set_attribute("stream_msg_id", msg_id)
            log.debug(
                "audit.stream.buffered",
                bank_id=bank_id,
                event_type=event_type,
                msg_id=msg_id,
            )
            return msg_id
        except Exception as exc:
            log.warning(
                "audit.stream.buffer_failed",
                bank_id=bank_id,
                event_type=event_type,
                error=str(exc),
            )
            return None


async def ensure_consumer_group(redis, bank_id: str) -> None:
    """
    Ensure the audit stream consumer group exists (idempotent).
    Call at audit-service startup.
    """
    key = _stream_key(bank_id)
    group = _CONSUMER_GROUP_TEMPLATE.format(bank_id=bank_id)
    try:
        await redis.xgroup_create(key, group, id="0", mkstream=True)
        log.info("audit.stream.group_created", bank_id=bank_id, group=group)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # group already exists — idempotent
        else:
            log.warning("audit.stream.group_create_failed", bank_id=bank_id, error=str(exc))


async def consume_pending(redis, bank_id: str, consumer_name: str, batch_size: int = 50):
    """
    Read pending (unacknowledged) messages from the audit stream.
    Called by audit-service consumer loop.

    Returns list of (msg_id, fields_dict) tuples.
    """
    key = _stream_key(bank_id)
    group = _CONSUMER_GROUP_TEMPLATE.format(bank_id=bank_id)
    try:
        messages = await redis.xreadgroup(
            groupname=group,
            consumername=consumer_name,
            streams={key: ">"},  # ">" = new messages not yet delivered to any consumer
            count=batch_size,
            block=1000,  # block for up to 1 second waiting for messages
        )
        if not messages:
            return []
        result = []
        for _stream, entries in messages:
            for msg_id, fields in entries:
                result.append((msg_id, fields))
        return result
    except Exception as exc:
        log.warning("audit.stream.consume_failed", bank_id=bank_id, error=str(exc))
        return []


async def acknowledge_messages(redis, bank_id: str, msg_ids: list[str]) -> None:
    """
    Acknowledge messages after successful Immudb write.
    Removes them from the pending entries list.
    """
    if not msg_ids:
        return
    key = _stream_key(bank_id)
    group = _CONSUMER_GROUP_TEMPLATE.format(bank_id=bank_id)
    try:
        await redis.xack(key, group, *msg_ids)
        log.debug("audit.stream.acknowledged", bank_id=bank_id, count=len(msg_ids))
    except Exception as exc:
        log.warning("audit.stream.ack_failed", bank_id=bank_id, error=str(exc))
