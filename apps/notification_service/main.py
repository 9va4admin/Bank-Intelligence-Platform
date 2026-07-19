"""
notification-service — Kafka consumer for platform.notifications.

Drains the platform.notifications topic and routes each event to the correct
delivery channel (email via Postal SMTP, WhatsApp via Meta Business API).
One instance per bank, matching ASTRA's per-bank K8s namespace isolation model.

Recipient resolution:
  - event.recipient       → use directly (email address or E.164 phone)
  - event.recipient_ref with '@' → email address delivered directly
  - event.recipient_ref (opaque user_id) → unresolved; logged, recorded as FAILED
  - event.recipient_role  → unresolved; logged, recorded as FAILED
    Both unresolved cases are honest gaps — the user directory (SAML/LDAP lookup)
    needed for recipient resolution is not yet built. See CLAUDE.md §16 remaining work.

Delivery results are written to platform.notification_records.
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from shared.config.config_service import config_service
from shared.event_bus.topics import PLATFORM_NOTIFICATIONS
from shared.notifications.dispatcher import NotificationDispatcher, NotificationRequest
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

SERVICE_NAME = "notification-service"

# ── dependency builders ─────────────────────────────────────────────────────


async def _build_kafka_consumer(bank_id: str) -> Optional[Any]:
    try:
        from aiokafka import AIOKafkaConsumer

        bootstrap = config_service.get_platform("kafka.bootstrap_servers")
        consumer = AIOKafkaConsumer(
            PLATFORM_NOTIFICATIONS,
            bootstrap_servers=bootstrap,
            group_id=f"cg-notification-service-{bank_id}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            value_deserializer=lambda v: v,   # raw bytes — we JSON-decode manually
            max_poll_records=50,
        )
        await consumer.start()
        log.info("notification_service.kafka_consumer_started", bank_id=bank_id)
        return consumer
    except Exception as exc:
        log.warning("notification_service.kafka_consumer_unavailable", error=str(exc))
        return None


async def _build_email_channel(cfg: Any, bank_id: str) -> Optional[Any]:
    try:
        from shared.notifications.email_channel import EmailChannel

        smtp_host = cfg.get_platform("notifications.smtp_host")
        smtp_port = int(cfg.get_platform("notifications.smtp_port"))
        from_addr = cfg.get_platform("notifications.smtp_from_address")
        channel = EmailChannel(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            from_address=from_addr,
            bank_id=bank_id,
        )
        channel.connect()
        log.info("notification_service.email_channel_ready", bank_id=bank_id)
        return channel
    except Exception as exc:
        log.warning("notification_service.email_channel_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_whatsapp_channel(cfg: Any, bank_id: str) -> Optional[Any]:
    try:
        from shared.notifications.whatsapp_channel import WhatsAppChannel

        api_url = cfg.get_platform("notifications.whatsapp_api_url")
        phone_number_id = cfg.get_platform("notifications.whatsapp_phone_number_id")
        access_token = await cfg.get_secret("notifications.whatsapp_access_token")
        channel = WhatsAppChannel(
            api_url=api_url,
            phone_number_id=phone_number_id,
            bank_id=bank_id,
        )
        channel.connect(access_token=access_token)
        log.info("notification_service.whatsapp_channel_ready", bank_id=bank_id)
        return channel
    except Exception as exc:
        log.warning("notification_service.whatsapp_channel_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_db_pool(cfg: Any) -> Optional[Any]:
    try:
        import asyncpg

        dsn = await cfg.get_secret("db.platform.dsn")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        log.info("notification_service.db_pool_ready")
        return pool
    except Exception as exc:
        log.warning("notification_service.db_pool_unavailable", error=str(exc))
        return None


def _build_debouncer(cfg: Any) -> Optional[Any]:
    """Optional Redis-backed NotificationDebouncer. Skipped when Redis unavailable."""
    try:
        import redis.asyncio as aioredis
        from shared.notifications.debouncer import NotificationDebouncer

        redis_url = cfg.get_platform("redis.cts.url")
        redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        return NotificationDebouncer(redis_client=redis_client)
    except Exception as exc:
        log.warning("notification_service.debouncer_unavailable", error=str(exc))
        return None


# ── recipient resolution ────────────────────────────────────────────────────


def _resolve_recipient(event: dict) -> tuple[Optional[str], str]:
    """
    Returns (recipient_address, normalised_channel) or (None, channel).

    recipient_address is None when we cannot resolve to an actual delivery address
    — this happens for opaque user_id refs and role-based routing because ASTRA
    does not yet have a user directory service (SAML/LDAP lookup not built).
    The caller logs the boundary and records a FAILED delivery rather than silently
    dropping the event.
    """
    channel = (event.get("channel") or "email").lower()
    if channel not in ("email", "whatsapp"):
        channel = "email"

    # Direct address already in the event
    if recipient := event.get("recipient"):
        return str(recipient), channel

    # recipient_ref that looks like an email address
    ref = str(event.get("recipient_ref") or "").strip()
    if ref and "@" in ref:
        return ref, "email"

    # Unresolvable — role-based or opaque user_id
    role = str(event.get("recipient_role") or "").strip()
    log.warning(
        "notification.recipient_unresolved",
        recipient_ref=ref or None,
        recipient_role=role or None,
        template_id=event.get("template_id"),
        bank_id=event.get("bank_id"),
        reason=(
            "recipient_role routing requires user directory (SAML/LDAP lookup not yet built)"
            if role else
            "recipient_ref is an opaque user_id; user directory resolution not yet built"
        ),
    )
    return None, channel


# ── DB recording ────────────────────────────────────────────────────────────


async def _record_delivery(
    pool: Any,
    notification_id: str,
    bank_id: str,
    channel: str,
    template_id_str: str,
    event_type: str,
    module: str,
    recipient_type: str,
    status: str,
    delivery_error: Optional[str],
    kafka_offset: Optional[int],
) -> None:
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO platform.notification_records (
                    notification_id,
                    bank_id,
                    module,
                    event_type,
                    channel,
                    recipient_type,
                    status,
                    sent_at,
                    delivery_error,
                    attempt_count,
                    kafka_offset,
                    created_at
                ) VALUES (
                    $1::uuid, $2, $3, $4, $5, $6, $7,
                    CASE WHEN $7 = 'SENT' THEN NOW() ELSE NULL END,
                    $8,
                    1,
                    $9,
                    NOW()
                )
                ON CONFLICT (notification_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        sent_at = EXCLUDED.sent_at,
                        delivery_error = EXCLUDED.delivery_error,
                        attempt_count = platform.notification_records.attempt_count + 1
                """,
                notification_id,
                bank_id,
                module.upper(),
                event_type.upper() if event_type else "UNKNOWN",
                channel.upper(),
                recipient_type.upper() if recipient_type else "UNKNOWN",
                status,
                delivery_error,
                kafka_offset,
            )
    except Exception as exc:
        log.warning(
            "notification_service.db_record_failed",
            notification_id=notification_id,
            error=str(exc),
        )


# ── consumer loop ────────────────────────────────────────────────────────────


async def _consume_loop(
    consumer: Any,
    dispatcher: NotificationDispatcher,
    pool: Optional[Any],
    bank_id: str,
) -> None:
    """
    Main consumer loop. Polls platform.notifications, dispatches each event,
    records result in DB. Per-message failure isolation: one bad message is
    committed and logged; the consumer never stops for a single delivery failure.
    """
    log.info("notification_service.consume_loop_started", bank_id=bank_id)
    try:
        async for msg in consumer:
            notification_id = f"notif-{uuid.uuid4()}"
            kafka_offset = msg.offset

            try:
                event: dict = json.loads(msg.value.decode("utf-8"))
            except Exception as exc:
                log.warning(
                    "notification_service.message_parse_failed",
                    offset=kafka_offset,
                    error=str(exc),
                )
                await consumer.commit()
                continue

            notification_id = str(event.get("notification_id") or notification_id)
            event_bank_id = str(event.get("bank_id") or bank_id)

            # Only process notifications for this bank
            if event_bank_id and event_bank_id != bank_id and event_bank_id != "unknown":
                await consumer.commit()
                continue

            template_id_str = str(event.get("template_id") or "")
            context = dict(event.get("context") or {})
            priority = str(event.get("priority") or "P2")
            smb_id = event.get("smb_id") or None
            event_category = event.get("event_category") or None
            module = str(event.get("module") or "PLATFORM")
            event_type = str(event.get("event_type") or template_id_str)
            recipient_type = str(event.get("recipient_role") or event.get("recipient_type") or "UNKNOWN")

            recipient, channel = _resolve_recipient(event)

            if recipient is None:
                # Unresolvable — record as FAILED so it's visible in the DB
                await _record_delivery(
                    pool,
                    notification_id=notification_id,
                    bank_id=event_bank_id,
                    channel=channel,
                    template_id_str=template_id_str,
                    event_type=event_type,
                    module=module,
                    recipient_type=recipient_type,
                    status="FAILED",
                    delivery_error="RECIPIENT_UNRESOLVED",
                    kafka_offset=kafka_offset,
                )
                await consumer.commit()
                continue

            # Dispatch
            delivery_status = "SENT"
            delivery_error: Optional[str] = None
            try:
                req = NotificationRequest(
                    channel=channel,  # type: ignore[arg-type]
                    recipient=recipient,
                    template_id=template_id_str,
                    context={**context, "bank_id": event_bank_id},
                    notification_id=notification_id,
                    priority=priority,
                    smb_id=smb_id,
                    event_category=event_category,
                )
                result = await dispatcher.send(req)
                if result.get("status") == "suppressed":
                    delivery_status = "SUPPRESSED"
                log.info(
                    "notification_service.dispatched",
                    notification_id=notification_id,
                    channel=channel,
                    template_id=template_id_str,
                    status=delivery_status,
                )
            except Exception as exc:
                delivery_status = "FAILED"
                delivery_error = str(exc)[:512]
                log.error(
                    "notification_service.dispatch_failed",
                    notification_id=notification_id,
                    channel=channel,
                    template_id=template_id_str,
                    error=delivery_error,
                )

            await _record_delivery(
                pool,
                notification_id=notification_id,
                bank_id=event_bank_id,
                channel=channel,
                template_id_str=template_id_str,
                event_type=event_type,
                module=module,
                recipient_type=recipient_type,
                status=delivery_status if delivery_status != "SUPPRESSED" else "SENT",
                delivery_error=delivery_error,
                kafka_offset=kafka_offset,
            )
            await consumer.commit()

    except asyncio.CancelledError:
        log.info("notification_service.consume_loop_cancelled", bank_id=bank_id)
    except Exception as exc:
        log.error("notification_service.consume_loop_crashed", bank_id=bank_id, error=str(exc))


# ── lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("notification_service.starting", service=SERVICE_NAME)
    configure_otel(service_name=SERVICE_NAME, service_version="1.0.0")

    try:
        await config_service.initialise()
    except Exception as exc:
        log.error("notification_service.config_service_init_failed", error=str(exc))

    bank_id = getattr(config_service, "bank_id", None) or "unknown"

    app.state.kafka_consumer = await _build_kafka_consumer(bank_id)
    app.state.email_channel = await _build_email_channel(config_service, bank_id)
    app.state.whatsapp_channel = await _build_whatsapp_channel(config_service, bank_id)
    app.state.db_pool = await _build_db_pool(config_service)
    app.state.debouncer = _build_debouncer(config_service)
    app.state.consume_task = None

    # Build dispatcher — always created; channels may be None (graceful degradation)
    dispatcher = NotificationDispatcher(bank_id=bank_id)
    dispatcher.connect(
        email_channel=app.state.email_channel,
        whatsapp_channel=app.state.whatsapp_channel,
        debouncer=app.state.debouncer,
    )
    app.state.dispatcher = dispatcher

    if app.state.kafka_consumer is not None:
        task = asyncio.create_task(
            _consume_loop(
                consumer=app.state.kafka_consumer,
                dispatcher=dispatcher,
                pool=app.state.db_pool,
                bank_id=bank_id,
            )
        )
        app.state.consume_task = task
        log.info("notification_service.consumer_started", bank_id=bank_id)
    else:
        log.warning(
            "notification_service.consumer_not_started",
            bank_id=bank_id,
            reason="kafka_consumer unavailable",
        )

    log.info("notification_service.ready", service=SERVICE_NAME, bank_id=bank_id)
    yield

    if app.state.consume_task is not None:
        app.state.consume_task.cancel()
        try:
            await app.state.consume_task
        except asyncio.CancelledError:
            pass

    if app.state.kafka_consumer is not None:
        try:
            await app.state.kafka_consumer.stop()
        except Exception:
            pass

    if app.state.db_pool is not None:
        await app.state.db_pool.close()

    log.info("notification_service.shutdown_complete")


# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="ASTRA Notification Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    checks = {
        "kafka_consumer": getattr(app.state, "kafka_consumer", None) is not None,
        "consumer_running": (
            getattr(app.state, "consume_task", None) is not None
            and not app.state.consume_task.done()
        ),
        "email_channel": getattr(app.state, "email_channel", None) is not None,
        "whatsapp_channel": getattr(app.state, "whatsapp_channel", None) is not None,
    }
    # At least one delivery channel must be available; kafka must be running
    operational = (
        checks["kafka_consumer"]
        and checks["consumer_running"]
        and (checks["email_channel"] or checks["whatsapp_channel"])
    )
    return JSONResponse(
        content={"status": "ready" if operational else "degraded", "checks": checks},
        status_code=200 if operational else 503,
    )
