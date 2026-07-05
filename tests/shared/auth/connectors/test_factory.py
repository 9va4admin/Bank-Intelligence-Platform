"""Tests for AuthConnectorFactory — entity-level routing to the correct connector."""
import pytest
from unittest.mock import MagicMock, patch
from shared.auth.connectors.factory import AuthConnectorFactory
from shared.auth.connectors.base import AuthConnector
from shared.auth.connectors.local import LocalAuthConnector
from shared.auth.connectors.ldap_ad import LDAPADConnector
from shared.auth.connectors.saml import SAMLConnector
from shared.auth.exceptions import AuthConnectorConfigError


SB_SAML_CONFIG = {
    "auth": {
        "sb": {
            "integration_enabled": True,
            "integration_type": "saml",
            "saml": {
                "idp_metadata_url_secret": "auth/saml/sb/idp_metadata_url",
                "sp_entity_id": "astra-sb-saraswat",
                "acs_url": "https://saraswat-coop.astra.internal/auth/saml/acs",
            },
        },
        "smb": {
            "integration_enabled": False,
            "integration_type": "local",
            "default": {
                "integration_enabled": False,
                "integration_type": "local",
            },
        },
        "branch": {
            "integration_enabled": True,
            "integration_type": "ldap_ad",
            "ldap_ad": {
                "server_url": "ldaps://dc.saraswat-coop.internal:636",
                "base_dn": "DC=saraswat-coop,DC=local",
                "user_search_base": "OU=Users,DC=saraswat-coop,DC=local",
                "group_search_base": "OU=Groups,DC=saraswat-coop,DC=local",
                "bind_dn_secret": "auth/ldap/bind_dn",
                "bind_pw_secret": "auth/ldap/bind_pw",
            },
            "clearing_zones": ["MUMBAI"],
        },
        "pu": {
            "integration_enabled": True,
            "integration_type": "ldap_ad",
            "ldap_ad": {
                "server_url": "ldaps://dc.saraswat-coop.internal:636",
                "base_dn": "DC=saraswat-coop,DC=local",
                "user_search_base": "OU=Users,DC=saraswat-coop,DC=local",
                "group_search_base": "OU=Groups,DC=saraswat-coop,DC=local",
                "bind_dn_secret": "auth/ldap/bind_dn",
                "bind_pw_secret": "auth/ldap/bind_pw",
            },
        },
    }
}

SMB_LDAP_OVERRIDE_CONFIG = {
    "auth": {
        "sb": {
            "integration_enabled": True,
            "integration_type": "saml",
            "saml": {
                "idp_metadata_url_secret": "auth/saml/sb/idp_metadata_url",
                "sp_entity_id": "astra-sb",
                "acs_url": "https://astra.internal/auth/saml/acs",
            },
        },
        "smb": {
            "default": {
                "integration_enabled": False,
                "integration_type": "local",
            },
            "overrides": {
                "pune-ucb": {
                    "integration_enabled": True,
                    "integration_type": "ldap_ad",
                    "ldap_ad": {
                        "server_url": "ldaps://dc.pune-ucb.local:636",
                        "base_dn": "DC=pune-ucb,DC=local",
                        "user_search_base": "OU=Users,DC=pune-ucb,DC=local",
                        "group_search_base": "OU=Groups,DC=pune-ucb,DC=local",
                        "bind_dn_secret": "auth/smb/pune-ucb/ldap/bind_dn",
                        "bind_pw_secret": "auth/smb/pune-ucb/ldap/bind_pw",
                    },
                }
            },
        },
        "branch": {"integration_enabled": False, "integration_type": "local"},
        "pu": {"integration_enabled": False, "integration_type": "local"},
    }
}


def _make_factory(config: dict, bank_id="saraswat-coop") -> AuthConnectorFactory:
    mock_config_service = MagicMock()
    mock_config_service.get.side_effect = lambda key: config
    return AuthConnectorFactory(bank_id=bank_id, config_service=mock_config_service)


def test_sb_gets_saml_connector():
    factory = _make_factory(SB_SAML_CONFIG)
    connector = factory.get_connector(entity_type="sb", entity_id="saraswat-coop")
    assert isinstance(connector, SAMLConnector)


def test_branch_gets_ldap_ad_connector():
    factory = _make_factory(SB_SAML_CONFIG)
    connector = factory.get_connector(entity_type="branch", entity_id="branch-dadar-001")
    assert isinstance(connector, LDAPADConnector)


def test_pu_gets_ldap_ad_connector():
    factory = _make_factory(SB_SAML_CONFIG)
    connector = factory.get_connector(entity_type="pu", entity_id="pu-mumbai-1")
    assert isinstance(connector, LDAPADConnector)


def test_smb_default_gets_local_connector():
    factory = _make_factory(SB_SAML_CONFIG)
    # No override for this SMB → falls back to default
    connector = factory.get_connector(entity_type="smb", entity_id="small-ucb-xyz")
    assert isinstance(connector, LocalAuthConnector)


def test_smb_override_gets_ldap_connector():
    factory = _make_factory(SMB_LDAP_OVERRIDE_CONFIG)
    # pune-ucb has a per-SMB override to ldap_ad
    connector = factory.get_connector(entity_type="smb", entity_id="pune-ucb")
    assert isinstance(connector, LDAPADConnector)


def test_smb_non_override_still_gets_default_local():
    factory = _make_factory(SMB_LDAP_OVERRIDE_CONFIG)
    # kolhapur-ucb has no override → local
    connector = factory.get_connector(entity_type="smb", entity_id="kolhapur-ucb")
    assert isinstance(connector, LocalAuthConnector)


def test_connector_is_cached_on_second_call():
    factory = _make_factory(SB_SAML_CONFIG)
    c1 = factory.get_connector(entity_type="sb", entity_id="saraswat-coop")
    c2 = factory.get_connector(entity_type="sb", entity_id="saraswat-coop")
    assert c1 is c2   # same object — cached


def test_invalid_entity_type_raises():
    factory = _make_factory(SB_SAML_CONFIG)
    with pytest.raises(AuthConnectorConfigError, match="unknown entity_type"):
        factory.get_connector(entity_type="rbi", entity_id="any")


def test_missing_auth_config_raises():
    factory = _make_factory({})   # empty config — no 'auth' key
    with pytest.raises(AuthConnectorConfigError, match="auth config missing"):
        factory.get_connector(entity_type="sb", entity_id="saraswat-coop")


def test_all_local_config_works():
    config = {
        "auth": {
            "sb": {"integration_enabled": False, "integration_type": "local"},
            "smb": {
                "default": {"integration_enabled": False, "integration_type": "local"},
            },
            "branch": {"integration_enabled": False, "integration_type": "local"},
            "pu": {"integration_enabled": False, "integration_type": "local"},
        }
    }
    factory = _make_factory(config)
    for entity_type in ("sb", "branch", "pu"):
        connector = factory.get_connector(entity_type=entity_type, entity_id="x")
        assert isinstance(connector, LocalAuthConnector), f"{entity_type} should be local"
    smb_connector = factory.get_connector(entity_type="smb", entity_id="any-smb")
    assert isinstance(smb_connector, LocalAuthConnector)
