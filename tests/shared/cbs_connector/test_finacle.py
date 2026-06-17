"""
Tests for FinacleCBSConnector — account info fetch, balance, status mapping,
signature specimen retrieval, and error handling.

TDD: written BEFORE the implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.cbs_connector.finacle import FinacleCBSConnector
from shared.cbs_connector.base import AccountStatus
from shared.cbs_connector.exceptions import CBSUnavailableError, AccountNotFoundError


@pytest.fixture
def connector() -> FinacleCBSConnector:
    c = FinacleCBSConnector(
        base_url="http://finacle.bank.internal:8080",
        bank_id="test-bank",
    )
    mock_http = AsyncMock()
    c._http = mock_http
    c._ready = True
    return c


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# get_account_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_returns_active_status(connector):
    connector._http.get = AsyncMock(return_value=_mock_response({
        "accountId": "ACC001",
        "status": "ACTIVE",
        "availableBalance": 250000.50,
        "currency": "INR",
    }))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.ACTIVE
    assert info.available_balance == 250000.50
    assert info.bank_id == "test-bank"


@pytest.mark.asyncio
async def test_get_account_info_maps_frozen_status(connector):
    connector._http.get = AsyncMock(return_value=_mock_response({
        "accountId": "ACC002",
        "status": "FROZEN",
        "availableBalance": 0.0,
        "currency": "INR",
    }))
    info = await connector.get_account_info("9999999999999999", "test-bank")
    assert info.status == AccountStatus.FROZEN


@pytest.mark.asyncio
async def test_get_account_info_never_stores_raw_account_number(connector):
    connector._http.get = AsyncMock(return_value=_mock_response({
        "accountId": "ACC001",
        "status": "ACTIVE",
        "availableBalance": 10000.0,
        "currency": "INR",
    }))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    info_dict = info.model_dump()
    for val in info_dict.values():
        if isinstance(val, str):
            assert "1234567890123456" not in val, "Raw account number leaked into AccountInfo"


@pytest.mark.asyncio
async def test_get_account_info_raises_not_found_on_404(connector):
    connector._http.get = AsyncMock(return_value=_mock_response({}, status_code=404))
    with pytest.raises(AccountNotFoundError):
        await connector.get_account_info("0000000000000000", "test-bank")


@pytest.mark.asyncio
async def test_get_account_info_raises_unavailable_on_connection_error(connector):
    connector._http.get = AsyncMock(side_effect=Exception("connection refused"))
    with pytest.raises(CBSUnavailableError):
        await connector.get_account_info("1234567890123456", "test-bank")


@pytest.mark.asyncio
async def test_get_account_info_raises_if_not_ready():
    c = FinacleCBSConnector(base_url="http://finacle", bank_id="b")
    with pytest.raises(RuntimeError, match="connect"):
        await c.get_account_info("1234567890", "b")


# ---------------------------------------------------------------------------
# get_signature_specimens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_signature_specimens_returns_bytes_list(connector):
    import base64
    connector._http.get = AsyncMock(return_value=_mock_response({
        "specimens": [
            {"image": base64.b64encode(b"sig-img-1").decode()},
            {"image": base64.b64encode(b"sig-img-2").decode()},
        ]
    }))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert len(specimens) == 2
    assert specimens[0] == b"sig-img-1"


@pytest.mark.asyncio
async def test_get_signature_specimens_returns_empty_list_if_none(connector):
    connector._http.get = AsyncMock(return_value=_mock_response({"specimens": []}))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert specimens == []


@pytest.mark.asyncio
async def test_get_signature_specimens_raises_unavailable_on_error(connector):
    connector._http.get = AsyncMock(side_effect=Exception("timeout"))
    with pytest.raises(CBSUnavailableError):
        await connector.get_signature_specimens("1234567890123456", "test-bank")
