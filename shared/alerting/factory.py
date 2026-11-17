"""Build the production AlertAuditor from configuration.

Primary sink: the Redis audit stream (sub-millisecond, durable; the audit service signs and writes it to Immudb).
Fallback sink: a direct Immudb write, used when the stream cannot be reached.
Settings (Layer 3, hot-reloadable at the next build): alerting.audit_collection_pattern, alerting.audit_max_error_chars.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from shared.alerting.audit import AlertAuditor, Sink
from shared.audit.stream_buffer import buffer_audit_event

ENTITY_TYPE = "alert_incident"

DEFAULT_COLLECTION_PATTERN = "cts_{bank_id}"      # the collection the CTS audit trail already uses
DEFAULT_MAX_ERROR_CHARS = 200


async def _setting(config_service: Any, key: str, default: Any) -> Any:
    try:
        value = await config_service.get(key)
    except Exception:
        return default
    return default if value in (None, "") else value


async def build_alert_auditor(config_service: Any, bank_id: str, *, redis: Any = None, immudb_writer: Any = None,
                              on_failure: Optional[Callable[..., Any]] = None) -> AlertAuditor:
    pattern = str(await _setting(config_service, "alerting.audit_collection_pattern", DEFAULT_COLLECTION_PATTERN))
    try:
        max_error = int(await _setting(config_service, "alerting.audit_max_error_chars", DEFAULT_MAX_ERROR_CHARS))
    except (TypeError, ValueError):
        max_error = DEFAULT_MAX_ERROR_CHARS

    sink: Optional[Sink] = None
    if redis is not None:
        async def stream_sink(event_type: str, bank: str, entity_id: str, actor_id: str, payload: dict) -> Optional[str]:
            return await buffer_audit_event(redis, bank, event_type, ENTITY_TYPE, entity_id, actor_id, payload)
        sink = stream_sink

    fallback: Optional[Sink] = None
    if immudb_writer is not None:
        collection = pattern.format(bank_id=bank_id)

        async def immudb_sink(event_type: str, bank: str, entity_id: str, actor_id: str, payload: dict) -> Optional[str]:
            return await immudb_writer.write(collection=collection, event_type=event_type, bank_id=bank, instrument_id=entity_id,
                                             payload={**payload, "actor_id": actor_id})
        fallback = immudb_sink

    if sink is None and fallback is not None:           # no stream configured: the direct write is the primary
        sink, fallback = fallback, None
    return AlertAuditor(sink, fallback=fallback, on_failure=on_failure, max_error_chars=max_error)
