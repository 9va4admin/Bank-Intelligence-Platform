"""
Tests for FlexCubeCBSConnector — Oracle FlexCube core banking adapter.

FlexCube uses an XML/SOAP web services interface (urn:FCUBSAccService).
The connector wraps the SOAP calls and translates to the canonical AccountInfo model.
"""
import base64
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from shared.cbs_connector.flexcube import FlexCubeCBSConnector
from shared.cbs_connector.base import AccountStatus, StopPaymentResult, PPSEntry
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError


# ---------------------------------------------------------------------------
# Helpers — build SOAP XML response strings
# ---------------------------------------------------------------------------

def _soap_account_response(
    acc_no: str = "1234567890123456",
    status: str = "A",
    balance: str = "150000.00",
    currency: str = "INR",
    acc_id: str = "FC-001",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:fcubs="urn:FCUBSAccService">
  <soapenv:Body>
    <fcubs:QueryCustAccountResponse>
      <fcubs:CUSTAC_RES>
        <fcubs:ACCOUNT_NO>{acc_no}</fcubs:ACCOUNT_NO>
        <fcubs:AC_STAT_NO_DR>N</fcubs:AC_STAT_NO_DR>
        <fcubs:AC_STAT_BLOCKED>{"Y" if status == "F" else "N"}</fcubs:AC_STAT_BLOCKED>
        <fcubs:AC_STAT_CLOSED>{"Y" if status == "C" else "N"}</fcubs:AC_STAT_CLOSED>
        <fcubs:AC_STAT_DORMANT>{"Y" if status in ("D", "I") else "N"}</fcubs:AC_STAT_DORMANT>
        <fcubs:ACCOUNT_STATUS>{status}</fcubs:ACCOUNT_STATUS>
        <fcubs:AVAIL_BAL>{balance}</fcubs:AVAIL_BAL>
        <fcubs:CCY>{currency}</fcubs:CCY>
        <fcubs:CUST_AC_NO>{acc_id}</fcubs:CUST_AC_NO>
      </fcubs:CUSTAC_RES>
    </fcubs:QueryCustAccountResponse>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_sig_response(images: list[bytes]) -> str:
    items = "".join(
        f"<fcubs:SIG_IMAGE>{base64.b64encode(img).decode()}</fcubs:SIG_IMAGE>"
        for img in images
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:fcubs="urn:FCUBSAccService">
  <soapenv:Body>
    <fcubs:QuerySignatureResponse>
      <fcubs:SIGNATURES>{items}</fcubs:SIGNATURES>
    </fcubs:QuerySignatureResponse>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_stop_response(active: bool, reason: str = "", date: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:fcubs="urn:FCUBSAccService">
  <soapenv:Body>
    <fcubs:QueryStopPaymentResponse>
      <fcubs:SP_FLAG>{"Y" if active else "N"}</fcubs:SP_FLAG>
      <fcubs:SP_REASON>{reason}</fcubs:SP_REASON>
      <fcubs:SP_DATE>{date}</fcubs:SP_DATE>
    </fcubs:QueryStopPaymentResponse>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_pps_response(entries: list[dict]) -> str:
    rows = ""
    for e in entries:
        rows += (
            f"<fcubs:PPS_REC>"
            f"<fcubs:CHQ_FROM>{e['from']}</fcubs:CHQ_FROM>"
            f"<fcubs:CHQ_TO>{e['to']}</fcubs:CHQ_TO>"
            f"<fcubs:PPS_AMT>{e['amt']}</fcubs:PPS_AMT>"
            f"<fcubs:PPS_STATUS>{e['sts']}</fcubs:PPS_STATUS>"
            f"</fcubs:PPS_REC>"
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:fcubs="urn:FCUBSAccService">
  <soapenv:Body>
    <fcubs:QueryPPSResponse>
      <fcubs:PPS_RECORDS>{rows}</fcubs:PPS_RECORDS>
    </fcubs:QueryPPSResponse>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_cheque_status_response(status: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:fcubs="urn:FCUBSAccService">
  <soapenv:Body>
    <fcubs:QueryChequeStatusResponse>
      <fcubs:CHQ_STATUS>{status}</fcubs:CHQ_STATUS>
    </fcubs:QueryChequeStatusResponse>
  </soapenv:Body>
</soapenv:Envelope>"""


def _soap_fault(code: str = "404", msg: str = "Account not found") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <soapenv:Fault>
      <faultcode>{code}</faultcode>
      <faultstring>{msg}</faultstring>
    </soapenv:Fault>
  </soapenv:Body>
</soapenv:Envelope>"""


def _make_soap_mock(response_text: str, raise_exc=None):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = response_text
    mock_resp.raise_for_status = MagicMock()

    mock_http = MagicMock()
    if raise_exc:
        mock_http.post = AsyncMock(side_effect=raise_exc)
    else:
        mock_http.post = AsyncMock(return_value=mock_resp)
    return mock_http


@pytest.fixture
def connector() -> FlexCubeCBSConnector:
    return FlexCubeCBSConnector(
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
# connect()
# ---------------------------------------------------------------------------

def test_connect_sets_ready(connector):
    connector.connect()
    assert connector._ready is True


def test_connect_with_http_client_sets_ready(connector):
    connector.connect(http_client=_make_soap_mock(""))
    assert connector._ready is True


# ---------------------------------------------------------------------------
# connect() — _soap_client wiring (get_signatory_data's WSDL-based client)
#
# Regression coverage for the bug where connect() never assigned
# _soap_client at all, so get_signatory_data() always raised AttributeError
# in real production regardless of connectivity. connect() must now always
# leave _soap_client set to *something* (a real client or None on graceful
# degradation) — never simply absent.
# ---------------------------------------------------------------------------

def test_connect_without_injection_sets_soap_client_attribute(connector):
    """The original bug: _soap_client was never assigned by connect() at
    all, so accessing it raised AttributeError rather than being None.
    hasattr must be True even though base_url here is unreachable (WSDL
    fetch fails and degrades to None) — the attribute must exist either way."""
    connector.connect()
    assert hasattr(connector, "_soap_client")


def test_connect_without_injection_degrades_to_none_on_unreachable_wsdl(connector):
    connector.connect()
    assert connector._soap_client is None


def test_connect_with_soap_client_injection_uses_injected_instance(connector):
    fake_soap_client = MagicMock()
    connector.connect(soap_client=fake_soap_client)
    assert connector._soap_client is fake_soap_client


def test_connect_builds_real_zeep_client_when_wsdl_reachable(connector):
    """When zeep.Client construction succeeds, _build_soap_client must return
    it (not silently discard it) and derive the WSDL URL from base_url with
    the FCUBSSignatoryService suffix, mirroring FCUBSAccService's pattern."""
    fake_zeep_client = MagicMock()
    with patch("zeep.Client", return_value=fake_zeep_client) as mock_zeep_client:
        connector.connect()
    assert connector._soap_client is fake_zeep_client
    called_kwargs = mock_zeep_client.call_args.kwargs
    assert called_kwargs["wsdl"] == "http://flexcube.bank.internal:8080/FCJNeoWS/FCUBSSignatoryService?wsdl"


@pytest.mark.asyncio
async def test_get_signatory_data_raises_cbs_unavailable_not_attribute_error_when_degraded(connector):
    """End-to-end regression for the original bug report: calling
    get_signatory_data() after a real connect() (no injection, unreachable
    WSDL) must raise CBSUnavailableError — never a raw AttributeError."""
    connector.connect()  # no soap_client injected; WSDL unreachable -> degrades to None
    with pytest.raises(CBSUnavailableError):
        await connector.get_signatory_data("ACC001", "test-bank")


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
    connector.connect(http_client=_make_soap_mock(_soap_account_response(status="A")))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.ACTIVE
    assert info.available_balance == 150000.0
    assert info.currency == "INR"
    assert info.account_number_last4 == "3456"
    assert info.bank_id == "test-bank"


@pytest.mark.asyncio
async def test_get_account_info_blocked_account_is_frozen(connector):
    connector.connect(http_client=_make_soap_mock(_soap_account_response(status="F")))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.FROZEN


@pytest.mark.asyncio
async def test_get_account_info_closed_account(connector):
    connector.connect(http_client=_make_soap_mock(_soap_account_response(status="C")))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.CLOSED


@pytest.mark.asyncio
async def test_get_account_info_dormant_account(connector):
    connector.connect(http_client=_make_soap_mock(_soap_account_response(status="D")))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.DORMANT


@pytest.mark.asyncio
async def test_get_account_info_npa_account(connector):
    connector.connect(http_client=_make_soap_mock(_soap_account_response(status="NPA")))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert info.status == AccountStatus.NPA


@pytest.mark.asyncio
async def test_get_account_info_hash_does_not_contain_raw_number(connector):
    connector.connect(http_client=_make_soap_mock(_soap_account_response()))
    info = await connector.get_account_info("1234567890123456", "test-bank")
    assert "1234567890123456" not in info.account_number_hash


# ---------------------------------------------------------------------------
# get_account_info — error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_account_info_soap_fault_with_404_raises_account_not_found(connector):
    connector.connect(http_client=_make_soap_mock(_soap_fault("404", "Account not found")))
    with pytest.raises(AccountNotFoundError):
        await connector.get_account_info("1234567890123456", "test-bank")


@pytest.mark.asyncio
async def test_get_account_info_network_error_raises_cbs_unavailable(connector):
    connector.connect(http_client=_make_soap_mock("", raise_exc=Exception("Connection refused")))
    with pytest.raises(CBSUnavailableError):
        await connector.get_account_info("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_signature_specimens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_signature_specimens_returns_decoded_bytes(connector):
    img1, img2 = b"\x89PNG\r\n", b"\xff\xd8\xff"
    connector.connect(http_client=_make_soap_mock(_soap_sig_response([img1, img2])))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert len(specimens) == 2
    assert specimens[0] == img1
    assert specimens[1] == img2


@pytest.mark.asyncio
async def test_get_signature_specimens_empty_when_none_on_file(connector):
    connector.connect(http_client=_make_soap_mock(_soap_sig_response([])))
    specimens = await connector.get_signature_specimens("1234567890123456", "test-bank")
    assert specimens == []


@pytest.mark.asyncio
async def test_get_signature_specimens_network_error_raises_cbs_unavailable(connector):
    connector.connect(http_client=_make_soap_mock("", raise_exc=Exception("timeout")))
    with pytest.raises(CBSUnavailableError):
        await connector.get_signature_specimens("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# check_stop_payment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_stop_payment_stopped(connector):
    connector.connect(http_client=_make_soap_mock(
        _soap_stop_response(True, "CUSTOMER_REQUEST", "2026-06-01")
    ))
    result = await connector.check_stop_payment("1234567890123456", "000042", "test-bank")
    assert isinstance(result, StopPaymentResult)
    assert result.is_stopped is True
    assert result.reason == "CUSTOMER_REQUEST"


@pytest.mark.asyncio
async def test_check_stop_payment_not_stopped(connector):
    connector.connect(http_client=_make_soap_mock(_soap_stop_response(False)))
    result = await connector.check_stop_payment("1234567890123456", "000042", "test-bank")
    assert result.is_stopped is False


@pytest.mark.asyncio
async def test_check_stop_payment_network_error_raises_cbs_unavailable(connector):
    connector.connect(http_client=_make_soap_mock("", raise_exc=Exception("timeout")))
    with pytest.raises(CBSUnavailableError):
        await connector.check_stop_payment("1234567890123456", "000042", "test-bank")


# ---------------------------------------------------------------------------
# get_pps_entries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pps_entries_returns_entries(connector):
    connector.connect(http_client=_make_soap_mock(_soap_pps_response([
        {"from": "000001", "to": "000100", "amt": "50000.00", "sts": "A"},
        {"from": "000101", "to": "000200", "amt": "75000.00", "sts": "I"},
    ])))
    entries = await connector.get_pps_entries("1234567890123456", "test-bank")
    assert len(entries) == 2
    assert entries[0].cheque_series_start == "000001"
    assert entries[0].amount == 50000.0
    assert entries[0].is_active is True
    assert entries[1].is_active is False


@pytest.mark.asyncio
async def test_get_pps_entries_empty_when_not_registered(connector):
    connector.connect(http_client=_make_soap_mock(_soap_pps_response([])))
    entries = await connector.get_pps_entries("1234567890123456", "test-bank")
    assert entries == []


@pytest.mark.asyncio
async def test_get_pps_entries_network_error_raises_cbs_unavailable(connector):
    connector.connect(http_client=_make_soap_mock("", raise_exc=Exception("timeout")))
    with pytest.raises(CBSUnavailableError):
        await connector.get_pps_entries("1234567890123456", "test-bank")


# ---------------------------------------------------------------------------
# get_cheque_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cheque_status_active(connector):
    connector.connect(http_client=_make_soap_mock(_soap_cheque_status_response("ACTIVE")))
    status = await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
    assert status == "ACTIVE"


@pytest.mark.asyncio
async def test_get_cheque_status_used(connector):
    connector.connect(http_client=_make_soap_mock(_soap_cheque_status_response("USED")))
    status = await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
    assert status == "USED"


@pytest.mark.asyncio
async def test_get_cheque_status_network_error_raises_cbs_unavailable(connector):
    connector.connect(http_client=_make_soap_mock("", raise_exc=Exception("timeout")))
    with pytest.raises(CBSUnavailableError):
        await connector.get_cheque_status("1234567890123456", "000042", "test-bank")
