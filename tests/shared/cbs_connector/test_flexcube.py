"""
Tests for FlexCubeCBSConnector — stub adapter for Oracle FlexCube core banking.
"""
import pytest
from unittest.mock import MagicMock

from shared.cbs_connector.flexcube import FlexCubeCBSConnector
from shared.cbs_connector.base import StopPaymentResult, PPSEntry


# FlexCubeCBSConnector doesn't implement the 3 abstract methods.
# Create a concrete subclass for testing.
class FlexCubeCBSConnectorForTest(FlexCubeCBSConnector):
    """Minimal concrete subclass that stubs unimplemented abstract methods."""

    async def check_stop_payment(self, account_number, cheque_number, bank_id):
        raise NotImplementedError("FlexCube adapter not yet implemented")

    async def get_pps_entries(self, account_number, bank_id):
        raise NotImplementedError("FlexCube adapter not yet implemented")

    async def get_cheque_status(self, account_number, cheque_number, bank_id):
        raise NotImplementedError("FlexCube adapter not yet implemented")


@pytest.fixture
def connector() -> FlexCubeCBSConnectorForTest:
    return FlexCubeCBSConnectorForTest(
        base_url="http://flexcube.bank.internal:8080", bank_id="test-bank"
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_constructor_stores_base_url(connector):
    assert connector._base_url == "http://flexcube.bank.internal:8080"


def test_constructor_stores_bank_id(connector):
    assert connector._bank_id == "test-bank"


def test_constructor_not_ready_before_connect(connector):
    assert connector._ready is False


# ---------------------------------------------------------------------------
# connect() — FlexCube ignores http_client (uses SOAP, no async HTTP needed)
# ---------------------------------------------------------------------------

def test_connect_sets_ready(connector):
    connector.connect()
    assert connector._ready is True


def test_connect_with_http_client_sets_ready(connector):
    """connect() accepts an optional http_client arg but FlexCube ignores it."""
    connector.connect(http_client=MagicMock())
    assert connector._ready is True


# ---------------------------------------------------------------------------
# get_account_info — stub raises NotImplementedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_raises_not_implemented(connector):
    connector.connect()
    with pytest.raises(NotImplementedError, match="FlexCube"):
        await connector.get_account_info("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_signature_specimens — stub raises NotImplementedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_signature_specimens_raises_not_implemented(connector):
    connector.connect()
    with pytest.raises(NotImplementedError, match="FlexCube"):
        await connector.get_signature_specimens("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# Stub methods inherited directly from FlexCubeCBSConnector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flexcube_base_methods_raise_not_implemented():
    """Call the base class methods directly to cover the NotImplementedError lines."""
    flex = FlexCubeCBSConnectorForTest.__new__(FlexCubeCBSConnectorForTest)
    flex._base_url = "http://flexcube"
    flex._bank_id = "test-bank"
    flex._ready = True

    with pytest.raises(NotImplementedError):
        await FlexCubeCBSConnector.get_account_info(flex, "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await FlexCubeCBSConnector.get_signature_specimens(flex, "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await FlexCubeCBSConnector.get_cheque_status(flex, "000001", "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await FlexCubeCBSConnector.check_stop_payment(flex, "000001", "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await FlexCubeCBSConnector.get_pps_entries(flex, "1234567890", "test-bank")
