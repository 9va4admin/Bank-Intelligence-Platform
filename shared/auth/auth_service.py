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
        connector,                       # AuthConnector (LocalAuthConnector in prod)
        mfa: TOTPMFAService,
        session_service: SessionTokenService,
        account_store: AccountEnrollmentStore,
    ) -> None:
        self._connector = connector
        self._mfa = mfa
        self._session = session_service
        self._accounts = account_store

    # -- stage 1: password -------------------------------------------------- #

    async def login(self, username: str, password: str) -> LoginResult:
        """Verify password, then issue a half-session and say what MFA step is next.

        Raises AuthenticationError / AccountLockedError from the connector on
        failure — the caller returns 401 with a uniform message.
        """
        identity: ASTRAIdentity = await self._connector.authenticate(
            LocalCredentials(username=username, password=password)
        )
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
            raise AuthenticationError("invalid MFA code")
        log.info("auth.mfa.verified", user_id=interim.user_id)
        return self._issue_from_claims(interim, mfa_authenticated=True)

    # -- stage 2b: enrol then confirm (first login) ------------------------- #

    async def begin_enrollment(self, interim: SessionClaims) -> EnrollmentChallenge:
        self._require_half_session(interim)
        return await self._mfa.begin_enrollment(interim.user_id, interim.username)

    async def confirm_enrollment(self, interim: SessionClaims, code: str) -> IssuedSession:
        self._require_half_session(interim)
        ok = await self._mfa.confirm_enrollment(interim.user_id, code)
        if not ok:
            log.warning("auth.mfa.enroll_failed", user_id=interim.user_id)
            raise AuthenticationError("invalid enrolment code")
        await self._accounts.set_totp_enrolled(interim.user_id, True)
        log.info("auth.mfa.enrolled", user_id=interim.user_id)
        return self._issue_from_claims(interim, mfa_authenticated=True)

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
