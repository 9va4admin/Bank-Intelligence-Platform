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

No passwords stored — SAML handles authentication.
TOTP is second factor on top of SAML (step-up auth).
TOTP secrets stored in Vault, never in YugabyteDB.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
# Mock data store (replace with YugabyteDB in production)
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
# Routes — User CRUD
# ---------------------------------------------------------------------------

@router_v1.get("/v1/admin/users", response_model=UserListResponse)
async def list_users(
    role_filter: Optional[str] = Query(None),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(require_it_admin),
) -> UserListResponse:
    users = list(_MOCK_USERS.values())
    if active_only:
        users = [u for u in users if u["is_active"]]
    if role_filter:
        users = [u for u in users if u["role"] == role_filter]
    # Paginate
    total = len(users)
    start = (page - 1) * limit
    page_users = users[start:start + limit]
    return UserListResponse(
        bank_id=admin["bank_id"],
        users=[_to_response(u) for u in page_users],
        total=total,
        page=page,
        limit=limit,
    )


@router_v1.post("/v1/admin/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreateRequest,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    if body.bank_type not in _VALID_BANK_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid bank_type. Must be SB or SMB.")
    if body.permission_level not in _VALID_PERMISSION_LEVELS:
        raise HTTPException(status_code=422, detail=f"Invalid permission_level. Must be ADMIN, EDIT, or READ_ONLY.")
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {sorted(_VALID_ROLES)}")
    # Enforce role↔bank_type compatibility
    if body.bank_type == "SB" and body.role in _SMB_ROLES:
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SMB users (bank_type=SMB).")
    if body.bank_type == "SMB" and body.role in _SB_ROLES:
        raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SB users (bank_type=SB).")
    if body.clearing_zone not in _VALID_ZONES:
        raise HTTPException(status_code=422, detail=f"Invalid zone. Must be one of: {sorted(_VALID_ZONES)}")
    if any(u["email"] == body.email for u in _MOCK_USERS.values()):
        raise HTTPException(status_code=409, detail="User with this email already exists")
    import uuid
    user_id = f"usr-{str(uuid.uuid4())[:8]}"
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
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    _MOCK_USERS[user_id] = new_user
    log.info("user.created", user_id=user_id, role=body.role, bank_type=body.bank_type, bank_id=admin["bank_id"])
    return _to_response(new_user)


@router_v1.get("/v1/admin/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_response(u)


@router_v1.put("/v1/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    admin: dict = Depends(require_it_admin),
) -> UserResponse:
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    # bank_type field absent from UserUpdateRequest — detect if caller sent it as extra JSON key
    # (FastAPI ignores extra fields by default, but we surface a clear error if somehow present)
    if body.permission_level is not None:
        if body.permission_level not in _VALID_PERMISSION_LEVELS:
            raise HTTPException(status_code=422, detail="Invalid permission_level. Must be ADMIN, EDIT, or READ_ONLY.")
        u["permission_level"] = body.permission_level
    if body.role is not None:
        if body.role not in _VALID_ROLES:
            raise HTTPException(status_code=422, detail="Invalid role")
        # Maintain role↔bank_type compatibility on update too
        if u["bank_type"] == "SB" and body.role in _SMB_ROLES:
            raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SMB users.")
        if u["bank_type"] == "SMB" and body.role in _SB_ROLES:
            raise HTTPException(status_code=422, detail=f"Role '{body.role}' is only valid for SB users.")
        u["role"] = body.role
    if body.clearing_zone is not None:
        if body.clearing_zone not in _VALID_ZONES:
            raise HTTPException(status_code=422, detail="Invalid zone")
        u["clearing_zone"] = body.clearing_zone
    if body.is_active is not None:
        u["is_active"] = body.is_active
    if body.display_name is not None:
        u["display_name"] = body.display_name
    log.info("user.updated", user_id=user_id, bank_id=admin["bank_id"])
    return _to_response(u)


@router_v1.delete("/v1/admin/users/{user_id}", status_code=204)
async def deactivate_user(
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    u["is_active"] = False
    log.info("user.deactivated", user_id=user_id, bank_id=admin["bank_id"])


# ---------------------------------------------------------------------------
# Routes — TOTP
# ---------------------------------------------------------------------------

@router_v1.post("/v1/admin/users/{user_id}/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> TOTPSetupResponse:
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    secret = _generate_totp_secret()
    # Store in Vault (here stored in mock dict — Vault in production)
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
    user_id: str,
    body: TOTPVerifyRequest,
    admin: dict = Depends(require_it_admin),
) -> TOTPVerifyResponse:
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    secret = _TOTP_SECRETS.get(user_id)
    if not secret:
        raise HTTPException(status_code=400, detail="TOTP setup not initiated. Call /totp/setup first.")
    if not _verify_totp(secret, body.totp_code):
        return TOTPVerifyResponse(valid=False, message="Invalid code. Please try again.")
    u["totp_enabled"] = True
    log.info("totp.activated", user_id=user_id, bank_id=admin["bank_id"])
    return TOTPVerifyResponse(valid=True, message="TOTP activated. MFA is now required at login.")


@router_v1.delete("/v1/admin/users/{user_id}/totp", status_code=204)
async def totp_reset(
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    u["totp_enabled"] = False
    _TOTP_SECRETS.pop(user_id, None)
    log.info("totp.reset", user_id=user_id, bank_id=admin["bank_id"])


@router_v1.post("/v1/auth/totp/verify", response_model=TOTPVerifyResponse)
async def totp_verify_login(
    body: TOTPVerifyRequest,
) -> TOTPVerifyResponse:
    """
    Called during login flow after SAML assertion — no JWT needed yet.
    Returns valid=True → login proceeds and JWT is issued.
    """
    u = _MOCK_USERS.get(body.user_id)
    if not u or u["bank_id"] != body.bank_id:
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
    user_id: str,
    admin: dict = Depends(require_it_admin),
) -> list[SessionRecord]:
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    # In production: query Redis session store for active sessions
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
    user_id: str,
    admin: dict = Depends(require_it_admin),
):
    u = _MOCK_USERS.get(user_id)
    if not u or u["bank_id"] != admin["bank_id"]:
        raise HTTPException(status_code=404, detail="User not found")
    # In production: delete all Redis session keys for this user
    log.info("user.force_logout", user_id=user_id, by=admin["user_id"], bank_id=admin["bank_id"])
