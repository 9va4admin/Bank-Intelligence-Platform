"""LDAPADConnector — LDAPS bind against Active Directory + AD group → ASTRA role mapping."""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, field_validator

from shared.auth.connectors.base import ASTRAIdentity, AuthConnector
from shared.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    LDAPServerUnreachableError,
)

log = structlog.get_logger()


class LDAPCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)
    username: str
    password: str


class LDAPADConnectorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_url: str
    base_dn: str
    user_search_base: str
    group_search_base: str
    bind_dn_secret: str     # Vault path for service-account DN
    bind_pw_secret: str     # Vault path for service-account password
    group_role_map: dict[str, str] = {}  # AD group DN → ASTRA role name

    @field_validator("server_url")
    @classmethod
    def require_ldaps(cls, v: str) -> str:
        if not v.startswith("ldaps://"):
            raise ValueError("LDAPS required — use ldaps:// (port 636). Plain ldap:// rejected.")
        return v


class LDAPADConnector(AuthConnector):
    """Authenticates users via LDAPS bind against Microsoft Active Directory.

    Auth flow:
      1. Service-account bind (DN + password from Vault) to verify connectivity.
      2. Search for user by sAMAccountName under user_search_base.
      3. Re-bind as the found user DN with the supplied password (validates credentials).
      4. Fetch memberOf attribute and map first matching AD group to ASTRA role.
      5. Return ASTRAIdentity.

    LDAPS (port 636) is mandatory — plain LDAP rejected at config validation.
    """

    def __init__(
        self,
        config: LDAPADConnectorConfig,
        entity_type: str,
        entity_id: str,
        bank_id: str,
        clearing_zones: Optional[list[str]] = None,
    ) -> None:
        self.config = config
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.bank_id = bank_id
        self.clearing_zones = clearing_zones or []

    @property
    def connector_type(self) -> str:
        return "ldap_ad"

    async def authenticate(self, credentials: LDAPCredentials) -> ASTRAIdentity:
        import ldap3
        import ldap3.core.exceptions as ldap_exc

        try:
            entry = await self._ldap_bind_and_search(credentials.username, credentials.password)
        except ldap_exc.LDAPBindError as exc:
            log.warn("auth.ldap.bind_failed", bank_id=self.bank_id, username=credentials.username)
            raise AuthenticationError("invalid credentials") from exc
        except ldap_exc.LDAPSocketOpenError as exc:
            log.error("auth.ldap.server_unreachable", bank_id=self.bank_id, server=self.config.server_url)
            raise LDAPServerUnreachableError(str(exc)) from exc

        if entry is None:
            raise AuthenticationError(f"user '{credentials.username}' not found in directory")

        # Map AD groups to ASTRA role
        member_of: list[str] = getattr(entry.memberOf, "values", []) or []
        role: Optional[str] = None
        for group_dn in member_of:
            if group_dn in self.config.group_role_map:
                role = self.config.group_role_map[group_dn]
                break

        if role is None:
            log.warn("auth.ldap.no_role_mapping", bank_id=self.bank_id, username=credentials.username, groups=member_of)
            raise AuthorizationError(
                f"user '{credentials.username}' authenticated but has no ASTRA role mapping. "
                f"Add their AD group to group_role_map."
            )

        display_name: str = getattr(entry.displayName, "value", credentials.username) or credentials.username
        mail: str = getattr(entry.mail, "value", "") or ""

        log.info("auth.ldap.success", bank_id=self.bank_id, username=credentials.username, role=role)
        return ASTRAIdentity(
            user_id=f"ldap:{self.bank_id}:{credentials.username}",
            username=credentials.username,
            display_name=display_name,
            entity_type=self.entity_type,  # type: ignore[arg-type]
            entity_id=self.entity_id,
            bank_id=self.bank_id,
            role=role,
            clearing_zones=self.clearing_zones,
            connector_used="ldap_ad",
        )

    async def health_check(self) -> bool:
        try:
            return await self._test_connection()
        except Exception:
            return False

    # --- Hooks replaced by AsyncMock in tests ---

    async def _ldap_bind_and_search(self, username: str, password: str):
        """Bind as service account, search for user, re-bind as user. Returns ldap3 entry or None."""
        raise NotImplementedError("inject mock in tests or wire real ldap3 connection pool")

    async def _test_connection(self) -> bool:
        """Attempt service-account bind; return True if successful."""
        raise NotImplementedError
