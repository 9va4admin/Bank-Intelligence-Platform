"""
notification-service — Kafka consumer for platform.notifications.

Drains the platform.notifications topic and routes each event to the correct
delivery channel (email via Postal SMTP, WhatsApp via Meta Business API).
One instance per bank, matching ASTRA's per-bank K8s namespace isolation model.

Every event is delivered through the shared delivery engine (shared/alerting/engine.py): queued in the outbox first, retried with the configured
backoff, falling back to another channel when one gives up, audited before and after every attempt, and recorded in ONE delivery log,
platform.alert_deliveries (the same one the alert system uses). The kafka offset is committed per message.

Who an event is for (resolve_targets):
  - event.recipient                       → used directly (email address or E.164 phone) on the event's channel
  - event.recipient_ref containing '@'    → that email address
  - event.recipient_ref (a user id)       → that user's in-app bell
  - event.recipient_role                  → the in-app bell of every active user of that role (local accounts and everyone who has signed in)
  - nothing of the above                  → recorded as UNDELIVERED with the reason, never silently dropped
Role-based email needs per-user contact details (planned with the alert routing screens); until then a role is reached on the bell.
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

from shared.alerting.bell import resolve_bell_users
from shared.alerting.engine import Target
from shared.config.config_service import config_service
from shared.event_bus.topics import PLATFORM_NOTIFICATIONS
from shared.messages import get_message
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

SERVICE_NAME = "notification-service"

# ── dependency builders ─────────────────────────────────────────────────────

_CHANNELS = ("email", "whatsapp", "bell")


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


async def _build_db_pool(cfg: Any) -> Optional[Any]:
    for key in ("db.platform.dsn", "db.cts.dsn"):       # the delivery log lives in the platform schema of the same database
        try:
            import asyncpg

            pool = await asyncpg.create_pool(await cfg.get_secret(key), min_size=1, max_size=5)
            log.info("notification_service.db_pool_ready", dsn_key=key)
            return pool
        except Exception as exc:
            log.warning("notification_service.db_pool_unavailable", dsn_key=key, error=str(exc))
    return None


def _build_redis(cfg: Any) -> Optional[Any]:
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(cfg.get_platform("redis.cts.url"), encoding="utf-8", decode_responses=True)
    except Exception as exc:
        log.warning("notification_service.redis_unavailable", error=str(exc))
        return None


# ── who an event is for ─────────────────────────────────────────────────────


async def _setting(cfg: Any, key: str, default: int) -> int:
    try:
        return int(await cfg.get(key))
    except Exception:
        return default


async def _bell_users_of_role(pool: Any, cfg: Any, bank_id: str, role: str) -> list[Target]:
    if pool is None or not role:
        return []
    try:
        users = await resolve_bell_users(pool, bank_id, roles=[role], limit=await _setting(cfg, "alerting.bell_max_recipients", 200),
                                         seen_within_days=await _setting(cfg, "alerting.bell_directory_days", 90))
    except Exception as exc:
        log.warning("notification_service.role_lookup_failed", bank_id=bank_id, role=role, error=str(exc))
        return []
    return [Target("bell", u) for u in users]


async def resolve_targets(event: dict, *, pool: Any, config_service: Any, bank_id: str) -> list[Target]:
    """The delivery targets for an event (see the module docstring). An empty list means nobody could be found."""
    channel = (event.get("channel") or "email").lower()
    if channel not in _CHANNELS:
        channel = "email"
    if recipient := event.get("recipient"):
        return [Target(channel, str(recipient))]
    ref = str(event.get("recipient_ref") or "").strip()
    if ref and "@" in ref:
        return [Target("email", ref)]
    role = str(event.get("recipient_role") or "").strip()
    if role:
        return await _bell_users_of_role(pool, config_service, bank_id, role)
    if ref:
        return [Target("bell", ref)]
    return []


# ── consumer loop ────────────────────────────────────────────────────────────


def _readable(event: dict, template_id: str, event_type: str) -> str:
    return str(event.get("message") or (event.get("context") or {}).get("message") or event_type or template_id or get_message("PLATFORM_NOTIFICATION_GENERIC"))


async def _consume_loop(consumer: Any, engine: Any, pool: Optional[Any], bank_id: str, cfg: Any) -> None:
    """
    Main consumer loop. Polls platform.notifications and hands each event to the delivery engine. Per-message failure isolation: one bad message is
    committed and logged; the consumer never stops for a single delivery failure.
    """
    log.info("notification_service.consume_loop_started", bank_id=bank_id)
    try:
        async for msg in consumer:
            try:
                event: dict = json.loads(msg.value.decode("utf-8"))
            except Exception as exc:
                log.warning("notification_service.message_parse_failed", offset=msg.offset, error=str(exc))
                await consumer.commit()
                continue

            notification_id = str(event.get("notification_id") or f"notif-{uuid.uuid4()}")
            event_bank_id = str(event.get("bank_id") or bank_id)
            if event_bank_id and event_bank_id != bank_id and event_bank_id != "unknown":     # only this bank's notifications
                await consumer.commit()
                continue

            template_id = str(event.get("template_id") or "")
            module = str(event.get("module") or "PLATFORM")
            event_type = str(event.get("event_type") or template_id)
            priority = str(event.get("priority") or "P2")
            channel = (event.get("channel") or "email").lower()
            if channel not in _CHANNELS:
                channel = "email"
            context = {**dict(event.get("context") or {}), "bank_id": event_bank_id, "event_type": event_type,
                       "component": str(event.get("component") or module.lower()), "message": _readable(event, template_id, event_type),
                       "priority": priority, "incident_id": notification_id}
            try:
                targets = await resolve_targets(event, pool=pool, config_service=cfg, bank_id=event_bank_id)
                if not targets:
                    log.warning("notification.recipient_unresolved", notification_id=notification_id, template_id=template_id, bank_id=event_bank_id)
                    await engine.record_undeliverable(bank_id=event_bank_id, incident_id=notification_id, occasion=notification_id, channel=channel,
                                                      template_id=template_id, context=context, priority=priority, reason="RECIPIENT_UNRESOLVED")
                else:
                    async def fallback_targets(fallback_channel: str, _event=event, _bank=event_bank_id) -> list[Target]:
                        return await _bell_users_of_role(pool, cfg, _bank, str(_event.get("recipient_role") or "")) if fallback_channel == "bell" else []
                    result = await engine.submit(bank_id=event_bank_id, incident_id=notification_id, occasion=notification_id, targets=targets,
                                                 template_id=template_id, context=context, priority=priority, component=context["component"],
                                                 resolve_targets=fallback_targets)
                    log.info("notification_service.submitted", notification_id=notification_id, sent=result.sent, retrying=result.retrying)
            except Exception as exc:
                log.error("notification_service.submit_failed", notification_id=notification_id, template_id=template_id, error=str(exc)[:200])
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

    from shared.alerting.factory import build_alert_auditor, build_delivery_engine
    from shared.notifications.debouncer import NotificationDebouncer
    from shared.notifications.factory import build_dispatcher

    app.state.kafka_consumer = await _build_kafka_consumer(bank_id)
    app.state.db_pool = await _build_db_pool(config_service)
    app.state.redis = _build_redis(config_service)
    app.state.consume_task = None

    # The same channels, settings (SMTP_* / WHATSAPP_*), outbox and audit trail as the alert system; any channel may be absent (graceful degradation).
    debouncer = NotificationDebouncer(redis_client=app.state.redis) if app.state.redis is not None else None
    dispatcher = await build_dispatcher(config_service, bank_id, db_pool=app.state.db_pool, debouncer=debouncer)
    app.state.dispatcher = dispatcher
    app.state.email_channel = getattr(dispatcher, "_email", None)
    app.state.whatsapp_channel = getattr(dispatcher, "_whatsapp", None)
    auditor = await build_alert_auditor(config_service, bank_id, redis=app.state.redis, immudb_writer=None)
    app.state.engine = await build_delivery_engine(config_service, bank_id, db_pool=app.state.db_pool, dispatcher=dispatcher, auditor=auditor)

    if app.state.kafka_consumer is not None and app.state.engine is not None:
        task = asyncio.create_task(
            _consume_loop(
                consumer=app.state.kafka_consumer,
                engine=app.state.engine,
                pool=app.state.db_pool,
                bank_id=bank_id,
                cfg=config_service,
            )
        )
        app.state.consume_task = task
        log.info("notification_service.consumer_started", bank_id=bank_id)
    else:
        log.warning(
            "notification_service.consumer_not_started",
            bank_id=bank_id,
            reason="kafka_consumer or delivery engine unavailable",
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
    if getattr(app.state, "redis", None) is not None:
        try:
            await app.state.redis.aclose()
        except Exception:
            pass

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
        "engine": getattr(app.state, "engine", None) is not None,
        "email_channel": getattr(app.state, "email_channel", None) is not None,
        "whatsapp_channel": getattr(app.state, "whatsapp_channel", None) is not None,
    }
    # The delivery engine (outbox + at least one channel) must exist; kafka must be running
    operational = checks["kafka_consumer"] and checks["consumer_running"] and checks["engine"]
    return JSONResponse(
        content={"status": "ready" if operational else "degraded", "checks": checks},
        status_code=200 if operational else 503,
    )
