"""ASTRA DEV-ONLY auth server — run local login + TOTP MFA with no Vault/DB/Redis.

Generates an ephemeral RS256 keypair in-process and seeds THREE accounts (real
argon2 hashes). Serves the real /v1/auth/* router; the frontend reaches it via the
Vite proxy (/v1 -> http://127.0.0.1:8010).

Real MFA flow — no shortcuts: the FIRST sign-in for each user triggers enrolment
(scan the QR into an authenticator app), and every sign-in after that requires the
current 6-digit TOTP code from that app.

    uvicorn apps.api.dev_auth_server:app --port 8010

NEVER use in production: keys are ephemeral (restart = sessions dropped + re-enrol)
and accounts are seeded. Production wires SessionTokenService keys from Vault and
the real connectors + account store.
"""
from __future__ import annotations

import structlog
from argon2 import PasswordHasher
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import auth as auth_router
from shared.auth.auth_service import AuthService
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.connectors.local import LocalCredentials
from shared.auth.exceptions import AuthenticationError
from shared.auth.mfa import TOTPMFAService
from shared.auth.session_token import SessionTokenService

log = structlog.get_logger()

# username -> account. Users enrol TOTP on first sign-in (scan QR), then supply a
# code every time. Enrolment lives in memory, so a backend restart means re-enrol.
SEED_ACCOUNTS: dict[str, dict] = {
    "admin": {
        "user_id": "usr-admin", "password": "astra-dev-admin",
        "display_name": "Anita Rao", "role": "bank_it_admin",
        "bank_type": "SB", "permission_level": "ADMIN",
        "entity_type": "sb", "entity_id": "saraswat-coop", "bank_id": "saraswat-coop",
        "clearing_zones": ["ALL"],
    },
    "ops": {
        "user_id": "usr-ops", "password": "astra-dev-ops",
        "display_name": "Sunil Mehta", "role": "ops_manager",
        "bank_type": "SB", "permission_level": "EDIT",
        "entity_type": "sb", "entity_id": "saraswat-coop", "bank_id": "saraswat-coop",
        "clearing_zones": ["ALL"],
    },
    "smb": {
        "user_id": "usr-smb", "password": "astra-dev-smb",
        "display_name": "Vasavi Admin", "role": "smb_admin",
        "bank_type": "SMB", "permission_level": "ADMIN",
        "entity_type": "smb", "entity_id": "smb-mh-vasavi", "bank_id": "smb-mh-vasavi",
        "clearing_zones": ["MUMBAI"],
    },
}

_PH = PasswordHasher()
for _acct in SEED_ACCOUNTS.values():
    _acct["password_hash"] = _PH.hash(_acct["password"])


def _gen_keys() -> tuple[str, str]:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


class _MemMfaStore:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def put(self, uid: str, secret: str) -> None:
        self._d[uid] = secret

    async def get(self, uid: str):
        return self._d.get(uid)

    async def delete(self, uid: str) -> None:
        self._d.pop(uid, None)


class _MemAccounts:
    def __init__(self) -> None:
        self._enrolled: set[str] = set()

    async def is_totp_enrolled(self, uid: str) -> bool:
        return uid in self._enrolled

    async def set_totp_enrolled(self, uid: str, val: bool) -> None:
        self._enrolled.add(uid) if val else self._enrolled.discard(uid)


class _DevConnector:
    """Verifies any of the seeded accounts against its real argon2 hash."""

    @property
    def connector_type(self) -> str:
        return "local"

    async def authenticate(self, credentials: LocalCredentials) -> ASTRAIdentity:
        acct = SEED_ACCOUNTS.get(credentials.username)
        if acct is None:
            raise AuthenticationError("invalid credentials")
        try:
            _PH.verify(acct["password_hash"], credentials.password)
        except Exception:
            raise AuthenticationError("invalid credentials")
        return ASTRAIdentity(
            user_id=acct["user_id"], username=credentials.username,
            display_name=acct["display_name"], entity_type=acct["entity_type"],
            entity_id=acct["entity_id"], bank_id=acct["bank_id"], role=acct["role"],
            clearing_zones=acct["clearing_zones"], connector_used="local",
            bank_type=acct["bank_type"], permission_level=acct["permission_level"],
        )

    async def health_check(self) -> bool:
        return True


def build_app() -> FastAPI:
    priv, pub = _gen_keys()
    session_service = SessionTokenService(priv, pub, issuer="astra-auth", ttl_seconds=900)
    mfa = TOTPMFAService(_MemMfaStore(), issuer="ASTRA")
    accounts = _MemAccounts()
    svc = AuthService(
        connector=_DevConnector(), mfa=mfa,
        session_service=session_service, account_store=accounts,
    )

    app = FastAPI(title="ASTRA Dev Auth (local only)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4000", "http://localhost:5173"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    app.state.session_service = session_service
    app.state.auth_service = svc
    app.include_router(auth_router.router_v1)

    @app.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "ok"}

    _banner()
    return app


def _banner() -> None:
    line = "=" * 68
    rows = "\n".join(
        f"    {u:<7} / {a['password']:<16}  ->  {a['role']} ({a['bank_type']})"
        for u, a in SEED_ACCOUNTS.items()
    )
    print(
        f"\n{line}\n"
        f"  ASTRA DEV AUTH  |  http://localhost:8010  |  NEVER use in production\n"
        f"{line}\n"
        f"  username / password:\n{rows}\n\n"
        f"  First sign-in = scan the QR with an authenticator app (Google\n"
        f"  Authenticator / Authy), then enter the 6-digit code. Every sign-in\n"
        f"  after that asks for the current code from your app.\n"
        f"{line}\n"
    )


app = build_app()
