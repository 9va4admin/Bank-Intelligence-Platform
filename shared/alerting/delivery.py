"""The delivery outbox (platform.alert_deliveries): what must be sent, to whom, on which channel, and what happened.

A notification is queued first (idempotent on its key), then claimed with a lease and sent. A worker that dies mid-send loses its lease and the
delivery is claimed again. Recipients are stored masked for display and encrypted for sending (pgcrypto, key from the bank's secrets); the clear
address exists only in memory while a delivery is being sent.
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from shared.alerting.audit import mask_recipient
from shared.messages import get_message
from shared.alerting.incidents import MAX_LIST, _is_conflict
from shared.utils.pii_crypto import hash_account_number     # the platform's one HMAC; the name is historical, it hashes any identifier

_COLUMNS = ("delivery_id, bank_id, incident_id, idempotency_key, escalation_level, channel, recipient_ref, template_id, status, attempt, "
            "payload, priority, fallback_of")


class EnqueueResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    delivery_id: str
    created: bool


class DeliveryRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    delivery_id: str
    bank_id: str
    incident_id: str
    escalation_level: int
    channel: str
    recipient: str                # the clear address; only ever held in memory, only on a claimed row
    recipient_ref: str
    template_id: Optional[str] = None
    attempt: int
    payload: dict[str, Any] = {}
    priority: Optional[str] = None
    fallback_of: Optional[str] = None


class DeliveryStore:
    def __init__(self, pool: Any, *, pii_key: str, pepper: str, max_attempts: int = 6, retry_backoff_seconds: float = 0.03) -> None:
        if not pii_key or not pepper:
            raise ValueError(get_message("ALERT_DELIVERY_KEYS_REQUIRED"))
        self._pool, self._key, self._pepper = pool, pii_key, pepper
        self._max_attempts, self._backoff = max(1, max_attempts), retry_backoff_seconds

    async def _retrying(self, fn):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_conflict(exc) or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff * attempt * (0.5 + random.random()))

    def idempotency_key(self, bank_id: str, incident_id: str, occasion: str, level: int, channel: str, recipient: str) -> str:
        return f"{incident_id}:{occasion}:{level}:{channel}:{hash_account_number(recipient, bank_id, self._pepper)[:16]}"

    async def enqueue(self, *, bank_id: str, incident_id: str, occasion: str, level: int, channel: str, recipient: str, template_id: str,
                      payload: dict[str, Any], priority: str, fallback_of: Optional[str] = None, delay_seconds: float = 0.0) -> EnqueueResult:
        key = self.idempotency_key(bank_id, incident_id, occasion, level, channel, recipient)
        delivery_id = uuid.uuid4().hex

        async def go():
            created = await self._pool.fetchval(
                "INSERT INTO platform.alert_deliveries (delivery_id, bank_id, incident_id, idempotency_key, escalation_level, channel, recipient_ref, "
                "recipient_enc, template_id, status, payload, priority, fallback_of, next_attempt_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7, pgp_sym_encrypt($8, $9)::bytea, $10,'PENDING',$11::jsonb,$12,$13, NOW() + make_interval(secs => $14)) "
                "ON CONFLICT DO NOTHING RETURNING delivery_id",
                delivery_id, bank_id, incident_id, key, level, channel, mask_recipient(recipient, channel), recipient, self._key, template_id,
                json.dumps(payload), priority, fallback_of, float(delay_seconds))
            if created:
                return EnqueueResult(delivery_id=delivery_id, created=True)
            existing = await self._pool.fetchval("SELECT delivery_id FROM platform.alert_deliveries WHERE bank_id=$1 AND idempotency_key=$2", bank_id, key)
            return EnqueueResult(delivery_id=existing, created=False)
        return await self._retrying(go)

    async def claim(self, bank_id: str, delivery_id: str, *, lease_seconds: float) -> Optional[DeliveryRow]:
        """Take a delivery that is due (or whose sender's lease has expired). At most one caller wins."""
        async def go():
            row = await self._pool.fetchrow(
                "UPDATE platform.alert_deliveries SET status='SENDING', attempt=attempt+1, claimed_until=NOW() + make_interval(secs => $3) "
                "WHERE bank_id=$1 AND delivery_id=$2 AND ("
                "  (status IN ('PENDING','FAILED') AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())) "
                "  OR (status='SENDING' AND claimed_until < NOW())) "
                f"RETURNING {_COLUMNS}, pgp_sym_decrypt(recipient_enc, $4) AS recipient",
                bank_id, delivery_id, float(lease_seconds), self._key)
            if row is None:
                return None
            payload = row["payload"]
            return DeliveryRow(delivery_id=row["delivery_id"], bank_id=row["bank_id"], incident_id=row["incident_id"],
                               escalation_level=row["escalation_level"], channel=row["channel"], recipient=row["recipient"],
                               recipient_ref=row["recipient_ref"], template_id=row["template_id"], attempt=row["attempt"],
                               payload=json.loads(payload) if isinstance(payload, str) else dict(payload or {}),
                               priority=row["priority"], fallback_of=row["fallback_of"])
        return await self._retrying(go)

    async def due_ids(self, bank_id: str, *, limit: int) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT delivery_id FROM platform.alert_deliveries WHERE bank_id=$1 AND ("
            "  (status IN ('PENDING','FAILED') AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())) "
            "  OR (status='SENDING' AND claimed_until < NOW())) ORDER BY created_at LIMIT $2",
            bank_id, min(max(limit, 1), MAX_LIST))
        return [r["delivery_id"] for r in rows]

    async def mark_sent(self, bank_id: str, delivery_id: str, *, provider_class: str = "") -> None:
        await self._retrying(lambda: self._pool.execute(
            "UPDATE platform.alert_deliveries SET status='SENT', completed_at=NOW(), claimed_until=NULL, provider_class=$3, error=NULL "
            "WHERE bank_id=$1 AND delivery_id=$2", bank_id, delivery_id, provider_class))

    async def schedule_retry(self, bank_id: str, delivery_id: str, *, delay_seconds: float, error: str, provider_class: str = "") -> None:
        await self._retrying(lambda: self._pool.execute(
            "UPDATE platform.alert_deliveries SET status='FAILED', claimed_until=NULL, error=$3, provider_class=$4, "
            "next_attempt_at=NOW() + make_interval(secs => $5) WHERE bank_id=$1 AND delivery_id=$2",
            bank_id, delivery_id, error, provider_class, float(delay_seconds)))

    async def mark_undelivered(self, bank_id: str, delivery_id: str, *, error: str, provider_class: str = "") -> None:
        await self._retrying(lambda: self._pool.execute(
            "UPDATE platform.alert_deliveries SET status='UNDELIVERED', completed_at=NOW(), claimed_until=NULL, error=$3, provider_class=$4 "
            "WHERE bank_id=$1 AND delivery_id=$2", bank_id, delivery_id, error, provider_class))

    async def list_for_incident(self, bank_id: str, incident_id: str, *, limit: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT delivery_id, escalation_level, channel, recipient_ref, template_id, status, attempt, provider_class, error, fallback_of, "
            "created_at, completed_at FROM platform.alert_deliveries WHERE bank_id=$1 AND incident_id=$2 ORDER BY created_at LIMIT $3",
            bank_id, incident_id, min(max(limit, 1), MAX_LIST))
        return [dict(r) for r in rows]
