"""ASTRA DEV-ONLY auth server — run local login + TOTP MFA with no Vault/DB/Redis.

Generates an ephemeral RS256 keypair in-process and seeds ONE admin account
(real argon2 hash). Serves the real /v1/auth/* router so the frontend login flow
works end-to-end on a laptop. The frontend reaches it via the Vite proxy
(/v1 -> http://localhost:8000).

    uvicorn apps.api.dev_auth_server:app --port 8000

NEVER use in production: keys are ephemeral (sessions die on restart) and there is
a dev-only endpoint that reveals the current TOTP code so you can sign in without a
phone. Production wires SessionTokenService keys from Vault and the real connectors.
"""
from __future__ import annotations

import pyotp
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

SEED_USERNAME = "admin"
SEED_PASSWORD = "astra-dev-admin"   # dev only — printed at startup
SEED_USER_ID = "usr-admin"


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
    """Verifies the single seeded admin against a real argon2 hash."""

    def __init__(self) -> None:
        self._ph = PasswordHasher()
        self._hash = self._ph.hash(SEED_PASSWORD)

    @property
    def connector_type(self) -> str:
        return "local"

    async def authenticate(self, credentials: LocalCredentials) -> ASTRAIdentity:
        if credentials.username != SEED_USERNAME:
            raise AuthenticationError("invalid credentials")
        try:
            self._ph.verify(self._hash, credentials.password)
        except Exception:
            raise AuthenticationError("invalid credentials")
        return ASTRAIdentity(
            user_id=SEED_USER_ID,
            username=SEED_USERNAME,
            display_name="Dev Admin",
            entity_type="sb",
            entity_id="saraswat-coop",
            bank_id="saraswat-coop",
            role="bank_it_admin",
            clearing_zones=["ALL"],
            connector_used="local",
            bank_type="SB",
            permission_level="ADMIN",
        )

    async def health_check(self) -> bool:
        return True


def build_app() -> FastAPI:
    priv, pub = _gen_keys()
    session_service = SessionTokenService(priv, pub, issuer="astra-auth", ttl_seconds=900)
    mfa_store = _MemMfaStore()
    mfa = TOTPMFAService(mfa_store, issuer="ASTRA")
    accounts = _MemAccounts()
    svc = AuthService(
        connector=_DevConnector(),
        mfa=mfa,
        session_service=session_service,
        account_store=accounts,
    )

    app = FastAPI(title="ASTRA Dev Auth (local only)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.session_service = session_service
    app.state.auth_service = svc
    app.include_router(auth_router.router_v1)

    @app.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "ok"}

    @app.get("/v1/auth/dev/otp", include_in_schema=False)
    async def dev_otp():
        """DEV ONLY: current TOTP code for the seeded admin, so you can sign in
        without an authenticator app. The secret exists after the enrol QR shows."""
        secret = await mfa_store.get(SEED_USER_ID)
        if not secret:
            return {"detail": "No TOTP secret yet — start login, reach the setup screen, then refresh."}
        return {"code": pyotp.TOTP(secret).now(), "secret": secret}

    _banner()
    return app


def _banner() -> None:
    line = "=" * 66
    print(
        f"\n{line}\n"
        f"  ASTRA DEV AUTH  |  http://localhost:8000  |  NEVER use in production\n"
        f"{line}\n"
        f"  Username : {SEED_USERNAME}\n"
        f"  Password : {SEED_PASSWORD}\n"
        f"\n"
        f"  First sign-in triggers MFA enrolment. To get the 6-digit code without\n"
        f"  a phone, open (after the setup-key screen appears):\n"
        f"     http://localhost:4000/v1/auth/dev/otp\n"
        f"  or scan/enter the shown key into any authenticator app.\n"
        f"{line}\n"
    )


app = build_app()
