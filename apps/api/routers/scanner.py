"""
Scanner Registration & Fleet Monitoring.

Routes:
  POST   /v1/cts/scanner/register                    — Admin provisions SDK_PUSH scanner slot
  POST   /v1/cts/scanner/{registration_id}/heartbeat — SDK heartbeat (Bearer token, NOT JWT)
  GET    /v1/cts/scanner/fleet                        — Fleet status for all registrations
  GET    /v1/cts/scanner/{branch_ifsc}/status         — Per-branch scanner status
  DELETE /v1/cts/scanner/{registration_id}            — Deactivate a registration
  POST   /v1/cts/scanner/agent/heartbeat              — Go agent heartbeat (Bearer machine token)
  GET    /v1/cts/scanner/agent/status                 — Branch scanner status: ACTIVE/IDLE/OFFLINE

Auth model
──────────
  Admin routes (register / fleet / status / delete):
    JWT from bank's IdP — FastAPI Depends(get_current_user), same as every other ASTRA route.
    Roles: bank_it_admin, platform_admin — write.
            ops_manager — read only (fleet / status).

  Heartbeat endpoint:
    Authorization: Bearer <registration_token>
    This is a machine identity token issued at registration, NOT a user JWT.
    The SDK runs unattended at the branch; it has no user session.
    Token is stored as SHA-256 hash; plaintext is shown exactly once.
    Constant-time comparison (hmac.compare_digest) prevents timing attacks.
    The heartbeat route has NO get_current_user dependency — intentional.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()
tracer = trace.get_tracer(__name__)

router_v1 = APIRouter(prefix="/v1/cts/scanner", tags=["Scanner Fleet v1"])

# ── Role sets ─────────────────────────────────────────────────────────────────

_WRITE_ROLES = {"bank_it_admin", "platform_admin"}
_READ_ROLES  = {"bank_it_admin", "platform_admin", "ops_manager"}

# ── In-memory store (test / no-DB path) ──────────────────────────────────────

_SCANNER_STORE: dict[str, dict] = {}

# ── Auth dependency ───────────────────────────────────────────────────────────


def get_current_user(request: Request) -> dict[str, Any]:
    """
    FastAPI dependency — resolves the authenticated user from the JWT.

    In production, delegates to require_user_context.
    In tests, overridden via app.dependency_overrides[get_current_user].
    Raises 401 if no valid auth is present.
    """
    try:
        from apps.api.dependencies import require_user_context
        ctx = require_user_context(request)
        return {
            "bank_id": ctx.bank_id,
            "user_id": ctx.user_id,
            "role": ctx.role.value if hasattr(ctx.role, "value") else str(ctx.role),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )


# ── DB / helper utilities ─────────────────────────────────────────────────────


def _get_db_pool(request: Request):
    state = getattr(getattr(request, "app", None), "state", None)
    return getattr(state, "db_pool_cts", None) if state else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _compute_health(reg: dict) -> str:
    if not reg.get("last_heartbeat_at"):
        return "PENDING"
    last = reg["last_heartbeat_at"]
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    interval = reg.get("heartbeat_interval_seconds", 60)
    stale = (datetime.now(timezone.utc) - last).total_seconds()
    if stale < interval * 2:
        return "ONLINE"
    if stale < interval * 5:
        return "DEGRADED"
    return "OFFLINE"


# ── Pydantic models ───────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_ifsc: str = Field(..., min_length=11, max_length=11)
    branch_id: str
    scanner_config_id: Optional[str] = None
    heartbeat_interval_seconds: int = Field(default=60, ge=10, le=3600)


class RegisterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    registration_id: str
    token: str
    branch_ifsc: str
    status: str
    message: str


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    sdk_version: Optional[str] = None
    scans_queued: int = 0
    last_error: Optional[str] = None


class HeartbeatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    next_heartbeat_in: int


class RegistrationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    registration_id: str
    bank_id: str
    branch_id: str
    branch_ifsc: str
    sdk_version: Optional[str]
    status: str
    health: str
    last_heartbeat_at: Optional[str]
    last_scan_submitted_at: Optional[str]
    heartbeat_interval_seconds: int
    scans_today: int
    errors_today: int
    last_error: Optional[str]
    registered_at: str
    registered_by: str
    is_active: bool


class FleetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    registrations: list[RegistrationSummary]
    total: int


def _reg_to_summary(r: dict) -> RegistrationSummary:
    def _ts(v) -> Optional[str]:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return RegistrationSummary(
        registration_id=r["registration_id"],
        bank_id=r["bank_id"],
        branch_id=r["branch_id"],
        branch_ifsc=r["branch_ifsc"],
        sdk_version=r.get("sdk_version"),
        status=r.get("status", "PENDING"),
        health=_compute_health(r),
        last_heartbeat_at=_ts(r.get("last_heartbeat_at")),
        last_scan_submitted_at=_ts(r.get("last_scan_submitted_at")),
        heartbeat_interval_seconds=r.get("heartbeat_interval_seconds", 60),
        scans_today=r.get("scans_today", 0),
        errors_today=r.get("errors_today", 0),
        last_error=r.get("last_error"),
        registered_at=_ts(r.get("registered_at")) or "",
        registered_by=r.get("registered_by", ""),
        is_active=r.get("is_active", True),
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router_v1.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_scanner(
    body: RegisterRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> RegisterResponse:
    """
    Admin provisions a scanner registration slot.

    Returns registration_id + plaintext token — shown ONCE. Admin hands the
    token to the person installing the scanner SDK at the branch. The SDK
    stores it locally and uses it on every heartbeat call.
    """
    if current_user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    with tracer.start_as_current_span("scanner.register") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("branch_ifsc", body.branch_ifsc)

        ifsc = body.branch_ifsc.upper()
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT registration_id FROM cts.scanner_registrations "
                        "WHERE bank_id = $1 AND branch_ifsc = $2 AND is_active = true",
                        bank_id, ifsc,
                    )
                    if existing:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"An active registration already exists for branch {ifsc}. "
                                   "Deactivate it first.",
                        )
                    token = secrets.token_urlsafe(32)
                    reg_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "INSERT INTO cts.scanner_registrations "
                        "(registration_id, bank_id, branch_id, branch_ifsc, scanner_config_id, "
                        "registration_token_hash, status, heartbeat_interval_seconds, "
                        "registered_at, registered_by, is_active) "
                        "VALUES ($1,$2,$3,$4,$5,$6,'PENDING',$7,$8,$9,true)",
                        reg_id, bank_id, body.branch_id, ifsc, body.scanner_config_id,
                        _token_hash(token), body.heartbeat_interval_seconds,
                        now, current_user["user_id"],
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("scanner.register.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
        else:
            active_exists = any(
                r["bank_id"] == bank_id and r["branch_ifsc"] == ifsc and r.get("is_active", True)
                for r in _SCANNER_STORE.values()
            )
            if active_exists:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"An active registration already exists for branch {ifsc}.",
                )
            token = secrets.token_urlsafe(32)
            reg_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            _SCANNER_STORE[reg_id] = {
                "registration_id": reg_id,
                "bank_id": bank_id,
                "branch_id": body.branch_id,
                "branch_ifsc": ifsc,
                "scanner_config_id": body.scanner_config_id,
                "sdk_version": None,
                "registration_token_hash": _token_hash(token),
                "status": "PENDING",
                "last_heartbeat_at": None,
                "last_scan_submitted_at": None,
                "heartbeat_interval_seconds": body.heartbeat_interval_seconds,
                "scans_today": 0,
                "errors_today": 0,
                "last_error": None,
                "registered_at": now,
                "registered_by": current_user["user_id"],
                "is_active": True,
            }

        log.info("scanner.registered", bank_id=bank_id, branch_ifsc=ifsc, reg_id=reg_id)
        return RegisterResponse(
            registration_id=reg_id,
            token=token,
            branch_ifsc=ifsc,
            status="PENDING",
            message="Token shown once — store it securely. It cannot be retrieved again.",
        )


@router_v1.post(
    "/{registration_id}/heartbeat",
    response_model=HeartbeatResponse,
)
async def heartbeat(
    registration_id: str,
    body: HeartbeatRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> HeartbeatResponse:
    """
    SDK heartbeat — called every heartbeat_interval_seconds from the branch.

    Auth: Authorization: Bearer <registration_token>
    This is a machine token, NOT a user JWT. No get_current_user dependency
    here — intentional. The SDK has no user session.
    """
    with tracer.start_as_current_span("scanner.heartbeat") as span:
        span.set_attribute("registration_id", registration_id)

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Scanner token required: Authorization: Bearer <token>",
            )
        incoming_token = authorization[7:].strip()
        incoming_hash = _token_hash(incoming_token)

        db_pool = _get_db_pool(request)
        now = datetime.now(timezone.utc)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    reg = await conn.fetchrow(
                        "SELECT registration_id, bank_id, branch_ifsc, "
                        "registration_token_hash, heartbeat_interval_seconds, is_active "
                        "FROM cts.scanner_registrations WHERE registration_id = $1",
                        registration_id,
                    )
            except Exception as exc:
                log.error("scanner.heartbeat.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")

            if reg is None:
                raise HTTPException(status_code=404, detail="Registration not found")
            if not reg["is_active"]:
                raise HTTPException(status_code=403, detail="Registration deactivated")
            if not hmac.compare_digest(reg["registration_token_hash"], incoming_hash):
                log.warning("scanner.heartbeat.bad_token", registration_id=registration_id)
                raise HTTPException(status_code=401, detail="Invalid scanner token")

            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE cts.scanner_registrations SET "
                        "status = 'ONLINE', last_heartbeat_at = $2, "
                        "sdk_version = COALESCE($3, sdk_version), "
                        "last_error = $4 "
                        "WHERE registration_id = $1",
                        registration_id, now,
                        body.sdk_version, body.last_error,
                    )
            except Exception as exc:
                log.error("scanner.heartbeat.update_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")

            interval = reg["heartbeat_interval_seconds"]
        else:
            reg = _SCANNER_STORE.get(registration_id)
            if reg is None:
                raise HTTPException(status_code=404, detail="Registration not found")
            if not reg.get("is_active", True):
                raise HTTPException(status_code=403, detail="Registration deactivated")
            if not hmac.compare_digest(reg["registration_token_hash"], incoming_hash):
                log.warning("scanner.heartbeat.bad_token", registration_id=registration_id)
                raise HTTPException(status_code=401, detail="Invalid scanner token")

            reg["status"] = "ONLINE"
            reg["last_heartbeat_at"] = now.isoformat()
            if body.sdk_version is not None:
                reg["sdk_version"] = body.sdk_version
            if body.last_error is not None:
                reg["last_error"] = body.last_error
            interval = reg.get("heartbeat_interval_seconds", 60)

        log.info("scanner.heartbeat.ok", registration_id=registration_id)
        return HeartbeatResponse(status="OK", next_heartbeat_in=interval)


@router_v1.get("/fleet", response_model=FleetResponse)
async def fleet_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> FleetResponse:
    """Fleet monitoring — all scanner registrations for the authenticated bank."""
    if current_user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    with tracer.start_as_current_span("scanner.fleet") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT registration_id, bank_id, branch_id, branch_ifsc, sdk_version, "
                        "status, last_heartbeat_at, last_scan_submitted_at, "
                        "heartbeat_interval_seconds, scans_today, errors_today, last_error, "
                        "registered_at, registered_by, is_active "
                        "FROM cts.scanner_registrations "
                        "WHERE bank_id = $1 ORDER BY branch_ifsc",
                        bank_id,
                    )
            except Exception as exc:
                log.error("scanner.fleet.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
            regs = [_reg_to_summary(dict(r)) for r in rows]
        else:
            regs = [
                _reg_to_summary(r) for r in _SCANNER_STORE.values()
                if r["bank_id"] == bank_id
            ]
            regs.sort(key=lambda r: r.branch_ifsc)

        return FleetResponse(registrations=regs, total=len(regs))


@router_v1.get("/{branch_ifsc}/status", response_model=RegistrationSummary)
async def branch_scanner_status(
    branch_ifsc: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> RegistrationSummary:
    """Per-branch scanner status — returns the active registration for this branch."""
    if current_user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    with tracer.start_as_current_span("scanner.branch_status") as span:
        bank_id = current_user["bank_id"]
        ifsc = branch_ifsc.upper()
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("branch_ifsc", ifsc)

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT registration_id, bank_id, branch_id, branch_ifsc, sdk_version, "
                        "status, last_heartbeat_at, last_scan_submitted_at, "
                        "heartbeat_interval_seconds, scans_today, errors_today, last_error, "
                        "registered_at, registered_by, is_active "
                        "FROM cts.scanner_registrations "
                        "WHERE bank_id = $1 AND branch_ifsc = $2 AND is_active = true",
                        bank_id, ifsc,
                    )
            except Exception as exc:
                log.error("scanner.branch_status.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active scanner registration for branch {ifsc}",
                )
            return _reg_to_summary(dict(row))
        else:
            reg = next(
                (r for r in _SCANNER_STORE.values()
                 if r["bank_id"] == bank_id and r["branch_ifsc"] == ifsc and r.get("is_active", True)),
                None,
            )
            if not reg:
                raise HTTPException(
                    status_code=404,
                    detail=f"No active scanner registration for branch {ifsc}",
                )
            return _reg_to_summary(reg)


@router_v1.delete("/{registration_id}", response_model=RegistrationSummary)
async def deactivate_scanner(
    registration_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> RegistrationSummary:
    """
    Deactivate a scanner registration.

    The SDK will no longer be able to heartbeat (403 on next attempt).
    Token rotation: deactivate then re-register to issue a fresh token.
    """
    if current_user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    with tracer.start_as_current_span("scanner.deactivate") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("registration_id", registration_id)

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT registration_id FROM cts.scanner_registrations "
                        "WHERE registration_id = $1 AND bank_id = $2",
                        registration_id, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404, detail="Registration not found")
                    await conn.execute(
                        "UPDATE cts.scanner_registrations "
                        "SET status = 'OFFLINE', is_active = false "
                        "WHERE registration_id = $1",
                        registration_id,
                    )
                    row = await conn.fetchrow(
                        "SELECT registration_id, bank_id, branch_id, branch_ifsc, sdk_version, "
                        "status, last_heartbeat_at, last_scan_submitted_at, "
                        "heartbeat_interval_seconds, scans_today, errors_today, last_error, "
                        "registered_at, registered_by, is_active "
                        "FROM cts.scanner_registrations WHERE registration_id = $1",
                        registration_id,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("scanner.deactivate.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
            log.info("scanner.deactivated", registration_id=registration_id, bank_id=bank_id)
            return _reg_to_summary(dict(row))
        else:
            reg = _SCANNER_STORE.get(registration_id)
            if not reg or reg["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail="Registration not found")
            reg["status"] = "OFFLINE"
            reg["is_active"] = False
            log.info("scanner.deactivated", registration_id=registration_id, bank_id=bank_id)
            return _reg_to_summary(reg)


# ── Go agent heartbeat + status (cts.scanner_tokens, NOT cts.scanner_registrations) ──
#
# The Go CGO scanner agent (edge/cts-scanner-agent/) uses machine-bound tokens
# from cts.scanner_tokens — a separate table from the SDK-based scanner_registrations
# above. These two endpoints serve the agent's 30-second heartbeat and the
# BranchDashboard's scanner status pill.
#
# Three states (computed server-side from last_seen + active_session_id):
#   ACTIVE  — heartbeat within 90s AND active_session_id non-empty
#   IDLE    — heartbeat within 90s AND no active session
#   OFFLINE — no heartbeat in 90s (or never seen)
# ─────────────────────────────────────────────────────────────────────────────

# In-memory fallback for agent heartbeats when DB is unavailable (dev / tests).
_AGENT_STORE: dict[str, dict] = {}  # keyed by token_hash


class AgentHeartbeatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    branch_id: str
    active_session_id: str = ""  # empty string → IDLE


class AgentHeartbeatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["OK"]


class AgentStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: Literal["ACTIVE", "IDLE", "OFFLINE"]
    branch_id: str
    active_session_id: Optional[str]
    last_seen: Optional[str]       # ISO 8601 UTC
    last_seen_seconds_ago: Optional[int]


def _agent_state(last_seen, active_session_id: str) -> str:
    """Derive ACTIVE / IDLE / OFFLINE from DB row values."""
    if last_seen is None:
        return "OFFLINE"
    now = datetime.now(timezone.utc)
    if isinstance(last_seen, str):
        last_seen = datetime.fromisoformat(last_seen)
    age = (now - last_seen).total_seconds()
    if age > 90:
        return "OFFLINE"
    return "ACTIVE" if active_session_id else "IDLE"


@router_v1.post("/agent/heartbeat", response_model=AgentHeartbeatResponse)
async def agent_heartbeat(
    body: AgentHeartbeatRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> AgentHeartbeatResponse:
    """
    30-second heartbeat from the Go CGO scanner agent on the teller PC.

    Auth: Authorization: Bearer <machine-bound token from token.dat>
    Validates against cts.scanner_tokens — NOT a user JWT.
    Updates last_seen and active_session_id. No CSRF required (machine token).
    """
    with tracer.start_as_current_span("scanner.agent_heartbeat") as span:
        span.set_attribute("bank_id", body.bank_id)
        span.set_attribute("branch_id", body.branch_id)

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Scanner machine token required: Authorization: Bearer <token>",
            )
        incoming_token = authorization[7:].strip()
        incoming_hash = hashlib.sha256(incoming_token.encode()).hexdigest()

        now = datetime.now(timezone.utc)
        session_id = body.active_session_id or None  # store NULL rather than empty string

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT token_id, bank_id, branch_id, token_hash, revoked "
                        "FROM cts.scanner_tokens "
                        "WHERE bank_id = $1 AND branch_id = $2 AND revoked = false",
                        body.bank_id, body.branch_id,
                    )
            except Exception as exc:
                log.error("scanner.agent_heartbeat.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")

            if row is None:
                raise HTTPException(status_code=404, detail="No active scanner token for this branch")
            if not hmac.compare_digest(row["token_hash"], incoming_hash):
                log.warning("scanner.agent_heartbeat.bad_token",
                            bank_id=body.bank_id, branch_id=body.branch_id)
                raise HTTPException(status_code=401, detail="Invalid scanner token")

            try:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE cts.scanner_tokens "
                        "SET last_seen = $2, active_session_id = $3 "
                        "WHERE bank_id = $1 AND branch_id = $4 AND revoked = false",
                        body.bank_id, now, session_id, body.branch_id,
                    )
            except Exception as exc:
                log.error("scanner.agent_heartbeat.update_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
        else:
            # In-memory fallback — dev / unit tests
            if not hmac.compare_digest(
                _AGENT_STORE.get(incoming_hash, {}).get("token_hash", ""),
                incoming_hash,
            ):
                # No stored record → accept first-time heartbeat and store it
                _AGENT_STORE[incoming_hash] = {
                    "bank_id": body.bank_id,
                    "branch_id": body.branch_id,
                    "token_hash": incoming_hash,
                }
            entry = _AGENT_STORE[incoming_hash]
            entry["last_seen"] = now.isoformat()
            entry["active_session_id"] = body.active_session_id

        log.info("scanner.agent_heartbeat.ok",
                 bank_id=body.bank_id, branch_id=body.branch_id,
                 active_session_id=body.active_session_id or "IDLE")
        return AgentHeartbeatResponse(status="OK")


@router_v1.get("/agent/status", response_model=AgentStatusResponse)
async def agent_status(
    branch_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> AgentStatusResponse:
    """
    Current scanner state for a branch — polled by BranchDashboard every 15s.

    ACTIVE  — heartbeat within 90s AND a scan session is running
    IDLE    — heartbeat within 90s AND no active session
    OFFLINE — no heartbeat in 90s (or machine has never connected)
    """
    bank_id = current_user["bank_id"]

    with tracer.start_as_current_span("scanner.agent_status") as span:
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("branch_id", branch_id)

        db_pool = _get_db_pool(request)
        now = datetime.now(timezone.utc)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT last_seen, active_session_id "
                        "FROM cts.scanner_tokens "
                        "WHERE bank_id = $1 AND branch_id = $2 AND revoked = false",
                        bank_id, branch_id,
                    )
            except Exception as exc:
                log.error("scanner.agent_status.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")

            if row is None:
                return AgentStatusResponse(
                    state="OFFLINE",
                    branch_id=branch_id,
                    active_session_id=None,
                    last_seen=None,
                    last_seen_seconds_ago=None,
                )

            last_seen = row["last_seen"]
            active_session_id = row["active_session_id"] or ""
        else:
            # In-memory fallback
            entry = next(
                (v for v in _AGENT_STORE.values()
                 if v.get("bank_id") == bank_id and v.get("branch_id") == branch_id),
                None,
            )
            if entry is None:
                return AgentStatusResponse(
                    state="OFFLINE",
                    branch_id=branch_id,
                    active_session_id=None,
                    last_seen=None,
                    last_seen_seconds_ago=None,
                )
            last_seen = entry.get("last_seen")
            active_session_id = entry.get("active_session_id") or ""

        state = _agent_state(last_seen, active_session_id)

        last_seen_str = None
        seconds_ago = None
        if last_seen is not None:
            ls = last_seen if isinstance(last_seen, datetime) else datetime.fromisoformat(str(last_seen))
            last_seen_str = ls.isoformat()
            seconds_ago = int((now - ls).total_seconds())

        return AgentStatusResponse(
            state=state,
            branch_id=branch_id,
            active_session_id=active_session_id or None,
            last_seen=last_seen_str,
            last_seen_seconds_ago=seconds_ago,
        )
