"""
EEH (External Exchange Hub) — FastAPI app.

Responsibilities:
  - Health / metrics endpoints (Kubernetes probes)
  - Session lifecycle REST endpoints (open, close)
  - SSE status feed stream (branch portal real-time feedback)
  - Lifespan: connects Redis, DB pool; creates EEHSessionManager + SSEPublisher

gRPC upload server (UploadCheque streaming RPC) runs as a separate grpcio server
started in the same lifespan — see apps/eeh/grpc_server.py (Phase 2 continuation).
"""
from __future__ import annotations

import structlog
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps.eeh.session import (
    EEHSession,
    EEHSessionManager,
    SessionAlreadyActiveError,
    SessionNotFoundError,
)
from apps.eeh.sse import SSEPublisher, branch_sse_stream

log = structlog.get_logger()

SERVICE_NAME = "eeh-service"

# ── Module-level singletons (replaced by lifespan in production) ───────────────
# These start as None; in test code, callers patch `apps.eeh.main.session_manager`.

session_manager: Optional[EEHSessionManager] = None
sse_publisher: Optional[SSEPublisher] = None
_redis = None
_db = None


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Connect Redis and DB on startup; initialise session manager and SSE publisher.
    Tear down connections on shutdown.
    """
    global session_manager, sse_publisher, _redis, _db

    log.info("eeh.starting", service=SERVICE_NAME)

    try:
        import redis.asyncio as aioredis
        from shared.config.config_service import config_service
        _redis = aioredis.from_url(
            config_service.get("redis.cts.url"),
            decode_responses=True,
        )
        await _redis.ping()
        log.info("eeh.redis_connected")
    except Exception as exc:
        log.warning("eeh.redis_unavailable", error=str(exc))
        _redis = None

    try:
        import asyncpg
        from shared.config.config_service import config_service
        _db = await asyncpg.create_pool(
            config_service.get("db.cts.dsn"),
            min_size=1,
            max_size=5,
        )
        log.info("eeh.db_connected")
    except Exception as exc:
        log.warning("eeh.db_unavailable", error=str(exc))
        _db = None

    if _redis is not None and _db is not None:
        session_manager = EEHSessionManager(redis=_redis, db=_db)
        sse_publisher = SSEPublisher(redis=_redis)

    yield

    log.info("eeh.shutting_down", service=SERVICE_NAME)
    if _db is not None:
        await _db.close()
    if _redis is not None:
        await _redis.aclose()


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title=f"ASTRA {SERVICE_NAME}",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/health/ready", include_in_schema=False)
async def readiness(response: Response):
    checks = {
        "redis": _redis is not None,
        "db": _db is not None,
        "session_manager": session_manager is not None,
    }
    all_ok = all(checks.values())
    response.status_code = 200 if all_ok else 503
    return {
        "status": "ready" if all_ok else "degraded",
        "service": SERVICE_NAME,
        "checks": checks,
    }


# ── Session lifecycle endpoints ────────────────────────────────────────────────

class OpenSessionRequest(BaseModel):
    bank_id: str
    branch_id: str
    operator_id: str
    cert_fingerprint: str
    hub_type: str
    clearing_date: date
    session_ttl_seconds: int = 14400  # 4 hours default


class OpenSessionResponse(BaseModel):
    session_id: str
    bank_id: str
    branch_id: str
    hub_type: str
    status: str
    clearing_date: str
    expires_at: str


class CloseSessionResponse(BaseModel):
    session_id: str
    status: str


@app.post("/v1/eeh/session/open", response_model=OpenSessionResponse, status_code=201)
async def open_session(body: OpenSessionRequest):
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialised")
    try:
        sess: EEHSession = await session_manager.open_session(
            bank_id=body.bank_id,
            branch_id=body.branch_id,
            operator_id=body.operator_id,
            cert_fingerprint=body.cert_fingerprint,
            hub_type=body.hub_type,
            clearing_date=body.clearing_date,
            session_ttl_seconds=body.session_ttl_seconds,
        )
    except SessionAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return OpenSessionResponse(
        session_id=sess.session_id,
        bank_id=sess.bank_id,
        branch_id=sess.branch_id,
        hub_type=sess.hub_type,
        status=sess.status,
        clearing_date=sess.clearing_date.isoformat(),
        expires_at=sess.expires_at.isoformat(),
    )


@app.post("/v1/eeh/session/{session_id}/close", response_model=CloseSessionResponse)
async def close_session(session_id: str):
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialised")
    await session_manager.close_session(session_id, status="CLOSED")
    return CloseSessionResponse(session_id=session_id, status="CLOSED")


# ── SSE stream ─────────────────────────────────────────────────────────────────

@app.get("/v1/eeh/stream/{branch_id}/{clearing_date_str}")
async def sse_stream(branch_id: str, clearing_date_str: str):
    if _redis is None:
        raise HTTPException(status_code=503, detail="Redis not available")
    try:
        clearing_date = date.fromisoformat(clearing_date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format (expected YYYY-MM-DD)")

    return StreamingResponse(
        branch_sse_stream(_redis, branch_id, clearing_date),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
