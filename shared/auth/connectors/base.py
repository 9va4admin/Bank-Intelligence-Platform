"""Base classes for auth connectors — ASTRAIdentity + AuthConnector ABC."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ASTRAIdentity(BaseModel):
    """Uniform post-authentication identity issued by any connector."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    display_name: str
    entity_type: Literal["sb", "smb", "branch", "pu"]
    entity_id: str
    bank_id: str
    role: str
    clearing_zones: list[str] = []
    connector_used: Literal["saml", "ldap_ad", "local"]
    authenticated_at: float = 0.0

    def model_post_init(self, __context: Any) -> None:
        # Set authenticated_at to now if caller passed 0
        if self.authenticated_at == 0.0:
            object.__setattr__(self, "authenticated_at", time.time())


class AuthConnector(ABC):
    """Abstract base for all auth connectors."""

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """One of 'saml', 'ldap_ad', 'local'."""

    @abstractmethod
    async def authenticate(self, credentials: Any) -> ASTRAIdentity:
        """Verify credentials and return ASTRAIdentity on success.

        Raises:
            AuthenticationError: Wrong credentials or inactive account.
            AccountLockedError: Too many failed attempts.
            AuthorizationError: Authenticated but no ASTRA role mapping.
            LDAPServerUnreachableError: LDAP/AD server unreachable.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the upstream identity system is reachable."""
