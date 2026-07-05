"""Tests for ASTRAIdentity + AuthConnector ABC."""
import time
import pytest
from pydantic import ValidationError
from shared.auth.connectors.base import ASTRAIdentity


def test_astra_identity_valid():
    identity = ASTRAIdentity(
        user_id="u-001",
        username="ravi.mehta",
        display_name="Ravi Mehta",
        entity_type="sb",
        entity_id="saraswat-coop",
        bank_id="saraswat-coop",
        role="ops_reviewer",
        clearing_zones=["MUMBAI"],
        connector_used="ldap_ad",
        authenticated_at=time.time(),
    )
    assert identity.entity_type == "sb"
    assert identity.connector_used == "ldap_ad"


def test_astra_identity_invalid_entity_type():
    with pytest.raises(ValidationError):
        ASTRAIdentity(
            user_id="u-001",
            username="x",
            display_name="X",
            entity_type="rbi",          # invalid — not sb/smb/branch/pu
            entity_id="test",
            bank_id="test",
            role="ops_reviewer",
            connector_used="local",
            authenticated_at=time.time(),
        )


def test_astra_identity_invalid_connector_used():
    with pytest.raises(ValidationError):
        ASTRAIdentity(
            user_id="u-001",
            username="x",
            display_name="X",
            entity_type="sb",
            entity_id="test",
            bank_id="test",
            role="ops_reviewer",
            connector_used="oauth2",    # invalid — not saml/ldap_ad/local
            authenticated_at=time.time(),
        )


def test_astra_identity_immutable():
    identity = ASTRAIdentity(
        user_id="u-001",
        username="ravi.mehta",
        display_name="Ravi Mehta",
        entity_type="sb",
        entity_id="saraswat-coop",
        bank_id="saraswat-coop",
        role="bank_it_admin",
        connector_used="saml",
        authenticated_at=time.time(),
    )
    with pytest.raises(Exception):
        identity.role = "ops_reviewer"   # type: ignore[misc]


def test_astra_identity_default_clearing_zones():
    identity = ASTRAIdentity(
        user_id="u-002",
        username="priya.nair",
        display_name="Priya Nair",
        entity_type="smb",
        entity_id="pune-ucb",
        bank_id="saraswat-coop",
        role="smb_admin",
        connector_used="local",
        authenticated_at=time.time(),
    )
    assert identity.clearing_zones == []


def test_astra_identity_pu_entity_type():
    identity = ASTRAIdentity(
        user_id="u-003",
        username="kiran.rao",
        display_name="Kiran Rao",
        entity_type="pu",
        entity_id="pu-mumbai-1",
        bank_id="saraswat-coop",
        role="ops_manager",
        connector_used="saml",
        authenticated_at=time.time(),
    )
    assert identity.entity_type == "pu"


def test_astra_identity_branch_entity_type():
    identity = ASTRAIdentity(
        user_id="u-004",
        username="deepak.shetty",
        display_name="Deepak Shetty",
        entity_type="branch",
        entity_id="branch-dadar-001",
        bank_id="saraswat-coop",
        role="ops_reviewer",
        clearing_zones=["MUMBAI"],
        connector_used="ldap_ad",
        authenticated_at=time.time(),
    )
    assert identity.entity_type == "branch"
