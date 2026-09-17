"""AuthConnectorFactory — resolves the correct connector for each entity level."""
from __future__ import annotations

from typing import Any

import structlog

from shared.auth.connectors.base import AuthConnector
from shared.auth.exceptions import AuthConnectorConfigError

log = structlog.get_logger()

_VALID_ENTITY_TYPES = {"sb", "smb", "branch", "pu"}


class AuthConnectorFactory:
    """Returns the configured AuthConnector for a given entity_type + entity_id.

    Connector instances are cached per (entity_type, entity_id) — one instance
    per entity for the lifetime of the factory (typically one factory per bank,
    held in app.state).

    Config is read from config_service keyed at 'auth' (Layer 2 Helm values).
    """

    def __init__(self, bank_id: str, config_service: Any, db_pool: Any = None) -> None:
        self.bank_id = bank_id
        self._config_service = config_service
        self._db_pool = db_pool
        self._cache: dict[tuple[str, str], AuthConnector] = {}

    def get_connector(self, entity_type: str, entity_id: str) -> AuthConnector:
        if entity_type not in _VALID_ENTITY_TYPES:
            raise AuthConnectorConfigError(
                f"unknown entity_type '{entity_type}'. Valid: {sorted(_VALID_ENTITY_TYPES)}"
            )

        cache_key = (entity_type, entity_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        connector = self._build_connector(entity_type, entity_id)
        self._cache[cache_key] = connector
        return connector

    def _build_connector(self, entity_type: str, entity_id: str) -> AuthConnector:
        # config_service.get() is async; in dev/POC, Layer 2 Helm values are not wired
        # so the auth config is unavailable — fall back to local auth directly.
        raw_auth_config = getattr(self._config_service, "_auth_config_cache", None)
        if raw_auth_config is None:
            log.info(
                "auth.factory.no_auth_config_fallback_to_local",
                bank_id=self.bank_id, entity_type=entity_type,
                note="No sync auth config available; defaulting to local DB auth",
            )
            return self._build_local(entity_type, entity_id)

        full_config = raw_auth_config
        if not full_config or "auth" not in full_config:
            return self._build_local(entity_type, entity_id)

        auth_root: dict = full_config["auth"]

        if entity_type == "smb":
            entity_cfg = self._resolve_smb_config(auth_root, entity_id)
        else:
            entity_cfg = auth_root.get(entity_type, {})

        if not entity_cfg:
            return self._build_local(entity_type, entity_id)

        integration_enabled: bool = entity_cfg.get("integration_enabled", False)
        integration_type: str = entity_cfg.get("integration_type", "local")
        clearing_zones: list[str] = entity_cfg.get("clearing_zones", [])

        if not integration_enabled or integration_type == "local":
            return self._build_local(entity_type, entity_id)

        if integration_type == "saml":
            return self._build_saml(entity_type, entity_id, entity_cfg, clearing_zones)

        if integration_type == "ldap_ad":
            return self._build_ldap_ad(entity_type, entity_id, entity_cfg, clearing_zones)

        raise AuthConnectorConfigError(
            f"Unknown integration_type '{integration_type}' for entity_type='{entity_type}'."
        )

    def _resolve_smb_config(self, auth_root: dict, entity_id: str) -> dict:
        smb_root: dict = auth_root.get("smb", {})

        # If top-level smb config has no 'default' key, treat the whole block as the default
        if "default" not in smb_root:
            return smb_root

        # Check per-SMB overrides first
        overrides: dict = smb_root.get("overrides", {})
        if entity_id in overrides:
            return overrides[entity_id]

        return smb_root.get("default", {})

    def _build_local(self, entity_type: str, entity_id: str) -> AuthConnector:
        if self._db_pool is not None:
            from shared.auth.connectors.local import YugabyteDBLocalAuthConnector
            log.info("auth.factory.local_db", bank_id=self.bank_id, entity_type=entity_type, entity_id=entity_id)
            return YugabyteDBLocalAuthConnector(bank_id=self.bank_id, db_pool=self._db_pool)

        from shared.auth.connectors.local import LocalAuthConnector
        log.warning(
            "auth.factory.local_no_db_pool",
            bank_id=self.bank_id, entity_type=entity_type, entity_id=entity_id,
            reason="no db_pool injected — every login against this connector will raise NotImplementedError",
        )
        return LocalAuthConnector(bank_id=self.bank_id)

    def _build_saml(
        self,
        entity_type: str,
        entity_id: str,
        entity_cfg: dict,
        clearing_zones: list[str],
    ) -> AuthConnector:
        from shared.auth.connectors.saml import SAMLConnector, SAMLConnectorConfig
        saml_cfg_raw: dict = entity_cfg.get("saml", {})
        saml_config = SAMLConnectorConfig(
            idp_metadata_url_secret=saml_cfg_raw["idp_metadata_url_secret"],
            sp_entity_id=saml_cfg_raw["sp_entity_id"],
            acs_url=saml_cfg_raw["acs_url"],
            group_role_map=saml_cfg_raw.get("group_role_map", {}),
        )
        log.info("auth.factory.saml", bank_id=self.bank_id, entity_type=entity_type, entity_id=entity_id)
        return SAMLConnector(
            config=saml_config,
            entity_type=entity_type,
            entity_id=entity_id,
            bank_id=self.bank_id,
            clearing_zones=clearing_zones,
        )

    def _build_ldap_ad(
        self,
        entity_type: str,
        entity_id: str,
        entity_cfg: dict,
        clearing_zones: list[str],
    ) -> AuthConnector:
        from shared.auth.connectors.ldap_ad import LDAPADConnector, LDAPADConnectorConfig
        ldap_cfg_raw: dict = entity_cfg.get("ldap_ad", {})
        ldap_config = LDAPADConnectorConfig(
            server_url=ldap_cfg_raw["server_url"],
            base_dn=ldap_cfg_raw["base_dn"],
            user_search_base=ldap_cfg_raw["user_search_base"],
            group_search_base=ldap_cfg_raw["group_search_base"],
            bind_dn_secret=ldap_cfg_raw["bind_dn_secret"],
            bind_pw_secret=ldap_cfg_raw["bind_pw_secret"],
            group_role_map=ldap_cfg_raw.get("group_role_map", {}),
        )
        log.info("auth.factory.ldap_ad", bank_id=self.bank_id, entity_type=entity_type, entity_id=entity_id)
        return LDAPADConnector(
            config=ldap_config,
            entity_type=entity_type,
            entity_id=entity_id,
            bank_id=self.bank_id,
            clearing_zones=clearing_zones,
        )
