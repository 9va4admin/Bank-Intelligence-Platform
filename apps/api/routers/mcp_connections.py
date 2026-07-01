"""
MCP Connections Configuration API

Routes for bank IT admins (SB and SMB) to configure MCP connections to:
  - SB_CBS           : Sponsor Bank's Core Banking System
  - SMB_CBS          : Sub-Member Bank's Core Banking System
  - SIGNATURE_VAULT  : Redis Signature Vault (fed by CBS signature extraction)
  - PPS_VAULT        : Redis Positive Pay vault
  - CANCELLED_LEAF   : Redis Bloom Filter for cancelled cheque serials

These connections are prerequisites before a clearing session can open.

Pre-flight gate: GET /v1/admin/mcp-connections/preflight
  → returns clearing_allowed=True only when all configured connections are ACTIVE.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, field_validator

from shared.audit.audit_event import AuditEvent, AuditEventType

log = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────────────────

_ALLOWED_ROLES = {"bank_it_admin", "ops_manager"}
_CBS_TYPES = {"SB_CBS", "SMB_CBS"}
_VALID_TYPES = {"SB_CBS", "SMB_CBS", "SIGNATURE_VAULT", "PPS_VAULT", "CANCELLED_LEAF"}
_VALID_CBS_VENDORS = {"finacle", "bancs", "flexcube"}

bearer = HTTPBearer(auto_error=False)

# ── In-memory store (replaced by YugabyteDB in production) ──────────────────


class _ConnectionStore:
    """Thread-safe in-memory store for MCP connection configs.

    Each record keyed by id string. In production: YugabyteDB cts schema.
    """

    def __init__(self):
        self._rows: Dict[str, dict] = {}

    def all_for_bank(self, bank_id: str) -> List[dict]:
        return [r for r in self._rows.values() if r["bank_id"] == bank_id]

    def get(self, connection_id: str) -> Optional[dict]:
        return self._rows.get(connection_id)

    def insert(self, row: dict) -> dict:
        self._rows[row["id"]] = row
        return row

    def update(self, connection_id: str, fields: dict) -> Optional[dict]:
        if connection_id not in self._rows:
            return None
        self._rows[connection_id].update(fields)
        self._rows[connection_id]["updated_at"] = _now()
        return self._rows[connection_id]

    def delete(self, connection_id: str) -> bool:
        if connection_id not in self._rows:
            return False
        del self._rows[connection_id]
        return True

    def exists(self, bank_id: str, connection_type: str, smb_id: Optional[str]) -> bool:
        for r in self._rows.values():
            if (
                r["bank_id"] == bank_id
                and r["connection_type"] == connection_type
                and r.get("smb_id") == smb_id
            ):
                return True
        return False


_global_store = _ConnectionStore()


def get_store() -> _ConnectionStore:
    return _global_store


# ── Audit emit ───────────────────────────────────────────────────────────────


async def _emit_audit(event_type: AuditEventType, bank_id: str, payload: dict) -> None:
    """Emit an MCP connection audit event.

    In production: publishes to platform.audit.events Kafka topic → audit-service
    writes to Immudb with HSM signature.

    Fire-and-forget from router perspective — failures are logged but do not
    block the HTTP response (Temporal audit-service handles retries).
    """
    try:
        event = AuditEvent(
            event_type=event_type,
            bank_id=bank_id,
            payload=payload,
        )
        # In production: kafka_producer.publish("platform.audit.events", event.to_json())
        log.info(
            "mcp_conn.audit_event",
            event_type=event_type.value,
            bank_id=bank_id,
            event_id=event.event_id,
        )
    except Exception as exc:
        # Never let audit failure break the user-facing operation
        log.error("mcp_conn.audit_emit_failed", event_type=event_type.value, bank_id=bank_id, error=str(exc))


# ── Auth dependency ──────────────────────────────────────────────────────────


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer),
) -> dict:
    """Validate bearer token and return user context.

    In production: validate JWT from bank IdP (SAML-issued), extract claims.
    In tests: dependency_overrides replaces this entirely.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    if not token.startswith("test-token-"):
        raise HTTPException(status_code=401, detail="Invalid token")
    bank_id = token[len("test-token-"):]
    return {
        "bank_id": bank_id,
        "user_id": f"user-{bank_id}",
        "role": "bank_it_admin",
        "bank_type": "SB",
        "smb_id": None,
    }


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")
    return user


# ── Connection tester dependency ─────────────────────────────────────────────


async def _default_tester(row: dict):
    """Default connection tester: attempts actual HTTP/Redis probe.

    Returns (success: bool, latency_ms: int | None, error: str | None).
    In production this probes CBS endpoint or Redis PING with mTLS.
    In tests: dependency_overrides replaces this.
    """
    import time
    t0 = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            url = row.get("endpoint_url", "")
            if not url:
                return False, None, "No endpoint_url configured"
            resp = await client.get(url + "/health", timeout=10.0)
            latency_ms = int((time.monotonic() - t0) * 1000)
            return resp.status_code < 500, latency_ms, None
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return False, latency_ms, str(exc)


def get_connection_tester() -> Callable:
    return _default_tester


# ── Pydantic models ──────────────────────────────────────────────────────────


class MCPConnectionCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_type: str
    smb_id: Optional[str] = None
    smb_name: Optional[str] = None
    cbs_vendor: Optional[str] = None
    endpoint_url: Optional[str] = None
    vault_secret_ref: Optional[str] = None

    @field_validator("connection_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"connection_type must be one of {_VALID_TYPES}")
        return v

    @field_validator("cbs_vendor")
    @classmethod
    def validate_vendor(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_CBS_VENDORS:
            raise ValueError(f"cbs_vendor must be one of {_VALID_CBS_VENDORS}")
        return v


class MCPConnectionUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    cbs_vendor: Optional[str] = None
    endpoint_url: Optional[str] = None
    vault_secret_ref: Optional[str] = None
    smb_name: Optional[str] = None

    @field_validator("cbs_vendor")
    @classmethod
    def validate_vendor(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_CBS_VENDORS:
            raise ValueError(f"cbs_vendor must be one of {_VALID_CBS_VENDORS}")
        return v


class MCPConnectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    bank_id: str
    connection_type: str
    smb_id: Optional[str]
    smb_name: Optional[str]
    cbs_vendor: Optional[str]
    endpoint_url: None = None               # raw URL never returned
    endpoint_url_masked: Optional[str]
    vault_secret_ref: Optional[str]
    status: str
    last_tested_at: Optional[str]
    last_test_latency_ms: Optional[int]
    last_sync_at: Optional[str]
    vault_record_count: Optional[int]
    error_message: Optional[str]
    created_at: str
    updated_at: Optional[str]
    created_by: str


class MCPConnectionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    bank_id: str
    connections: List[MCPConnectionResponse]
    total: int


class TestConnectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_id: str
    success: bool
    latency_ms: Optional[int]
    error: Optional[str]


class TriggerSyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_id: str
    workflow_id: str
    started_at: str


class PreflightCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_id: str
    connection_type: str
    smb_id: Optional[str]
    status: str


class PreflightResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    bank_id: str
    clearing_allowed: bool
    blocking_count: int
    checks: List[PreflightCheck]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_url(url: Optional[str]) -> Optional[str]:
    """Return scheme://host/*** — hide path, credentials, and query string."""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # Strip credentials from netloc
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}/***"
    except Exception:
        return "***"


def _row_to_response(row: dict) -> MCPConnectionResponse:
    return MCPConnectionResponse(
        id=row["id"],
        bank_id=row["bank_id"],
        connection_type=row["connection_type"],
        smb_id=row.get("smb_id"),
        smb_name=row.get("smb_name"),
        cbs_vendor=row.get("cbs_vendor"),
        endpoint_url=None,
        endpoint_url_masked=_mask_url(row.get("endpoint_url")),
        vault_secret_ref=row.get("vault_secret_ref"),
        status=row["status"],
        last_tested_at=row.get("last_tested_at"),
        last_test_latency_ms=row.get("last_test_latency_ms"),
        last_sync_at=row.get("last_sync_at"),
        vault_record_count=row.get("vault_record_count"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
        created_by=row["created_by"],
    )


def _scope_check(user: dict, row: dict):
    """Raise 403 if SMB user tries to access a row belonging to a different SMB."""
    if user["bank_type"] == "SMB":
        if row.get("smb_id") != user.get("smb_id"):
            raise HTTPException(status_code=403, detail="Access denied: not your SMB connection")


# ── Router ───────────────────────────────────────────────────────────────────

router_v1 = APIRouter(prefix="/v1/admin/mcp-connections", tags=["MCP Connections v1"])


@router_v1.get("/preflight", response_model=PreflightResponse)
async def get_preflight(
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    """Pre-flight gate: returns clearing_allowed=True only if ALL connections are ACTIVE."""
    rows = store.all_for_bank(user["bank_id"])
    if user["bank_type"] == "SMB":
        rows = [r for r in rows if r.get("smb_id") == user.get("smb_id")]

    blocking = [r for r in rows if r["status"] != "ACTIVE"]
    checks = [
        PreflightCheck(
            connection_id=r["id"],
            connection_type=r["connection_type"],
            smb_id=r.get("smb_id"),
            status=r["status"],
        )
        for r in rows
    ]
    return PreflightResponse(
        bank_id=user["bank_id"],
        clearing_allowed=len(blocking) == 0,
        blocking_count=len(blocking),
        checks=checks,
    )


@router_v1.get("/", response_model=MCPConnectionListResponse)
async def list_connections(
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    rows = store.all_for_bank(user["bank_id"])
    if user["bank_type"] == "SMB":
        rows = [r for r in rows if r.get("smb_id") == user.get("smb_id")]
    conns = [_row_to_response(r) for r in rows]
    return MCPConnectionListResponse(
        bank_id=user["bank_id"],
        connections=conns,
        total=len(conns),
    )


@router_v1.post("/", response_model=MCPConnectionResponse, status_code=201)
async def create_connection(
    body: MCPConnectionCreate,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    # SMB_CBS must have smb_id
    if body.connection_type == "SMB_CBS" and not body.smb_id:
        raise HTTPException(status_code=422, detail="smb_id required for SMB_CBS connection")

    # SMB admin can only create for their own smb_id
    if user["bank_type"] == "SMB":
        if body.connection_type == "SMB_CBS" and body.smb_id != user.get("smb_id"):
            raise HTTPException(status_code=403, detail="SMB admin can only configure their own CBS connection")

    # Duplicate check: unique on (bank_id, connection_type, smb_id)
    if store.exists(user["bank_id"], body.connection_type, body.smb_id):
        raise HTTPException(
            status_code=409,
            detail=f"Connection {body.connection_type} already exists for this bank/SMB",
        )

    row = {
        "id": str(uuid.uuid4()),
        "bank_id": user["bank_id"],
        "connection_type": body.connection_type,
        "smb_id": body.smb_id,
        "smb_name": body.smb_name,
        "cbs_vendor": body.cbs_vendor,
        "endpoint_url": body.endpoint_url,
        "vault_secret_ref": body.vault_secret_ref,
        "status": "PENDING",
        "last_tested_at": None,
        "last_test_latency_ms": None,
        "last_sync_at": None,
        "vault_record_count": None,
        "error_message": None,
        "created_at": _now(),
        "updated_at": None,
        "created_by": user["user_id"],
    }
    store.insert(row)
    await _emit_audit(AuditEventType.MCP_CONN_CREATED, user["bank_id"], {
        "connection_id": row["id"],
        "connection_type": body.connection_type,
        "smb_id": body.smb_id or "—",
        "created_by": user["user_id"],
    })
    return _row_to_response(row)


@router_v1.get("/{connection_id}", response_model=MCPConnectionResponse)
async def get_connection(
    connection_id: str,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    row = store.get(connection_id)
    if not row or row["bank_id"] != user["bank_id"]:
        raise HTTPException(status_code=404, detail="Connection not found")
    _scope_check(user, row)
    return _row_to_response(row)


@router_v1.put("/{connection_id}", response_model=MCPConnectionResponse)
async def update_connection(
    connection_id: str,
    body: MCPConnectionUpdate,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    row = store.get(connection_id)
    if not row or row["bank_id"] != user["bank_id"]:
        raise HTTPException(status_code=404, detail="Connection not found")
    _scope_check(user, row)

    updates: Dict[str, Any] = {"status": "PENDING"}  # reset to PENDING on any edit
    if body.cbs_vendor is not None:
        updates["cbs_vendor"] = body.cbs_vendor
    if body.endpoint_url is not None:
        updates["endpoint_url"] = body.endpoint_url
    if body.vault_secret_ref is not None:
        updates["vault_secret_ref"] = body.vault_secret_ref
    if body.smb_name is not None:
        updates["smb_name"] = body.smb_name

    updated = store.update(connection_id, updates)
    await _emit_audit(AuditEventType.MCP_CONN_UPDATED, user["bank_id"], {
        "connection_id": connection_id,
        "connection_type": row["connection_type"],
        "updated_by": user["user_id"],
        "fields_changed": [k for k in updates if k != "status"],
    })
    return _row_to_response(updated)


@router_v1.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    row = store.get(connection_id)
    if not row or row["bank_id"] != user["bank_id"]:
        raise HTTPException(status_code=404, detail="Connection not found")
    _scope_check(user, row)
    await _emit_audit(AuditEventType.MCP_CONN_DELETED, user["bank_id"], {
        "connection_id": connection_id,
        "connection_type": row["connection_type"],
        "smb_id": row.get("smb_id") or "—",
        "deleted_by": user["user_id"],
    })
    store.delete(connection_id)


@router_v1.post("/{connection_id}/test", response_model=TestConnectionResponse)
async def test_connection(
    connection_id: str,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
    tester: Callable = Depends(get_connection_tester),
):
    row = store.get(connection_id)
    if not row or row["bank_id"] != user["bank_id"]:
        raise HTTPException(status_code=404, detail="Connection not found")
    _scope_check(user, row)

    success, latency_ms, error = await tester(row)

    store.update(connection_id, {
        "status": "ACTIVE" if success else "ERROR",
        "last_tested_at": _now(),
        "last_test_latency_ms": latency_ms,
        "error_message": error,
    })

    audit_type = AuditEventType.MCP_CONN_TESTED_OK if success else AuditEventType.MCP_CONN_TESTED_FAIL
    await _emit_audit(audit_type, user["bank_id"], {
        "connection_id": connection_id,
        "connection_type": row["connection_type"],
        "latency_ms": latency_ms,
        "error": error or "—",
        "tested_by": user["user_id"],
    })

    return TestConnectionResponse(
        connection_id=connection_id,
        success=success,
        latency_ms=latency_ms,
        error=error,
    )


@router_v1.post("/{connection_id}/sync", response_model=TriggerSyncResponse)
async def trigger_sync(
    connection_id: str,
    user: dict = Depends(_require_admin),
    store: _ConnectionStore = Depends(get_store),
):
    row = store.get(connection_id)
    if not row or row["bank_id"] != user["bank_id"]:
        raise HTTPException(status_code=404, detail="Connection not found")
    _scope_check(user, row)

    if row["connection_type"] not in _CBS_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Sync only available for CBS connection types ({_CBS_TYPES}), not {row['connection_type']}",
        )

    if row["status"] != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot sync a connection in status={row['status']}. Must be ACTIVE.",
        )

    # In production: trigger Temporal VaultSyncWorkflow or DeltaVaultSyncWorkflow
    workflow_id = f"cts-vaultsync-{user['bank_id']}-{connection_id[:8]}"
    now = _now()
    store.update(connection_id, {"last_sync_at": now})
    await _emit_audit(AuditEventType.MCP_CONN_SYNC_TRIGGERED, user["bank_id"], {
        "connection_id": connection_id,
        "connection_type": row["connection_type"],
        "workflow_id": workflow_id,
        "triggered_by": user["user_id"],
    })

    return TriggerSyncResponse(
        connection_id=connection_id,
        workflow_id=workflow_id,
        started_at=now,
    )
