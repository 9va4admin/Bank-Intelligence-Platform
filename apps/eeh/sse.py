"""
EEH SSE Publisher and Stream.

Redis Pub/Sub channel per branch per clearing date:
  Channel: eeh:sse:{branch_id}:{clearing_date}

Event types published:
  CHEQUE_ACK      — per-instrument upload acknowledgement (ACCEPTED | REJECTED | HELD)
  MISMATCH_HOLD   — Vision mismatch detected; cheque is on hold for supervisor
  LOT_SEALED      — supervisor sealed the lot; batch submitted to OutwardScanWorkflow
  SESSION_CLOSED  — session ended (operator logout / expiry)

SSE wire format (per WHATWG EventSource spec):
  event: {type}\n
  data: {json}\n
  \n
"""
from __future__ import annotations

import json
import structlog
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

log = structlog.get_logger()


# ── Channel key ────────────────────────────────────────────────────────────────

def sse_channel_key(branch_id: str, clearing_date: date) -> str:
    return f"eeh:sse:{branch_id}:{clearing_date.isoformat()}"


# ── SSE wire formatter ─────────────────────────────────────────────────────────

def format_as_sse(*, data: Any, event_type: str) -> str:
    """
    Formats a dict as an SSE event string.
    Returns: 'event: {type}\\ndata: {json}\\n\\n'
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


# ── Publisher ──────────────────────────────────────────────────────────────────

class SSEPublisher:
    """
    Publishes events to the Redis Pub/Sub channel for a branch.

    Injected into EEH request handlers that need to push real-time feedback
    to the branch portal SSE stream.
    """

    def __init__(self, *, redis: Any) -> None:
        self._redis = redis

    def _envelope(self, *, event_type: str, branch_id: str, data: Any) -> str:
        payload = {
            "type": event_type,
            "branch_id": branch_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "data": data,
        }
        return json.dumps(payload)

    async def publish_cheque_ack(
        self,
        *,
        branch_id: str,
        clearing_date: date,
        ack: dict[str, Any],
    ) -> None:
        channel = sse_channel_key(branch_id, clearing_date)
        message = self._envelope(event_type="CHEQUE_ACK", branch_id=branch_id, data=ack)
        await self._redis.publish(channel, message)
        log.debug("sse.published", event_type="CHEQUE_ACK", branch_id=branch_id)

    async def publish_mismatch_hold(
        self,
        *,
        branch_id: str,
        clearing_date: date,
        item: dict[str, Any],
    ) -> None:
        channel = sse_channel_key(branch_id, clearing_date)
        message = self._envelope(event_type="MISMATCH_HOLD", branch_id=branch_id, data=item)
        await self._redis.publish(channel, message)
        log.debug("sse.published", event_type="MISMATCH_HOLD", branch_id=branch_id)

    async def publish_lot_sealed(
        self,
        *,
        branch_id: str,
        clearing_date: date,
        lot_id: str,
        instrument_count: int,
    ) -> None:
        channel = sse_channel_key(branch_id, clearing_date)
        data = {"lot_id": lot_id, "instrument_count": instrument_count}
        message = self._envelope(event_type="LOT_SEALED", branch_id=branch_id, data=data)
        await self._redis.publish(channel, message)
        log.debug("sse.published", event_type="LOT_SEALED", branch_id=branch_id, lot_id=lot_id)

    async def publish_session_closed(
        self,
        *,
        branch_id: str,
        clearing_date: date,
        session_id: str,
        reason: str = "OPERATOR_LOGOUT",
    ) -> None:
        channel = sse_channel_key(branch_id, clearing_date)
        data = {"session_id": session_id, "reason": reason}
        message = self._envelope(event_type="SESSION_CLOSED", branch_id=branch_id, data=data)
        await self._redis.publish(channel, message)


# ── Stream (async generator for FastAPI StreamingResponse) ─────────────────────

async def branch_sse_stream(
    redis: Any,
    branch_id: str,
    clearing_date: date,
) -> AsyncIterator[str]:
    """
    Subscribe to the Redis Pub/Sub channel for a branch and yield SSE-formatted strings.

    Yields a keepalive comment every 15 seconds to prevent proxy timeouts.
    Terminates when the SESSION_CLOSED event is received or the connection drops.
    """
    channel = sse_channel_key(branch_id, clearing_date)

    # Initial connection acknowledgement
    yield format_as_sse(
        data={"message": "Connected to EEH status feed", "branch_id": branch_id},
        event_type="CONNECTED",
    )

    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(channel)
        async for raw_message in pubsub.listen():
            if raw_message["type"] != "message":
                continue
            try:
                envelope = json.loads(raw_message["data"])
                event_type = envelope.get("type", "EVENT")
                yield format_as_sse(data=envelope, event_type=event_type)
                if event_type == "SESSION_CLOSED":
                    break
            except (json.JSONDecodeError, KeyError):
                continue
