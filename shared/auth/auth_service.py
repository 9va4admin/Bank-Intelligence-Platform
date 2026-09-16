"""AuthService — the local login -> MFA -> session state machine.

Business logic lives here (per api.md: routers stay thin). The router owns HTTP
cookies + CSRF; this owns the security-critical decisions.

Mandatory MFA, no backup codes:
  password OK, enrolled     -> MFA_REQUIRED           -> verify_mfa       -> full session
  password OK, not enrolled -> MFA_ENROLLMENT_REQUIRED -> begin+confirm    -> full session
A password alone NEVER produces a full session: the interim session is always
issued with mfa_authenticated=False. Only verify_mfa / confirm_enrollment mint a
session with mfa_authenticated=True.

bank_type/permission_level are derived fail-closed: bank_type follows entity_type
deterministically; an absent permission_level becomes READ_ONLY (least privilege),
never EDIT/ADMIN — this is the ASTRA-04 fail-closed rule applied at issuance.
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional, Protocol

import structlog
from pydantic import BaseModel, ConfigDict

from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.connectors.local import LocalCredentials
from shared.auth.exceptions import AuthenticationError, InvalidSessionError
from shared.auth.mfa import EnrollmentChallenge, TOTPMFAService
from shared.auth.session_token import IssuedSession, SessionClaims, SessionTokenService

log = structlog.get_logger()


class LoginOutcome(str, Enum):
    MFA_REQUIRED = "MFA_REQUIRED"                        # enrolled — supply a TOTP code
    MFA_ENROLLMENT_REQUIRED = "MFA_ENROLLMENT_REQUIRED"  # first login — enrol then confirm


class LoginResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    outcome: LoginOutcome
    interim_session: IssuedSession   # always mfa_authenticated=False


class AccountEnrollmentStore(Protocol):
    """Reads/writes the totp_enrolled flag on platform.local_auth_accounts."""

    async def is_totp_enrolled(self, user_id: str) -> bool: ...
    async def set_totp_enrolled(self, user_id: str, enrolled: bool) -> None: ...


def _derive_bank_type(identity: ASTRAIdentity) -> str:
    if identity.bank_type in ("SB", "SMB"):
        return identity.bank_type
    # entity_type is a required Literal — deterministic, not a fail-open guess
    return "SMB" if identity.entity_type == "smb" else "SB"


def _derive_permission_level(identity: ASTRAIdentity) -> str:
    if identity.permission_level in ("ADMIN", "EDIT", "READ_ONLY"):
        return identity.permission_level
    return "READ_ONLY"  # fail closed — never default to a write-capable level


class AuthService:
    def __init__(
        self,
        mfa: TOTPMFAService,
        session_service: SessionTokenService,
        account_store: AccountEnrollmentStore,
        connector=None,            # single AuthConnector — backward-compat / tests
        connector_factory=None,    # AuthConnectorFactory — production path
        db_pool=None,              # asyncpg Pool — optional; absent → no DB writes (test mode)
    ) -> None:
        if connector is None and connector_factory is None:
            raise ValueError("either connector or connector_factory must be provided")
        self._connector = connector
        self._connector_factory = connector_factory
        self._mfa = mfa
        self._session = session_service
        self._accounts = account_store
        self._db = db_pool

    # -- DB persistence helpers --------------------------------------------- #

    async def _persist_session(self, session: IssuedSession, user_agent: str = "", ip_hash: str = "") -> None:
        """INSERT full session into platform.user_sessions. Fire-and-forget on error."""
        if self._db is None:
            return
        try:
            expires_at = datetime.datetime.fromtimestamp(session.expires_at, tz=datetime.timezone.utc)
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO platform.user_sessions
                        (session_id, user_id, bank_id, expires_at, user_agent, ip_hash)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    session.session_id,
                    session.claims.user_id,
                    session.claims.bank_id,
                    expires_at,
                    user_agent or None,
                    ip_hash or None,
                )
        except Exception:
            log.warning("auth.session.persist_failed", session_id=session.session_id)

    async def _log_event(
        self,
        *,
        bank_id: str,
        bank_type: str,
        user_id: str,
        event_type: str,
        session_id: Optional[str] = None,
        ip_hash: Optional[str] = None,
        user_agent: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        """INSERT a row into platform.login_events. Fire-and-forget on error."""
        if self._db is None:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO platform.login_events
                        (bank_id, bank_type, user_id, event_type, ip_hash,
                         user_agent, session_id, failure_reason)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    bank_id, bank_type, user_id, event_type,
                    ip_hash, user_agent, session_id, failure_reason,
                )
        except Exception:
            log.warning("auth.login_event.persist_failed", event_type=event_type, user_id=user_id)

    # -- stage 1: password -------------------------------------------------- #

    async def login(
        self,
        username: str,
        password: str,
        bank_id: str = "",
        entity_type: str = "sb",
        entity_id: Optional[str] = None,
    ) -> LoginResult:
        """Verify password, then issue a half-session and say what MFA step is next.

        Raises AuthenticationError / AccountLockedError from the connector on
        failure — the caller returns 401 with a uniform message.
        """
        if self._connector_factory is not None:
            connector = self._connector_factory.get_connector(
                entity_type, entity_id if entity_id is not None else bank_id
            )
        else:
            connector = self._connector

        try:
            identity: ASTRAIdentity = await connector.authenticate(
                LocalCredentials(username=username, password=password, bank_id=bank_id)
            )
        except AuthenticationError:
            await self._log_event(
                bank_id=bank_id, bank_type="SB", user_id=username,
                event_type="LOGIN_FAILED", failure_reason="INVALID_CREDENTIALS",
            )
            raise
        enrolled = await self._accounts.is_totp_enrolled(identity.user_id)
        interim = self._issue_from_identity(identity, mfa_authenticated=False)
        outcome = (
            LoginOutcome.MFA_REQUIRED if enrolled else LoginOutcome.MFA_ENROLLMENT_REQUIRED
        )
        log.info(
            "auth.login.password_ok",
            user_id=identity.user_id, bank_id=identity.bank_id, outcome=outcome.value,
        )
        return LoginResult(outcome=outcome, interim_session=interim)

    # -- stage 2a: verify (already enrolled) -------------------------------- #

    async def verify_mfa(self, interim: SessionClaims, code: str) -> IssuedSession:
        self._require_half_session(interim)
        ok = await self._mfa.verify(interim.user_id, code)
        if not ok:
            log.warning("auth.mfa.verify_failed", user_id=interim.user_id)
            await self._log_event(
                bank_id=interim.bank_id, bank_type=interim.bank_type,
                user_id=interim.user_id, event_type="TOTP_FAILED",
                failure_reason="TOTP_MISMATCH",
            )
            raise AuthenticationError("invalid MFA code")
        log.info("auth.mfa.verified", user_id=interim.user_id)
        session = self._issue_from_claims(interim, mfa_authenticated=True)
        await self._persist_session(session)
        await self._log_event(
            bank_id=interim.bank_id, bank_type=interim.bank_type,
            user_id=interim.user_id, event_type="LOGIN_SUCCESS",
            session_id=session.session_id,
        )
        return session

    # -- stage 2b: enrol then confirm (first login) ------------------------- #

    async def begin_enrollment(self, interim: SessionClaims) -> EnrollmentChallenge:
        self._require_half_session(interim)
        return await self._mfa.begin_enrollment(interim.user_id, interim.username)

    async def confirm_enrollment(self, interim: SessionClaims, code: str) -> IssuedSession:
        self._require_half_session(interim)
        ok = await self._mfa.confirm_enrollment(interim.user_id, code)
        if not ok:
            log.warning("auth.mfa.enroll_failed", user_id=interim.user_id)
            await self._log_event(
                bank_id=interim.bank_id, bank_type=interim.bank_type,
                user_id=interim.user_id, event_type="TOTP_FAILED",
                failure_reason="TOTP_MISMATCH",
            )
            raise AuthenticationError("invalid enrolment code")
        await self._accounts.set_totp_enrolled(interim.user_id, True)
        log.info("auth.mfa.enrolled", user_id=interim.user_id)
        session = self._issue_from_claims(interim, mfa_authenticated=True)
        await self._persist_session(session)
        await self._log_event(
            bank_id=interim.bank_id, bank_type=interim.bank_type,
            user_id=interim.user_id, event_type="LOGIN_SUCCESS",
            session_id=session.session_id,
        )
        return session

    # -- refresh (full session -> full session, sliding expiry) ------------- #

    async def refresh(self, claims: SessionClaims) -> IssuedSession:
        if not claims.mfa_authenticated:
            raise InvalidSessionError("cannot refresh a pre-MFA session")
        return self._issue_from_claims(claims, mfa_authenticated=True)

    # -- internals ---------------------------------------------------------- #

    @staticmethod
    def _require_half_session(claims: SessionClaims) -> None:
        if claims.mfa_authenticated:
            raise InvalidSessionError("session is already MFA-authenticated")

    def _issue_from_identity(self, identity: ASTRAIdentity, *, mfa_authenticated: bool) -> IssuedSession:
        return self._session.issue(
            user_id=identity.user_id,
            username=identity.username,
            bank_id=identity.bank_id,
            bank_type=_derive_bank_type(identity),
            permission_level=_derive_permission_level(identity),
            role=identity.role,
            entity_type=identity.entity_type,
            entity_id=identity.entity_id,
            clearing_zones=identity.clearing_zones,
            mfa_authenticated=mfa_authenticated,
        )

    def _issue_from_claims(self, c: SessionClaims, *, mfa_authenticated: bool) -> IssuedSession:
        return self._session.issue(
            user_id=c.user_id,
            username=c.username,
            bank_id=c.bank_id,
            bank_type=c.bank_type,
            permission_level=c.permission_level,
            role=c.role,
            entity_type=c.entity_type,
            entity_id=c.entity_id,
            clearing_zones=c.clearing_zones,
            mfa_authenticated=mfa_authenticated,
        )
