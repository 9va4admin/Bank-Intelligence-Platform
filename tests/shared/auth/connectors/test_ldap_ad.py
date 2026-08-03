"""Tests for LDAPADConnector — LDAPS bind + AD group-to-role mapping."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from shared.auth.connectors.ldap_ad import LDAPADConnector, LDAPCredentials, LDAPADConnectorConfig
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    LDAPServerUnreachableError,
)


GROUP_ROLE_MAP = {
    "CN=ASTRA-OpsReviewers,OU=Groups,DC=saraswat-coop,DC=local": "ops_reviewer",
    "CN=ASTRA-OpsManagers,OU=Groups,DC=saraswat-coop,DC=local": "ops_manager",
    "CN=ASTRA-ITAdmins,OU=Groups,DC=saraswat-coop,DC=local": "bank_it_admin",
}

LDAP_CONFIG = LDAPADConnectorConfig(
    server_url="ldaps://dc.saraswat-coop.internal:636",
    base_dn="DC=saraswat-coop,DC=local",
    user_search_base="OU=Users,DC=saraswat-coop,DC=local",
    group_search_base="OU=Groups,DC=saraswat-coop,DC=local",
    bind_dn_secret="auth/ldap/bind_dn",
    bind_pw_secret="auth/ldap/bind_pw",
    group_role_map=GROUP_ROLE_MAP,
)


def _mock_ldap_entry(member_of: list[str], display_name="Ravi Mehta", mail="ravi@saraswat.in"):
    entry = MagicMock()
    entry.memberOf.values = member_of
    entry.displayName.value = display_name
    entry.mail.value = mail
    return entry


@pytest.fixture
def connector():
    conn = LDAPADConnector(
        config=LDAP_CONFIG,
        entity_type="sb",
        entity_id="saraswat-coop",
        bank_id="saraswat-coop",
    )
    return conn


@pytest.mark.asyncio
async def test_authenticate_success(connector):
    entry = _mock_ldap_entry(
        ["CN=ASTRA-OpsReviewers,OU=Groups,DC=saraswat-coop,DC=local"]
    )
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = entry
        result = await connector.authenticate(
            LDAPCredentials(username="ravi.mehta", password="P@ssw0rd1!")
        )

    assert isinstance(result, ASTRAIdentity)
    assert result.username == "ravi.mehta"
    assert result.role == "ops_reviewer"
    assert result.connector_used == "ldap_ad"
    assert result.entity_type == "sb"
    assert result.bank_id == "saraswat-coop"


@pytest.mark.asyncio
async def test_authenticate_maps_first_matching_group(connector):
    # User is in multiple ASTRA groups — first match wins
    entry = _mock_ldap_entry([
        "CN=SomeOtherGroup,OU=Groups,DC=saraswat-coop,DC=local",   # not in map
        "CN=ASTRA-OpsManagers,OU=Groups,DC=saraswat-coop,DC=local",  # match
        "CN=ASTRA-OpsReviewers,OU=Groups,DC=saraswat-coop,DC=local", # also match (skipped)
    ])
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = entry
        result = await connector.authenticate(
            LDAPCredentials(username="mgr.user", password="P@ssw0rd1!")
        )
    assert result.role == "ops_manager"


@pytest.mark.asyncio
async def test_authenticate_wrong_password_raises(connector):
    import ldap3
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.side_effect = ldap3.core.exceptions.LDAPBindError("Invalid credentials")
        with pytest.raises(AuthenticationError, match="invalid credentials"):
            await connector.authenticate(
                LDAPCredentials(username="ravi.mehta", password="WrongPass!")
            )


@pytest.mark.asyncio
async def test_authenticate_user_not_found_in_directory_raises(connector):
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = None   # user bound OK but search found nothing
        with pytest.raises(AuthenticationError, match="not found in directory"):
            await connector.authenticate(
                LDAPCredentials(username="ghost.user", password="P@ssw0rd1!")
            )


@pytest.mark.asyncio
async def test_authenticate_no_group_mapping_raises(connector):
    entry = _mock_ldap_entry([
        "CN=HR-Staff,OU=Groups,DC=saraswat-coop,DC=local",  # not in ASTRA map
    ])
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = entry
        with pytest.raises(AuthorizationError, match="no ASTRA role"):
            await connector.authenticate(
                LDAPCredentials(username="hr.user", password="P@ssw0rd1!")
            )


@pytest.mark.asyncio
async def test_authenticate_empty_member_of_raises(connector):
    entry = _mock_ldap_entry([])   # user has no group memberships
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.return_value = entry
        with pytest.raises(AuthorizationError, match="no ASTRA role"):
            await connector.authenticate(
                LDAPCredentials(username="ravi.mehta", password="P@ssw0rd1!")
            )


@pytest.mark.asyncio
async def test_authenticate_server_unreachable_raises(connector):
    import ldap3
    with patch.object(connector, "_ldap_bind_and_search", new_callable=AsyncMock) as mock_bind:
        mock_bind.side_effect = ldap3.core.exceptions.LDAPSocketOpenError("Cannot connect")
        with pytest.raises(LDAPServerUnreachableError):
            await connector.authenticate(
                LDAPCredentials(username="ravi.mehta", password="P@ssw0rd1!")
            )


def test_config_rejects_plain_ldap_url():
    """LDAPS required — plain ldap:// must be rejected at config time."""
    with pytest.raises(Exception):
        LDAPADConnectorConfig(
            server_url="ldap://dc.saraswat-coop.internal:389",  # plain — rejected
            base_dn="DC=saraswat-coop,DC=local",
            user_search_base="OU=Users,DC=saraswat-coop,DC=local",
            group_search_base="OU=Groups,DC=saraswat-coop,DC=local",
            bind_dn_secret="auth/ldap/bind_dn",
            bind_pw_secret="auth/ldap/bind_pw",
        )


@pytest.mark.asyncio
async def test_health_check_true_when_server_up(connector):
    with patch.object(connector, "_test_connection", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = True
        assert await connector.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_when_server_down(connector):
    with patch.object(connector, "_test_connection", new_callable=AsyncMock) as mock_test:
        mock_test.side_effect = Exception("Connection refused")
        assert await connector.health_check() is False


def test_connector_type(connector):
    assert connector.connector_type == "ldap_ad"


def test_clearing_zones_from_config(connector):
    """Connector can have pre-configured zone list for the entity."""
    conn_with_zones = LDAPADConnector(
        config=LDAP_CONFIG,
        entity_type="sb",
        entity_id="saraswat-coop",
        bank_id="saraswat-coop",
        clearing_zones=["MUMBAI", "PUNE"],
    )
    assert conn_with_zones.clearing_zones == ["MUMBAI", "PUNE"]
