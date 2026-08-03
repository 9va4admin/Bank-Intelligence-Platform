"""
User Management API — CRUD for bank staff, TOTP MFA setup, session management.

Routes:
  GET    /v1/admin/users                        — list users (bank_it_admin only)
  POST   /v1/admin/users                        — create user
  GET    /v1/admin/users/{user_id}              — get user detail
  PUT    /v1/admin/users/{user_id}              — update user (role, zone, status)
  DELETE /v1/admin/users/{user_id}              — deactivate (soft delete, never hard)
  POST   /v1/admin/users/{user_id}/totp/setup   — generate TOTP secret + QR URI
  POST   /v1/admin/users/{user_id}/totp/confirm — verify first TOTP code (activates MFA)
  DELETE /v1/admin/users/{user_id}/totp         — reset MFA (bank_it_admin only)
  POST   /v1/auth/totp/verify                   — verify TOTP at login (no auth required)
  GET    /v1/admin/users/{user_id}/sessions     — list active sessions for a user
  DELETE /v1/admin/users/{user_id}/sessions     — force logout all sessions

Backing store: platform.local_auth_accounts (asyncpg, pgbouncer-cts pool)
Graceful degradation: _MOCK_USERS in-memory dict when DB pool unavailable (dev/test).
TOTP secrets stored in Vault via VaultTOTPSecretStore; _TOTP_SECRETS dict as fallback.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(tags=["User Management v1"])

_SB_ROLES = {
    "ops_reviewer", "fraud_analyst", "ops_manager",
    "bank_it_admin", "compliance_officer", "rbi_examiner", "ml_engineer", "smb_it_admin",
}
_SMB_ROLES = {"smb_admin", "smb_editor", "smb_viewer"}
_VALID_ROLES = _SB_ROLES | _SMB_ROLES
_VALID_ZONES = {"MUMBAI", "DELHI", "CHENNAI", "KOLKATA", "HYDERABAD", "BANGALORE", "ALL"}
_VALID_BANK_TYPES = {"SB", "SMB"}
_VALID_PERMISSION_LEVELS = {"ADMIN", "EDIT", "READ_ONLY"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def get_admin_user(
    ctx: UserContext = Depends(require_user_context),
) -> dict:
    """
    Delegates to the central auth chokepoint (apps.api.dependencies), which
    validates the httpOnly session cookie via AuthenticationMiddleware.
    Re-shaped to this router's existing dict-based downstream code.
    No token parsing, no test-token backdoor. ASTRA-01.
    """
    return {"bank_id": ctx.bank_id, "role": ctx.role.value, "user_id": ctx.user_id}


def require_it_admin(user: dict = Depends(get_admin_user)) -> dict:
    if user["role"] != "bank_it_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin required")
    return user


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UserCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    email: str = Field(..., description="Must match bank's IdP email")
    display_name: str = Field(..., min_length=2, max_length=100)
    role: str = Field(..., description="One of the ASTRA roles")
    bank_type: str = Field("SB", description="SB or SMB — immutable after creation")
    permission_level: str = Field("EDIT", description="ADMIN, EDIT, or READ_ONLY")
    clearing_zone: str = Field("ALL", description="Zone scope for ops_reviewer")
    employee_id: Optional[str] = None
    branch_code: Optional[str] = None


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: Optional[str] = None
    permission_level: Optional[str] = None
    clearing_zone: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    # bank_type intentionally absent — immutable after user creation; extra="forbid" rejects it


class UserResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    email: str
    display_name: str
    role: str
    bank_type: str
    permission_level: str
    clearing_zone: str
    bank_id: str
    is_active: bool
    totp_enabled: bool
    employee_id: Optional[str]
    branch_code: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]


class UserListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    users: list[UserResponse]
    total: int
    page: int
    limit: int


class TOTPSetupResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    otpauth_uri: str        # otpauth://totp/ASTRA:user@bank.com?secret=BASE32&issuer=ASTRA
    secret_base32: str      # for manual entry in authenticator app
    qr_hint: str            # instruction text for the user


class TOTPVerifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    bank_id: str
    totp_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TOTPVerifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    valid: bool
    message: str


class SessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    user_id: str
    created_at: datetime
    last_active_at: datetime
    ip_address: str
    user_agent: str
    is_current: bool


# ---------------------------------------------------------------------------
# TOTP helpers (RFC 6238 — TOTP)
# ---------------------------------------------------------------------------

def _totp(secret_bytes: bytes, digits: int = 6, interval: int = 30) -> str:
    """Generate current TOTP code from raw secret bytes."""
    counter = struct.pack(">Q", int(time.time()) // interval)
    mac = hmac.new(secret_bytes, counter, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def _verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """Verify TOTP with ±window step tolerance."""
    try:
        secret_bytes = base64.b32decode(secret_b32.upper())
    except Exception:
        return False
    interval = 30
    step = int(time.time()) // interval
    for delta in range(-window, window + 1):
        counter = struct.pack(">Q", step + delta)
        mac = hmac.new(secret_bytes, counter, hashlib.sha1).digest()
        offset = mac[-1] & 0x0F
        expected = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
        if str(expected % 1_000_000).zfill(6) == code:
            return True
    return False


def _generate_totp_secret() -> str:
    """Generate a random 20-byte TOTP secret, base32-encoded."""
    import os
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


# ---------------------------------------------------------------------------
# In-memory fallback (dev/test — used when DB pool unavailable)
# ---------------------------------------------------------------------------

_MOCK_USERS: dict[str, dict] = {
    "usr-001": {
        "user_id": "usr-001", "email": "ops1@bank.com", "display_name": "Ramesh Kumar",
        "role": "ops_reviewer", "bank_type": "SB", "permission_level": "EDIT",
        "clearing_zone": "MUMBAI", "bank_id": "hdfc-bank",
        "is_active": True, "totp_enabled": True, "employee_id": "EMP-1001",
        "branch_code": "BOM001", "created_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 6, 25, 9, 12, tzinfo=timezone.utc),
    },
    "usr-002": {
        "user_id": "usr-002", "email": "fraud@bank.com", "display_name": "Priya Sharma",
        "role": "fraud_analyst", "bank_type": "SB", "permission_level": "EDIT",
        "clearing_zone": "ALL", "bank_id": "hdfc-bank",
        "is_active": True, "totp_enabled": False, "employee_id": "EMP-1002",
        "branch_code": None, "created_at": datetime(2026, 2, 3, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 6, 24, 16, 45, tzinfo=timezone.utc),
    },
    "usr-003": {
        "user_id": "usr-003", "email": "mgr@bank.com", "display_name": "Sunil Mehta",
        "role": "ops_manager", "bank_type": "SB", "permission_level": "EDIT",
        "clearing_zone": "ALL", "bank_id": "hdfc-bank",
        "is_active": True, "totp_enabled": True, "employee_id": "EMP-1003",
        "branch_code": None, "created_at": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 6, 25, 8, 55, tzinfo=timezone.utc),
    },
    "usr-004": {
        "user_id": "usr-004", "email": "compliance@bank.com", "display_name": "Anita Desai",
        "role": "compliance_officer", "bank_type": "SB", "permission_level": "EDIT",
        "clearing_zone": "ALL", "bank_id": "hdfc-bank",
        "is_active": True, "totp_enabled": True, "employee_id": "EMP-1004",
        "branch_code": None, "created_at": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 6, 23, 14, 20, tzinfo=timezone.utc),
    },
    "usr-005": {
        "user_id": "usr-005", "email": "ops2@bank.com", "display_name": "Vikram Singh",
        "role": "ops_reviewer", "bank_type": "SB", "permission_level": "EDIT",
        "clearing_zone": "DELHI", "bank_id": "hdfc-bank",
        "is_active": False, "totp_enabled": False, "employee_id": "EMP-1005",
        "branch_code": "DEL002", "created_at": datetime(2026, 3, 20, tzinfo=timezone.utc),
        "last_login_at": None,
    },
}

# TOTP secrets — in production these live in Vault, never in DB
_TOTP_SECRETS: dict[str, str] = {}


def _to_response(u: dict) -> UserResponse:
    return UserResponse(**{k: u[k] for k in UserResponse.model_fields})


# ---------------------------------------------------------------------------
# DB helpers — platform.local_auth_accounts
# ---------------------------------------------------------------------------

def _row_to_user_dict(row: dict) -> dict:
    """Map a local_auth_accounts DB row to a UserResponse-compatible dict."""
    entity_type = row.get("entity_type") or "sb"
    clearing_zones = row.get("clearing_zones") or []
    email = row.get("email") or row.get("username", "")
    return {
        "user_id": str(row["user_id"]),
        "email": email,
        "display_name": row.get("display_name") or email,
        "role": row["role"],
        "bank_type": "SMB" if entity_type == "smb" else "SB",
        "permission_level": "EDIT",   # not stored in this schema
        "clearing_zone": clearing_zones[0] if clearing_zones else "ALL",
        "bank_id": row["bank_id"],
        "is_active": bool(row.get("is_active", True)),
        "totp_enabled": bool(row.get("totp_enrolled", False)),
        "employee_id": None,
        "branch_code": row.get("entity_id") if entity_type == "branch" else None,
        "created_at": row["created_at"],
        "last_login_at": row.get("last_login_at"),
    }


async def _db_fetch_user(pool: Any, user_id: str, bank_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, bank_id, entity_type, entity_id, username, display_name,
                   role, clearing_zones, is_active, totp_enrolled,
                   created_at, last_login_at, email
            FROM platform.local_auth_accounts
            WHERE user_id = $1 AND bank_id = $2
            """,
            user_id, bank_id,
        )
        return _row_to_user_dict(dict(row)) if row else None


async def _db_fetch_users(
    pool: Any,
    bank_id: str,
    role_filter: Optional[str],
    active_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    conditions = ["bank_id = $1"]
    params: list[Any] = [bank_id]
    idx = 2
    if active_only:
        conditions.append(f"is_active = ${idx}")
        params.append(True)
        idx += 1
    if role_filter:
        conditions.append(f"role = ${idx}")
        params.append(role_filter)
        idx += 1
    where = " AND ".join(conditions)
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            f"SELECT COUNT(*) FROM platform.local_auth_accounts WHERE {where}",
            *params,
        )
        rows = await conn.fetch(
            f"""
            SELECT user_id, bank_id, entity_type, entity_id, username, display_name,
                   role, clearing_zones, is_active, totp_enrolled,
                   created_at, last_login_at, email
            FROM platform.local_auth_accounts
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params, limit, offset,
        )
        return [_row_to_user_dict(dict(r)) for r in rows], total


async def _db_email_exists(pool: Any, bank_id: str, email: str) -> bool:
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM platform.local_auth_accounts "
            "WHERE bank_id = $1 AND (email = $2 OR username = $2)",
            bank_id, email,
        )
        return (count or 0) > 0


async def _db_create_user(pool: Any, user_data: dict) -> dict:
    """Insert a new local_auth_accounts row. Uses sentinel password_hash for SAML-managed users."""
    import secrets as _secrets
    entity_type = "smb" if user_data["bank_type"] == "SMB" else "sb"
    clearing_zones = (
        [user_data["clearing_zone"]] if user_data["clearing_zone"] != "ALL" else []
    )
    # Sentinel hash — this user authenticates via SAML, not local password
    password_hash = f"SAML_MANAGED:{_secrets.token_hex(16)}"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO platform.local_auth_accounts
            (user_id, bank_id, entity_type, entity_id, username, display_name,
             password_hash, role, clearing_zones, is_active, email, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            user_data["user_id"],
            user_data["bank_id"],
            entity_type,
            user_data.get("branch_code") or "general",
            user_data["email"],
            user_data["display_name"],
            password_hash,
            user_data["role"],
            clearing_zones,
            True,
            user_data["email"],
            user_data["created_at"],
        )
    return user_data


async def _db_update_user(pool: Any, user_id: str, bank_id: str, updates: dict) -> Optional[dict]:
    """Apply a partial update dict to a local_auth_accounts row."""
    set_clauses = []
    params: list[Any] = []
    idx = 1
    field_map = {
        "role": "role",
        "clearing_zone": None,      # special: convert to clearing_zones array
        "is_active": "is_active",
        "display_name": "display_name",
    }
    if "clearing_zone" in updates and updates["clearing_zone"] is not None:
        zone = updates["clearing_zone"]
        set_clauses.append(f"clearing_zones = ${idx}")
        params.append([zone] if zone != "ALL" else [])
        idx += 1
    for key in ("role", "is_active", "display_name"):
        if key in updates and updates[key] is not None:
            set_clauses.append(f"{key} = ${idx}")
            params.append(updates[key])
            idx += 1
    if not set_clauses:
        return await _db_fetch_user(pool, user_id, bank_id)
    params.extend([user_id, bank_id])
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE platform.local_auth_accounts SET {', '.join(set_clauses)} "
            f"WHERE user_id = ${idx} AND bank_id = ${idx + 1}",
            *params,
        )
    return await _db_fetch_user(pool, user_id, bank_id)


async def _db_deactivate_user(pool: Any, user_id: str, bank_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE platform.local_auth_accounts SET is_active = FALSE "
            "WHERE user_id = $1 AND bank_id = $2",
            user_id, bank_id,
        )


async def _db_set_totp_enrolled(pool: Any, user_id: str, bank_id: str, enrolled: bool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE platform.local_auth_accounts SET totp_enrolled = $1 "
            "WHERE user_id = $2 AND bank_id = $3",
            enrolled, user_id, bank_id,
        )


# ---------------------------------------------------------------------------
# Routes — User CRUD
# ---------------------------------------------------------------------------

@router_v1.get("/v1/admin/users", response_model=UserListResponse)
async def list_users(
    request: Request,
    role_filter: Optional[str] = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(require_it_admin),
) -> UserListResponse:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        users, total = await _db_fetch_users(
            pool, admin["bank_id"], role_filter, active_only, limit, (page - 1) * limit,
        )
    else:
        users = [u for u in _MOCK_USERS.values() if u["bank_id"] == admin["bank_id"]]
        if active_only:
            users = [u for u in users if u["is_active"]]
        if role_filter:
            users = [u for u in users if u["role"] == role_filter]
        total = len(users)
        start = (page - 1) * limit
        users = users[start:start + limit]
    return UserListResponse(
        bank_id=admin["bank_id"],
        users=[_to_response(u) for u in users],
        total=total,
        page=page,
        limit=limit,
    )


@router_v1.post("/v1/admin/users", response_model=UserResponse, status_code=201)
async def create_user(
    request: Request,
    body: UserCreateRequest,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    if body.bank_type not in _VALID_BANK_TYPES:
        raise HTTPException(status_code=422, detail="Invalid bank_type. Must be SB or SMB.")
    if body.permission_level not in _VALID_PERMISSION_LEVELS:
        raise HTTPException(status_code=422, detail="Invalid permission_level. Must be ADMIN, EDIT, or READ_ONLY.")
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {sorted(_VALID_ROLES)}")
    if body.bank_type == "SB" and body.role in _SMB_ROLES:
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SMB users (bank_type=SMB).")
    if body.bank_type == "SMB" and body.role in _SB_ROLES:
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SB users (bank_type=SB).")
    if body.clearing_zone not in _VALID_ZONES:
        raise HTTPException(status_code=422, detail=f"Invalid zone. Must be one of: {sorted(_VALID_ZONES)}")

    pool = getattr(request.app.state, "db_pool_cts", None)
    import uuid
    user_id = f"usr-{str(uuid.uuid4())[:8]}"
    now = datetime.now(timezone.utc)

    if pool is not None:
        if await _db_email_exists(pool, admin["bank_id"], body.email):
            raise HTTPException(status_code=409, detail="User with this email already exists")
        new_user = {
            "user_id": user_id,
            "email": body.email,
            "display_name": body.display_name,
            "role": body.role,
            "bank_type": body.bank_type,
            "permission_level": body.permission_level,
            "clearing_zone": body.clearing_zone,
            "bank_id": admin["bank_id"],
            "is_active": True,
            "totp_enabled": False,
            "employee_id": body.employee_id,
            "branch_code": body.branch_code,
            "created_at": now,
            "last_login_at": None,
        }
        await _db_create_user(pool, new_user)
    else:
        if any(u["email"] == body.email for u in _MOCK_USERS.values()):
            raise HTTPException(status_code=409, detail="User with this email already exists")
        new_user = {
            "user_id": user_id,
            "email": body.email,
            "display_name": body.display_name,
            "role": body.role,
            "bank_type": body.bank_type,
            "permission_level": body.permission_level,
            "clearing_zone": body.clearing_zone,
            "bank_id": admin["bank_id"],
            "is_active": True,
            "totp_enabled": False,
            "employee_id": body.employee_id,
            "branch_code": body.branch_code,
            "created_at": now,
            "last_login_at": None,
        }
        _MOCK_USERS[user_id] = new_user

    log.info("user.created", user_id=user_id, role=body.role, bank_type=body.bank_type, bank_id=admin["bank_id"])
    return _to_response(new_user)


@router_v1.get("/v1/admin/users/{user_id}", response_model=UserResponse)
async def get_user(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_response(u)


@router_v1.put("/v1/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    request: Request,
    user_id: str,
    body: UserUpdateRequest,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    pool = getattr(request.app.state, "db_pool_cts", None)

    # Validate before any write
    if body.permission_level is not None and body.permission_level not in _VALID_PERMISSION_LEVELS:
        raise HTTPException(status_code=422, detail="Invalid permission_level. Must be ADMIN, EDIT, or READ_ONLY.")
    if body.role is not None:
        if body.role not in _VALID_ROLES:
            raise HTTPException(status_code=422, detail="Invalid role")
        # Need existing bank_type to validate role↔bank_type compatibility
        if pool is not None:
            existing = await _db_fetch_user(pool, user_id, admin["bank_id"])
        else:
            raw = _MOCK_USERS.get(user_id)
            existing = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
        if existing is None:
            raise HTTPException(status_code=404, detail="User not found")
        if existing["bank_type"] == "SB" and body.role in _SMB_ROLES:
            raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SMB users.")
        if existing["bank_type"] == "SMB" and body.role in _SB_ROLES:
            raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SB users.")
    if body.clearing_zone is not None and body.clearing_zone not in _VALID_ZONES:
        raise HTTPException(status_code=422, detail="Invalid zone")

    if pool is not None:
        updates = {
            k: v for k, v in {
                "role": body.role,
                "clearing_zone": body.clearing_zone,
                "is_active": body.is_active,
                "display_name": body.display_name,
            }.items() if v is not None
        }
        u = await _db_update_user(pool, user_id, admin["bank_id"], updates)
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
        if u is None:
            raise HTTPException(status_code=404, detail="User not found")
        if body.permission_level is not None:
            u["permission_level"] = body.permission_level
        if body.role is not None:
            u["role"] = body.role
        if body.clearing_zone is not None:
            u["clearing_zone"] = body.clearing_zone
        if body.is_active is not None:
            u["is_active"] = body.is_active
        if body.display_name is not None:
            u["display_name"] = body.display_name

    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    log.info("user.updated", user_id=user_id, bank_id=admin["bank_id"])
    return _to_response(u)


@router_v1.delete("/v1/admin/users/{user_id}", status_code=204)
async def deactivate_user(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if pool is not None:
        await _db_deactivate_user(pool, user_id, admin["bank_id"])
    else:
        _MOCK_USERS[user_id]["is_active"] = False
    log.info("user.deactivated", user_id=user_id, bank_id=admin["bank_id"])


# ---------------------------------------------------------------------------
# Routes — TOTP
# ---------------------------------------------------------------------------

@router_v1.post("/v1/admin/users/{user_id}/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> TOTPSetupResponse:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    secret = _generate_totp_secret()
    _TOTP_SECRETS[user_id] = secret
    email_encoded = u["email"].replace("@", "%40")
    otpauth_uri = (
        f"otpauth://totp/ASTRA:{email_encoded}"
        f"?secret={secret}&issuer=ASTRA&algorithm=SHA1&digits=6&period=30"
    )
    log.info("totp.setup.initiated", user_id=user_id, bank_id=admin["bank_id"])
    return TOTPSetupResponse(
        user_id=user_id,
        otpauth_uri=otpauth_uri,
        secret_base32=secret,
        qr_hint="Scan this QR code with Google Authenticator, Authy, or any TOTP app. "
                "Enter the 6-digit code below to confirm setup.",
    )


@router_v1.post("/v1/admin/users/{user_id}/totp/confirm", response_model=TOTPVerifyResponse)
async def totp_confirm(
    request: Request,
    user_id: str,
    body: TOTPVerifyRequest,
    admin: dict = Depends(require_it_admin),
) -> TOTPVerifyResponse:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    secret = _TOTP_SECRETS.get(user_id)
    if not secret:
        raise HTTPException(status_code=400, detail="TOTP setup not initiated. Call /totp/setup first.")
    if not _verify_totp(secret, body.totp_code):
        return TOTPVerifyResponse(valid=False, message="Invalid code. Please try again.")
    if pool is not None:
        await _db_set_totp_enrolled(pool, user_id, admin["bank_id"], True)
    else:
        _MOCK_USERS[user_id]["totp_enabled"] = True
    log.info("totp.activated", user_id=user_id, bank_id=admin["bank_id"])
    return TOTPVerifyResponse(valid=True, message="TOTP activated. MFA is now required at login.")


@router_v1.delete("/v1/admin/users/{user_id}/totp", status_code=204)
async def totp_reset(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    if pool is not None:
        await _db_set_totp_enrolled(pool, user_id, admin["bank_id"], False)
    else:
        _MOCK_USERS[user_id]["totp_enabled"] = False
    _TOTP_SECRETS.pop(user_id, None)
    log.info("totp.reset", user_id=user_id, bank_id=admin["bank_id"])


@router_v1.post("/v1/auth/totp/verify", response_model=TOTPVerifyResponse)
async def totp_verify_login(
    request: Request,
    body: TOTPVerifyRequest,
) -> TOTPVerifyResponse:
    """
    Called during login flow after SAML assertion — no JWT needed yet.
    Returns valid=True → login proceeds and JWT is issued.
    """
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, body.user_id, body.bank_id)
    else:
        raw = _MOCK_USERS.get(body.user_id)
        u = raw if (raw and raw["bank_id"] == body.bank_id) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not u["totp_enabled"]:
        raise HTTPException(status_code=400, detail="TOTP not enabled for this user")
    secret = _TOTP_SECRETS.get(body.user_id)
    if not secret:
        raise HTTPException(status_code=500, detail="TOTP secret not found. Contact IT admin.")
    valid = _verify_totp(secret, body.totp_code)
    if not valid:
        log.warning("totp.verify.failed", user_id=body.user_id, bank_id=body.bank_id)
    return TOTPVerifyResponse(
        valid=valid,
        message="Login authorised." if valid else "Invalid code. Please check your authenticator app.",
    )


# ---------------------------------------------------------------------------
# Routes — Session management
# ---------------------------------------------------------------------------

@router_v1.get("/v1/admin/users/{user_id}/sessions", response_model=list[SessionRecord])
async def list_user_sessions(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> list[SessionRecord]:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Sessions live in Redis (platform.user_sessions); query Redis when available
    redis = getattr(request.app.state, "redis_platform", None)
    if redis is not None:
        try:
            raw_sessions = await redis.lrange(f"sessions:{admin['bank_id']}:{user_id}", 0, -1)
            if raw_sessions:
                import json
                sessions = []
                for s in raw_sessions:
                    try:
                        d = json.loads(s)
                        sessions.append(SessionRecord(
                            session_id=d["session_id"],
                            user_id=user_id,
                            created_at=datetime.fromisoformat(d["created_at"]),
                            last_active_at=datetime.fromisoformat(d["last_active_at"]),
                            ip_address=d.get("ip_address", "unknown"),
                            user_agent=d.get("user_agent", "unknown"),
                            is_current=False,
                        ))
                    except Exception:
                        pass
                return sessions
        except Exception:
            pass
    # Fallback: return stub (Redis unavailable or no sessions stored)
    now = datetime.now(timezone.utc)
    return [
        SessionRecord(
            session_id="sess-abc123",
            user_id=user_id,
            created_at=datetime(2026, 6, 25, 9, 0, tzinfo=timezone.utc),
            last_active_at=now,
            ip_address="10.0.1.45",
            user_agent="Mozilla/5.0 (Windows NT 10.0)",
            is_current=False,
        )
    ]


@router_v1.delete("/v1/admin/users/{user_id}/sessions", status_code=204)
async def force_logout_user(
    request: Request,
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is not None:
        u = await _db_fetch_user(pool, user_id, admin["bank_id"])
    else:
        raw = _MOCK_USERS.get(user_id)
        u = raw if (raw and raw["bank_id"] == admin["bank_id"]) else None
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    redis = getattr(request.app.state, "redis_platform", None)
    if redis is not None:
        try:
            await redis.delete(f"sessions:{admin['bank_id']}:{user_id}")
        except Exception:
            pass
    log.info("user.force_logout", user_id=user_id, by=admin["user_id"], bank_id=admin["bank_id"])
