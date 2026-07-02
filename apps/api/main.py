"""
ASTRA API Gateway — FastAPI application entry point.

Lifespan wiring:
  - Redis CTS cluster (signature vault, PPS vault, session cache, rate limiting, distributed locks)
  - Redis EJ cluster (ATM health cache, canonical cache, OEM fingerprint cache)
  - Kafka producers: cts-producer (cts.* topics), ej-producer (ej.* topics)
  - Temporal client (workflow orchestration)
  - Rate limiting middleware (Redis sliding window)
  - Cache invalidation consumer (platform.config.changed → Redis DEL)
  - OTel tracing setup

All state stored on app.state — accessible to route handlers via Request.
"""
import asyncio
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.middleware.rate_limit import RateLimitMiddleware
from apps.api.middleware.security_violations import SecurityViolationMiddleware
from apps.api.routers import cts, ej, disputes, audit, admin, notifications
from apps.api.routers import batch, users, mcp_connections
from shared.config.config_service import config_service
from shared.event_bus.producer import EventProducer as KafkaEventProducer
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

SERVICE_NAME = "api-gateway"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise all infrastructure connections and store on app.state.
    Shutdown: close all connections gracefully.
    """
    log.info("api_gateway.starting", service=SERVICE_NAME)

    # --- OTel (first — so all startup spans are captured) ---
    configure_otel(service_name=SERVICE_NAME, service_version="1.0.0")

    # --- Config service (Layer 3-5) ---
    try:
        await config_service.initialise()
    except Exception as exc:
        log.error("api_gateway.config_service_init_failed", error=str(exc))
        raise

    # --- Redis CTS cluster ---
    # Hosts signature vault, PPS vault, session cache, rate limiting, distributed locks,
    # idempotency keys, dashboard aggregates, audit stream buffer
    try:
        redis_cts_url = await config_service.get_secret("redis.cts.url")
        app.state.redis_cts = aioredis.from_url(
            redis_cts_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
        await app.state.redis_cts.ping()
        log.info("api_gateway.redis_cts_connected")
    except Exception as exc:
        log.error("api_gateway.redis_cts_failed", error=str(exc))
        app.state.redis_cts = None

    # --- Redis EJ cluster ---
    # Hosts EJ health cache, EJ canonical cache, OEM fingerprint cache, EJ dashboard aggregates
    try:
        redis_ej_url = await config_service.get_secret("redis.ej.url")
        app.state.redis_ej = aioredis.from_url(
            redis_ej_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )
        await app.state.redis_ej.ping()
        log.info("api_gateway.redis_ej_connected")
    except Exception as exc:
        log.error("api_gateway.redis_ej_failed", error=str(exc))
        app.state.redis_ej = None

    # --- Kafka producer: CTS topics (cts.inward, cts.decisions, cts.human_review ...) ---
    try:
        kafka_servers = await config_service.get_secret("kafka.bootstrap_servers")
        app.state.kafka_producer_cts = KafkaEventProducer(
            bootstrap_servers=kafka_servers,
            module="cts",
        )
        log.info("api_gateway.kafka_cts_producer_ready")
    except Exception as exc:
        log.error("api_gateway.kafka_cts_producer_failed", error=str(exc))
        app.state.kafka_producer_cts = None
    # Alias for backward compat with cts.py routes that reference kafka_producer
    app.state.kafka_producer = app.state.kafka_producer_cts

    # --- Kafka producer: EJ topics (ej.raw.ingested, ej.canonical ...) ---
    try:
        kafka_servers = await config_service.get_secret("kafka.bootstrap_servers")
        app.state.kafka_producer_ej = KafkaEventProducer(
            bootstrap_servers=kafka_servers,
            module="ej",
        )
        log.info("api_gateway.kafka_ej_producer_ready")
    except Exception as exc:
        log.error("api_gateway.kafka_ej_producer_failed", error=str(exc))
        app.state.kafka_producer_ej = None

    # --- YugabyteDB CTS connection pool (pgbouncer-cts endpoint) ---
    # Used by mcp_connections router (YugabyteDBConnectionStore) and future CTS routers.
    # Isolated from EJ schema — pgbouncer-cts has access to cts schema only.
    try:
        import asyncpg
        db_cts_dsn = await config_service.get_secret("db.cts.dsn")
        app.state.db_pool_cts = await asyncpg.create_pool(
            dsn=db_cts_dsn,
            min_size=2,
            max_size=10,  # matches pgbouncer-cts max_connections per pod
            command_timeout=30,
        )
        log.info("api_gateway.db_pool_cts_ready")
    except Exception as exc:
        log.error("api_gateway.db_pool_cts_failed", error=str(exc))
        app.state.db_pool_cts = None

    # --- Temporal client ---
    try:
        from temporalio.client import Client as TemporalClient
        temporal_host = await config_service.get_secret("temporal.host")
        app.state.temporal_client = await TemporalClient.connect(temporal_host)
        log.info("api_gateway.temporal_connected", host=temporal_host)
    except Exception as exc:
        log.error("api_gateway.temporal_failed", error=str(exc))
        app.state.temporal_client = None

    # --- Cache invalidation consumer (platform.config.changed → Redis DEL) ---
    # Runs in background — Kafka consumer that deletes stale config cache entries
    cache_invalidator_task = None
    try:
        from shared.event_bus.cache_invalidator import CacheInvalidator
        from shared.event_bus.consumer import KafkaEventConsumer
        if app.state.redis_cts is not None:
            bank_id = config_service.bank_id
            invalidation_consumer = KafkaEventConsumer(
                bootstrap_servers=kafka_servers,
                group_id=f"cg-platform-config-cache-{bank_id}",
                topics=[f"platform.config.changed", f"platform.cache.invalidation"],
            )
            invalidator = CacheInvalidator(
                redis_cts=app.state.redis_cts,
                kafka_consumer=invalidation_consumer,
                bank_id=bank_id,
            )
            cache_invalidator_task = asyncio.create_task(invalidator.run())
            log.info("api_gateway.cache_invalidator_started")
    except Exception as exc:
        log.warning("api_gateway.cache_invalidator_failed", error=str(exc))

    log.info("api_gateway.ready", service=SERVICE_NAME)

    yield  # --- Application runs here ---

    # --- Shutdown ---
    log.info("api_gateway.shutting_down")

    if cache_invalidator_task:
        cache_invalidator_task.cancel()
        try:
            await asyncio.wait_for(cache_invalidator_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    if app.state.redis_cts:
        await app.state.redis_cts.aclose()
    if app.state.redis_ej:
        await app.state.redis_ej.aclose()

    if getattr(app.state, "db_pool_cts", None):
        await app.state.db_pool_cts.close()

    if app.state.kafka_producer_cts:
        app.state.kafka_producer_cts.flush()
    if app.state.kafka_producer_ej:
        app.state.kafka_producer_ej.flush()

    await config_service.shutdown()
    log.info("api_gateway.stopped")


app = FastAPI(
    title="ASTRA Bank Intelligence Platform",
    version="1.0.0",
    description="Automated Settlement and Transaction Recognition Architecture",
    docs_url="/docs" if os.environ.get("ENV") == "development" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# --- Middleware (order matters: outermost runs first) ---

# CORS — internal ops workstation only (not public internet)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ops.astra.internal"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)

# Security violations — catches TenantIsolationError / BankIsolationError, suspends user
# Must be outermost so it catches errors from all inner middleware and route handlers
app.add_middleware(SecurityViolationMiddleware)

# Rate limiting — Redis sliding window, per-bank per-endpoint
app.add_middleware(RateLimitMiddleware)

# --- Routers ---
app.include_router(cts.router_v1)
app.include_router(ej.router_v1)
app.include_router(disputes.router_v1)
app.include_router(audit.router_v1)
app.include_router(admin.router_v1)
app.include_router(notifications.router_v1)
app.include_router(batch.router_v1)
app.include_router(users.router_v1)
app.include_router(mcp_connections.router_v1)


# --- Health endpoints (no auth — Kubernetes probes) ---

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/health/ready", include_in_schema=False)
async def readiness():
    checks = {
        "config_service": config_service._ready,
        "redis_cts": app.state.redis_cts is not None,
        "redis_ej": app.state.redis_ej is not None,
        "temporal": app.state.temporal_client is not None,
        "kafka_cts": app.state.kafka_producer_cts is not None,
        "kafka_ej": app.state.kafka_producer_ej is not None,
    }
    # Only config_service and redis_cts are critical — rest degrade gracefully
    critical_healthy = checks["config_service"] and checks["redis_cts"]
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ready" if critical_healthy else "degraded", "checks": checks},
        status_code=200 if critical_healthy else 503,
    )
