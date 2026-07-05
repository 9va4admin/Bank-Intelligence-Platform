"""SAMLConnector — wraps SAML 2.0 IdP flow; ASTRA never sees the user's password."""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.auth.connectors.base import ASTRAIdentity, AuthConnector
from shared.auth.exceptions import AuthenticationError, AuthorizationError

log = structlog.get_logger()


class SAMLCredentials(BaseModel):
    """Carries the SAML assertion received from the IdP at the ACS endpoint."""

    model_config = ConfigDict(frozen=True)

    saml_response: str          # base64-encoded SAMLResponse POST parameter
    relay_state: Optional[str] = None


class SAMLConnectorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    idp_metadata_url_secret: str    # Vault path — URL to IdP metadata XML (ADFS federation metadata)
    sp_entity_id: str               # This SP's EntityID registered with IdP
    acs_url: str                    # Assertion Consumer Service URL (HTTPS, internal)
    role_attribute: str = "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups"
    group_role_map: dict[str, str] = {}   # SAML group claim value → ASTRA role name
    name_id_attribute: str = "NameID"    # attribute carrying the username


class SAMLConnector(AuthConnector):
    """Processes SAML 2.0 assertions from bank's IdP (e.g. ADFS, Azure AD, Okta).

    ASTRA never sees the user's password — IdP authenticates, ASTRA receives assertion.

    Auth flow:
      1. Browser redirects to IdP login (ASTRA generates AuthnRequest).
      2. IdP authenticates user, posts SAMLResponse to ACS URL.
      3. SAMLConnector validates assertion signature, checks NotBefore/NotOnOrAfter.
      4. Extracts NameID (username) and group claims.
      5. Maps first matching group claim to ASTRA role.
      6. Returns ASTRAIdentity.
    """

    def __init__(
        self,
        config: SAMLConnectorConfig,
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
        return "saml"

    async def authenticate(self, credentials: SAMLCredentials) -> ASTRAIdentity:
        attributes = await self._parse_and_validate_assertion(credentials.saml_response)

        username: str = attributes.get(self.config.name_id_attribute, "")
        if not username:
            raise AuthenticationError("SAML assertion missing NameID")

        groups: list[str] = attributes.get(self.config.role_attribute, [])
        if isinstance(groups, str):
            groups = [groups]

        role: Optional[str] = None
        for group in groups:
            if group in self.config.group_role_map:
                role = self.config.group_role_map[group]
                break

        if role is None:
            log.warn("auth.saml.no_role_mapping", bank_id=self.bank_id, username=username, groups=groups)
            raise AuthorizationError(
                f"user '{username}' authenticated via SAML but has no ASTRA role mapping. "
                f"Add their IdP group to group_role_map."
            )

        display_name: str = attributes.get(
            "http://schemas.microsoft.com/identity/claims/displayname", username
        )

        log.info("auth.saml.success", bank_id=self.bank_id, username=username, role=role)
        return ASTRAIdentity(
            user_id=f"saml:{self.bank_id}:{username}",
            username=username,
            display_name=display_name,
            entity_type=self.entity_type,  # type: ignore[arg-type]
            entity_id=self.entity_id,
            bank_id=self.bank_id,
            role=role,
            clearing_zones=self.clearing_zones,
            connector_used="saml",
        )

    async def health_check(self) -> bool:
        # SAML is stateless — check if IdP metadata URL is reachable
        try:
            return await self._ping_idp_metadata()
        except Exception:
            return False

    # --- Hooks ---

    async def _parse_and_validate_assertion(self, saml_response: str) -> dict[str, Any]:
        """Validate signature, timestamps, audience. Return attribute dict."""
        raise NotImplementedError("wire real python3-saml or pysaml2 library")

    async def _ping_idp_metadata(self) -> bool:
        """Fetch IdP metadata URL; return True if 200."""
        raise NotImplementedError
