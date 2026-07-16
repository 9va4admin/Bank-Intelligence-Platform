"""
audit-service — drains the Redis Streams audit buffer (shared/audit/stream_buffer.py)
and writes each event to Immudb via AuditStreamConsumer.

This is the "audit-service consumer" named in stream_buffer.py's own module
docstring and in shared/audit/audit_event.py's write-path documentation
("Every write to YugabyteDB that modifies a cheque or EJ record must be
followed by an ImmudbClient.write_event() call" — this is that follow-up,
for producers that buffer through Redis Streams rather than writing
directly). One instance per bank, matching ASTRA's per-bank K8s namespace
isolation model — see CLAUDE.md §2.1.

HSM is not yet wired anywhere in this codebase (tracked separately — Vault
Transit vs PKCS11 is still an open architecture decision). AuditStreamConsumer
degrades to unsigned writes with a loud warning rather than skipping writes
entirely until that lands — see shared/audit/stream_consumer.py's docstring.
"""
from contextlib import asynccontextmanager
from typing import Any, Optional

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from shared.audit.stream_consumer import AuditStreamConsumer
from shared.config.config_service import config_service
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

SERVICE_NAME = "audit-service"


async def _build_redis_client(cfg: Any) -> Optional[Any]:
    try:
        import redis.asyncio as aioredis
        redis_cts_url = await cfg.get_secret("redis.cts.url")
        client = aioredis.from_url(
            redis_cts_url, encoding="utf-8", decode_responses=True, max_connections=10,
        )
        await client.ping()
        log.info("audit_service.redis_cts_connected")
        return client
    except Exception as exc:
        log.warning("audit_service.redis_cts_unavailable", error=str(exc))
        return None


async def _build_immudb_writer(cfg: Any, bank_id: str) -> Optional[Any]:
    try:
        from shared.audit.immudb_client import ImmudbClient
        from shared.audit.immudb_writer import AsyncImmudbWriter
        host = cfg.get_platform("immudb.host")
        port = int(cfg.get_platform("immudb.port"))
        client = ImmudbClient()
        client.connect(host=host, port=port, bank_id=bank_id)
        log.info("audit_service.immudb_ready")
        return AsyncImmudbWriter(client)
    except Exception as exc:
        log.warning("audit_service.immudb_unavailable", bank_id=bank_id, error=str(exc))
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("audit_service.starting", service=SERVICE_NAME)
    configure_otel(service_name=SERVICE_NAME, service_version="1.0.0")

    try:
        await config_service.initialise()
    except Exception as exc:
        log.error("audit_service.config_service_init_failed", error=str(exc))

    bank_id = getattr(config_service, "bank_id", None) or "unknown"

    app.state.redis_cts = await _build_redis_client(config_service)
    app.state.immudb_writer = await _build_immudb_writer(config_service, bank_id)
    app.state.hsm = None  # not yet wired anywhere in this codebase — see module docstring

    app.state.consumer = None
    if app.state.redis_cts is not None and app.state.immudb_writer is not None:
        consumer = AuditStreamConsumer(
            redis_client=app.state.redis_cts,
            immudb_writer=app.state.immudb_writer,
            hsm=app.state.hsm,
            bank_id=bank_id,
            consumer_name=f"{SERVICE_NAME}-{bank_id}",
        )
        await consumer.start()
        app.state.consumer = consumer
        log.info("audit_service.consumer_started", bank_id=bank_id)
    else:
        log.warning(
            "audit_service.consumer_not_started",
            bank_id=bank_id,
            redis_available=app.state.redis_cts is not None,
            immudb_available=app.state.immudb_writer is not None,
        )

    log.info("audit_service.ready", service=SERVICE_NAME, bank_id=bank_id)
    yield

    if app.state.consumer is not None:
        await app.state.consumer.stop()
    if app.state.redis_cts is not None:
        await app.state.redis_cts.aclose()
    log.info("audit_service.shutdown_complete")


app = FastAPI(
    title="ASTRA Audit Service",
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
        "redis_cts": getattr(app.state, "redis_cts", None) is not None,
        "immudb": getattr(app.state, "immudb_writer", None) is not None,
        "consumer_running": getattr(app.state, "consumer", None) is not None,
    }
    all_healthy = all(checks.values())
    return JSONResponse(
        content={"status": "ready" if all_healthy else "degraded", "checks": checks},
        status_code=200 if all_healthy else 503,
    )
