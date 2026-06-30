"""
Tests for BaNCSCBSConnector — TCS BaNCS core banking adapter.

TCS BaNCS uses a REST/JSON API with BaNCS-specific status codes and field names
that differ from Finacle. The connector translates these to the canonical AccountInfo
model used by the rest of the platform.
"""
import base64
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock


from shared.cbs_connector.bancs import BaNCSCBSConnector
from shared.cbs_connector.base import AccountStatus, StopPaymentResult, PPSEntry
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_mock(status_code=200, json_body=None, raise_exc=None):
    """Return a mock async HTTP client whose .get() returns a configured response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_body or {}
    if raise_exc:
        mock_resp.raise_for_status.side_effect = raise_exc
    else:
        mock_resp.raise_for_status = MagicMock()

    mock_http = MagicMock()
    mock_http.get = AsyncMock(return_value=mock_resp)
    mock_http.post = AsyncMock(return_value=mock_resp)
    return mock_http


@pytest.fixture
def connector() -> BaNCSCBSConnector:
    c = BaNCSCBSConnector(base_url="http://bancs.bank.internal:8080", bank_id="test-bank")
    return c


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_constructor_stores_base_url_stripped(connector):
    assert connector._base_url == "http://bancs.bank.internal:8080"


def test_constructor_stores_bank_id(connector):
    assert connector._bank_id == "test-bank"


def test_constructor_not_ready_before_connect(connector):
    assert connector._ready is False


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

def test_connect_with_injected_http_client_sets_ready(connector):
    mock_http = MagicMock()
    connector.connect(http_client=mock_http)
    assert connector._ready is True
    assert connector._http is mock_http


def test_connect_without_http_client_uses_httpx(connector, monkeypatch):
    fake_httpx = MagicMock()
    fake_client = MagicMock()
    fake_httpx.AsyncClient.return_value = fake_client
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    connector.connect()
    assert connector._ready is True
    fake_httpx.AsyncClient.assert_called_once_with(timeout=10.0)
    assert connector._http is fake_client


# ---------------------------------------------------------------------------
# _assert_ready()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_raises_runtime_if_not_connected(connector):
    with pytest.raises(RuntimeError, match="connect()"):
        await connector.get_account_info("1234567890", "test-bank")


# ---------------------------------------------------------------------------
# get_account_info — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_active_account(connector):
    """BaNCS 'A' status maps to ACTIVE."""
    connector.connect(http_client=_make_http_mock(json_body={
        "acctSts": "A",
        "avlBal": 150000.0,
        "ccy": "INR",
        "acctId": "BANCS-ACC-001",
    }))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.ACTIVE
    assert info.available_balance == 150000.0
    assert info.currency == "INR"
    assert info.account_number_last4 == "3456"
    assert info.bank_id == "test-bank"


@pytest.mark.asyncio
async def test_get_account_info_frozen_account(connector):
    """BaNCS 'F' status maps to FROZEN."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "F", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.FROZEN


@pytest.mark.asyncio
async def test_get_account_info_dormant_account(connector):
    """BaNCS 'I' (Inactive) status maps to DORMANT."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "I", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.DORMANT


@pytest.mark.asyncio
async def test_get_account_info_closed_account(connector):
    """BaNCS 'C' status maps to CLOSED."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "C", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.CLOSED


@pytest.mark.asyncio
async def test_get_account_info_npa_account(connector):
    """BaNCS 'N' status maps to NPA."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "N", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.NPA


@pytest.mark.asyncio
async def test_get_account_info_unknown_status_defaults_to_active(connector):
    """Unknown BaNCS status codes default to ACTIVE (conservative)."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "XYZ", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_get_account_info_account_hash_does_not_contain_raw_number(connector):
    """account_number_hash must never be the raw account number."""
    connector.connect(http_client=_make_http_mock(json_body={"acctSts": "A", "avlBal": 0}))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert "1234567890123456" not in info.account_number_hash


# ---------------------------------------------------------------------------
# get_account_info — error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_404_raises_account_not_found(connector):
    connector.connect(http_client=_make_http_mock(status_code=404, json_body={}))
    with pytest.raises(AccountNotFoundError):
        await connector.get_account_info("1234567890123456", "test-bank")


@pytest.mark.asyncio
async def test_get_account_info_network_error_raises_cbs_unavailable(connector):
    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=Exception("Connection refused"))
    connector.connect(http_client=mock_http)
    with pytest.raises(CBSUnavailableError):
        await connector.get_account_info("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_signature_specimens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_signature_specimens_returns_decoded_bytes(connector):
    img_bytes = b"\x89PNG\r\n"
    encoded = base64.b64encode(img_bytes).decode()
    connector.connect(http_client=_make_http_mock(json_body={"sigImages": [
        {"imgData": encoded},
        {"imgData": encoded},
    ]}))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert len(specimens) == 2
    assert specimens[0] == img_bytes


@pytest.mark.asyncio
async def test_get_signature_specimens_empty_list_when_none(connector):
    connector.connect(http_client=_make_http_mock(json_body={"sigImages": []}))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert specimens == []


@pytest.mark.asyncio
async def test_get_signature_specimens_network_error_raises_cbs_unavailable(connector):
    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=Exception("timeout"))
    connector.connect(http_client=mock_http)
    with pytest.raises(CBSUnavailableError):
        await connector.get_signature_specimens("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# check_stop_payment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_stop_payment_is_stopped_true(connector):
    connector.connect(http_client=_make_http_mock(json_body={
        "spActive": True,
        "spReason": "CUSTOMER_REQUEST",
        "spDt": "2026-06-01T10:00:00Z",
    }))
    result = await connector.check_stop_payment("1234567890123456", "000042", "test-bank")
    assert isinstance(result, StopPaymentResult)
    assert result.is_stopped is True
    assert result.reason == "CUSTOMER_REQUEST"


@pytest.mark.asyncio
async def test_check_stop_payment_is_stopped_false(connector):
    connector.connect(http_client=_make_http_mock(json_body={"spActive": False}))
    result = await connector.check_stop_payment("1234567890123456", "000042", "test-bank")
    assert result.is_stopped is False
    assert result.reason is None


@pytest.mark.asyncio
async def test_check_stop_payment_network_error_raises_cbs_unavailable(connector):
    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=Exception("timeout"))
    connector.connect(http_client=mock_http)
    with pytest.raises(CBSUnavailableError):
        await connector.check_stop_payment("1234567890123456", "000042", "test-bank")


# ---------------------------------------------------------------------------
# get_pps_entries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pps_entries_returns_active_entries(connector):
    connector.connect(http_client=_make_http_mock(json_body={"ppsList": [
        {"chqFrom": "000001", "chqTo": "000100", "amt": 50000.0, "sts": "A"},
        {"chqFrom": "000101", "chqTo": "000200", "amt": 75000.0, "sts": "I"},
    ]}))
    entries = await connector.get_pps_entries("1234567890123456", "test-bank")
    assert len(entries) == 2
    assert entries[0].cheque_series_start == "000001"
    assert entries[0].amount == 50000.0
    assert entries[0].is_active is True
    assert entries[1].is_active is False


@pytest.mark.asyncio
async def test_get_pps_entries_empty_when_not_registered(connector):
    connector.connect(http_client=_make_http_mock(json_body={"ppsList": []}))
    entries = await connector.get_pps_entries("1234567890123456", "test-bank")
    assert entries == []


@pytest.mark.asyncio
async def test_get_pps_entries_network_error_raises_cbs_unavailable(connector):
    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=Exception("timeout"))
    connector.connect(http_client=mock_http)
    with pytest.raises(CBSUnavailableError):
        await connector.get_pps_entries("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_cheque_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cheque_status_active(connector):
    connector.connect(http_client=_make_http_mock(json_body={"chqSts": "ACTIVE"}))
    status = await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
    assert status == "ACTIVE"


@pytest.mark.asyncio
async def test_get_cheque_status_used(connector):
    connector.connect(http_client=_make_http_mock(json_body={"chqSts": "USED"}))
    status = await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
    assert status == "USED"


@pytest.mark.asyncio
async def test_get_cheque_status_network_error_raises_cbs_unavailable(connector):
    mock_http = MagicMock()
    mock_http.get = AsyncMock(side_effect=Exception("timeout"))
    connector.connect(http_client=mock_http)
    with pytest.raises(CBSUnavailableError):
        await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
