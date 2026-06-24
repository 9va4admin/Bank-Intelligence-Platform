"""
Tests for BaNCSCBSConnector — stub adapter for TCS BaNCS core banking.
"""
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# BaNCSCBSConnector doesn't implement the 3 abstract methods (check_stop_payment,
# get_pps_entries, get_cheque_status). We create a concrete subclass for testing.
from shared.cbs_connector.bancs import BaNCSCBSConnector
from shared.cbs_connector.base import StopPaymentResult, PPSEntry


class BaNCSCBSConnectorForTest(BaNCSCBSConnector):
    """Minimal concrete subclass that stubs the unimplemented abstract methods."""

    async def check_stop_payment(self, account_number, cheque_number, bank_id):
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def get_pps_entries(self, account_number, bank_id):
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def get_cheque_status(self, account_number, cheque_number, bank_id):
        raise NotImplementedError("BaNCS adapter not yet implemented")


@pytest.fixture
def connector() -> BaNCSCBSConnectorForTest:
    return BaNCSCBSConnectorForTest(
        base_url="http://bancs.bank.internal:8080", bank_id="test-bank"
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_constructor_stores_base_url(connector):
    assert connector._base_url == "http://bancs.bank.internal:8080"


def test_constructor_stores_bank_id(connector):
    assert connector._bank_id == "test-bank"


def test_constructor_not_ready_before_connect(connector):
    assert connector._ready is False


# ---------------------------------------------------------------------------
# connect() — with injected http_client
# ---------------------------------------------------------------------------

def test_connect_with_injected_http_client_sets_ready(connector):
    mock_http = MagicMock()
    connector.connect(http_client=mock_http)
    assert connector._ready is True
    assert connector._http is mock_http


def test_connect_without_http_client_uses_httpx(connector, monkeypatch):
    """connect() without http_client must import httpx and create AsyncClient."""
    fake_httpx = MagicMock()
    fake_client = MagicMock()
    fake_httpx.AsyncClient.return_value = fake_client
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    connector.connect()

    assert connector._ready is True
    fake_httpx.AsyncClient.assert_called_once_with(timeout=10.0)
    assert connector._http is fake_client


# ---------------------------------------------------------------------------
# get_account_info — stub raises NotImplementedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_raises_not_implemented(connector):
    connector._ready = True
    connector._http = MagicMock()
    with pytest.raises(NotImplementedError, match="BaNCS"):
        await connector.get_account_info("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_signature_specimens — stub raises NotImplementedError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_signature_specimens_raises_not_implemented(connector):
    connector._ready = True
    connector._http = MagicMock()
    with pytest.raises(NotImplementedError, match="BaNCS"):
        await connector.get_signature_specimens("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# Stub methods inherited from BaNCSCBSConnector directly (not via subclass)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_stop_payment_raises_not_implemented():
    """call the method directly on the stub to cover the NotImplementedError lines."""
    bancs = BaNCSCBSConnectorForTest.__new__(BaNCSCBSConnectorForTest)
    bancs._base_url = "http://bancs"
    bancs._bank_id = "test-bank"
    bancs._ready = True
    bancs._http = MagicMock()

    # Call the base class method directly (bypassing the test subclass override)
    with pytest.raises(NotImplementedError):
        await BaNCSCBSConnector.get_account_info(bancs, "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await BaNCSCBSConnector.get_signature_specimens(bancs, "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await BaNCSCBSConnector.get_cheque_status(bancs, "000001", "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await BaNCSCBSConnector.check_stop_payment(bancs, "000001", "1234567890", "test-bank")

    with pytest.raises(NotImplementedError):
        await BaNCSCBSConnector.get_pps_entries(bancs, "1234567890", "test-bank")
