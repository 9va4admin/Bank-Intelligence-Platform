"""
Hold escalation Temporal activities.

These activities are notification-only — they NEVER touch NGCH or change instrument status.
They check DB state before sending to avoid sending stale alerts if the hold was just released.
"""
from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


@activity.defn(name="send_hold_reminder")
async def send_hold_reminder(params: dict[str, Any]) -> None:
    """
    30-minute checkpoint: send reminder to branch if no branch note yet.
    Silently exits if hold has been released (DB check).
    """
    with tracer.start_as_current_span("activity.send_hold_reminder") as span:
        span.set_attribute("bank_id", params.get("bank_id", ""))
        span.set_attribute("instrument_id", params.get("instrument_id", ""))
        instrument_id: str = params["instrument_id"]
        bank_id: str = params["bank_id"]
        branch_email: str | None = params.get("branch_email")

        from shared.config.config_service import config_service
        from shared.notifications.dispatcher import NotificationRequest

        # Check if hold still active — skip notification if already released
        db_dsn = await config_service.get(f"db.cts.dsn")
        import asyncpg
        conn = await asyncpg.connect(db_dsn)
        try:
            row = await conn.fetchrow(
                "SELECT branch_note, released_at FROM cts.instrument_holds "
                "WHERE instrument_id = $1 AND bank_id = $2 ORDER BY held_at DESC LIMIT 1",
                instrument_id, bank_id,
            )
        finally:
            await conn.close()

        if row is None or row["released_at"] is not None:
            log.info("hold.escalation.skipped", checkpoint="30_MIN_REMINDER",
                     instrument_id=instrument_id, reason="already_released")
            return

        if row["branch_note"]:
            log.info("hold.escalation.skipped", checkpoint="30_MIN_REMINDER",
                     instrument_id=instrument_id, reason="branch_note_present")
            return

        # Branch has not responded — send reminder
        dispatcher_url = await config_service.get("services.notification_dispatcher.url")
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            if branch_email:
                await client.post(f"{dispatcher_url}/send", json=NotificationRequest(
                    channel="email",
                    recipient=branch_email,
                    template_id="cts.hold_30min_reminder",
                    context={"instrument_id": instrument_id},
                ).model_dump())

        log.info("hold.escalation.sent", checkpoint="30_MIN_REMINDER", instrument_id=instrument_id)


@activity.defn(name="send_hold_critical_alert")
async def send_hold_critical_alert(params: dict[str, Any]) -> None:
    """
    T-60min checkpoint: CRITICAL alert to ops_manager — IET window closing.
    Silently exits if hold has been released.
    """
    with tracer.start_as_current_span("activity.send_hold_critical_alert") as span:
        span.set_attribute("bank_id", params.get("bank_id", ""))
        span.set_attribute("instrument_id", params.get("instrument_id", ""))
        instrument_id: str = params["instrument_id"]
        bank_id: str = params["bank_id"]
        ops_manager_email: str | None = params.get("ops_manager_email")
        iet_deadline: float = params["iet_deadline"]

        from shared.config.config_service import config_service

        import asyncpg
        db_dsn = await config_service.get("db.cts.dsn")
        conn = await asyncpg.connect(db_dsn)
        try:
            row = await conn.fetchrow(
                "SELECT released_at FROM cts.instrument_holds "
                "WHERE instrument_id = $1 AND bank_id = $2 ORDER BY held_at DESC LIMIT 1",
                instrument_id, bank_id,
            )
        finally:
            await conn.close()

        if row is None or row["released_at"] is not None:
            log.info("hold.escalation.skipped", checkpoint="T_MINUS_60_MIN",
                     instrument_id=instrument_id, reason="already_released")
            return

        dispatcher_url = await config_service.get("services.notification_dispatcher.url")
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            if ops_manager_email:
                await client.post(f"{dispatcher_url}/send", json={
                    "channel": "email",
                    "recipient": ops_manager_email,
                    "template_id": "cts.hold_iet_critical_60min",
                    "context": {
                        "instrument_id": instrument_id,
                        "iet_deadline": iet_deadline,
                        "severity": "CRITICAL",
                    },
                })
            # Also send WhatsApp to ops_manager if configured
            ops_phone = await config_service.get(f"banks.{bank_id}.ops_manager_whatsapp", default=None)
            if ops_phone:
                await client.post(f"{dispatcher_url}/send", json={
                    "channel": "whatsapp",
                    "recipient": ops_phone,
                    "template_id": "cts.hold_iet_critical_60min",
                    "context": {
                        "instrument_id": instrument_id,
                        "iet_deadline": iet_deadline,
                    },
                })

        log.info("hold.escalation.sent", checkpoint="T_MINUS_60_MIN", instrument_id=instrument_id,
                 iet_deadline=iet_deadline)


@activity.defn(name="send_hold_p0_alert")
async def send_hold_p0_alert(params: dict[str, Any]) -> None:
    """
    T-5min checkpoint: P0 alert bypassing the notification debouncer.
    IET breach imminent — ops_manager must release and decide NOW.
    Silently exits if hold has been released.
    """
    with tracer.start_as_current_span("activity.send_hold_p0_alert") as span:
        span.set_attribute("bank_id", params.get("bank_id", ""))
        span.set_attribute("instrument_id", params.get("instrument_id", ""))
        instrument_id: str = params["instrument_id"]
        bank_id: str = params["bank_id"]
        ops_manager_email: str | None = params.get("ops_manager_email")
        iet_deadline: float = params["iet_deadline"]

        from shared.config.config_service import config_service

        import asyncpg
        db_dsn = await config_service.get("db.cts.dsn")
        conn = await asyncpg.connect(db_dsn)
        try:
            row = await conn.fetchrow(
                "SELECT released_at FROM cts.instrument_holds "
                "WHERE instrument_id = $1 AND bank_id = $2 ORDER BY held_at DESC LIMIT 1",
                instrument_id, bank_id,
            )
        finally:
            await conn.close()

        if row is None or row["released_at"] is not None:
            log.info("hold.escalation.skipped", checkpoint="T_MINUS_5_MIN_P0",
                     instrument_id=instrument_id, reason="already_released")
            return

        # P0: bypass debouncer — set bypass_debouncer=True in request
        dispatcher_url = await config_service.get("services.notification_dispatcher.url")
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            for channel, recipient in _build_recipients(ops_manager_email, None):
                await client.post(f"{dispatcher_url}/send", json={
                    "channel": channel,
                    "recipient": recipient,
                    "template_id": "cts.hold_iet_p0_5min",
                    "bypass_debouncer": True,
                    "context": {
                        "instrument_id": instrument_id,
                        "iet_deadline": iet_deadline,
                        "severity": "P0",
                        "message": "IET breach in 5 minutes. Release hold and decide immediately.",
                    },
                })

        log.info("hold.escalation.sent", checkpoint="T_MINUS_5_MIN_P0", instrument_id=instrument_id,
                 iet_deadline=iet_deadline, bypass_debouncer=True)


def _build_recipients(email: str | None, phone: str | None) -> list[tuple[str, str]]:
    result = []
    if email:
        result.append(("email", email))
    if phone:
        result.append(("whatsapp", phone))
    return result
