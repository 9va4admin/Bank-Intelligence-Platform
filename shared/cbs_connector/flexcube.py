"""
FlexCubeCBSConnector — Oracle FlexCube Core Banking adapter.

FlexCube exposes its core banking services via SOAP/XML web services
(urn:FCUBSAccService namespace). This connector wraps those SOAP calls and
translates responses to the canonical AccountInfo model used by the platform.

SOAP operations used:
  QueryCustAccount  → get_account_info
  QuerySignature    → get_signature_specimens
  QueryStopPayment  → check_stop_payment
  QueryPPS          → get_pps_entries
  QueryChequeStatus → get_cheque_status
"""
import base64
import re
from typing import Optional
import xml.etree.ElementTree as ET

import structlog

from shared.cbs_connector.base import (
    AccountInfo, AccountStatus, CBSConnector, CBSSignatoryData, PPSEntry, StopPaymentResult,
)
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

log = structlog.get_logger()

_NS = "urn:FCUBSAccService"
_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

_STATUS_MAP: dict[str, AccountStatus] = {
    "A":   AccountStatus.ACTIVE,
    "F":   AccountStatus.FROZEN,
    "C":   AccountStatus.CLOSED,
    "D":   AccountStatus.DORMANT,
    "I":   AccountStatus.DORMANT,
    "NPA": AccountStatus.NPA,
}


def _soap_request(operation: str, body_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soapenv:Envelope xmlns:soapenv="{_SOAP_ENV}" xmlns:fcubs="{_NS}">'
        f"<soapenv:Body><fcubs:{operation}>{body_xml}</fcubs:{operation}></soapenv:Body>"
        "</soapenv:Envelope>"
    )


def _find_text(root: ET.Element, tag: str, ns: str = _NS) -> Optional[str]:
    """Search for a tag anywhere in the tree, strip namespace."""
    # Try with namespace
    el = root.find(f".//{{{ns}}}{tag}")
    if el is None:
        # Try without namespace (some FlexCube versions omit it in responses)
        el = root.find(f".//{tag}")
    return el.text if el is not None else None


def _is_fault(root: ET.Element) -> bool:
    fault = root.find(f".//{{{_SOAP_ENV}}}Fault")
    if fault is None:
        fault = root.find(".//Fault")
    return fault is not None


def _fault_code(root: ET.Element) -> str:
    for tag in [f"{{{_SOAP_ENV}}}Fault", "Fault"]:
        fault = root.find(f".//{tag}")
        if fault is not None:
            code_el = fault.find("faultcode")
            return (code_el.text or "") if code_el is not None else ""
    return ""


class FlexCubeCBSConnector(CBSConnector):
    def __init__(self, base_url: str, bank_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._bank_id = bank_id
        self._http = None
        self._ready = False

    def connect(self, http_client=None) -> None:
        """
        Initialise the SOAP HTTP client.
        http_client is injected in tests; production creates an httpx.AsyncClient.
        """
        if http_client is not None:
            self._http = http_client
        else:
            import httpx  # type: ignore[import]
            self._http = httpx.AsyncClient(
                timeout=15.0,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
        self._ready = True
        log.info("cbs.flexcube.connected", base_url=self._base_url, bank_id=self._bank_id)

    async def _call(self, operation: str, body_xml: str) -> ET.Element:
        """Send a SOAP request and return the parsed XML root."""
        payload = _soap_request(operation, body_xml)
        url = f"{self._base_url}/FCJNeoWS/FCUBSAccService"
        try:
            response = await self._http.post(url, content=payload.encode())
            response.raise_for_status()
            return ET.fromstring(response.text)
        except Exception as exc:
            raise CBSUnavailableError(f"FlexCube SOAP call failed: {exc}") from exc

    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        self._assert_ready()
        body = f"<fcubs:CUSTAC_REQ><fcubs:ACCOUNT_NO>{account_number}</fcubs:ACCOUNT_NO></fcubs:CUSTAC_REQ>"
        try:
            root = await self._call("QueryCustAccount", body)
        except CBSUnavailableError:
            raise

        if _is_fault(root):
            code = _fault_code(root)
            if "404" in code or "not found" in code.lower():
                raise AccountNotFoundError(account_number)
            raise CBSUnavailableError(f"FlexCube fault: {code}")

        raw_status = _find_text(root, "ACCOUNT_STATUS") or "A"
        # Also check structural flags when explicit status not provided
        if _find_text(root, "AC_STAT_BLOCKED") == "Y":
            status = AccountStatus.FROZEN
        elif _find_text(root, "AC_STAT_CLOSED") == "Y":
            status = AccountStatus.CLOSED
        elif _find_text(root, "AC_STAT_DORMANT") == "Y":
            status = AccountStatus.DORMANT
        else:
            status = _STATUS_MAP.get(raw_status, AccountStatus.ACTIVE)

        bal_text = _find_text(root, "AVAIL_BAL")
        balance = float(bal_text) if bal_text else None
        account_hash = self._hash_account(account_number)

        return AccountInfo(
            account_number_hash=account_hash,
            account_number_last4=account_number[-4:],
            status=status,
            bank_id=bank_id,
            available_balance=balance,
            currency=_find_text(root, "CCY") or "INR",
            cbs_account_id=_find_text(root, "CUST_AC_NO"),
        )

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        self._assert_ready()
        body = f"<fcubs:SIG_REQ><fcubs:ACCOUNT_NO>{account_number}</fcubs:ACCOUNT_NO></fcubs:SIG_REQ>"
        try:
            root = await self._call("QuerySignature", body)
        except CBSUnavailableError:
            log.error("cbs.flexcube.get_signatures.failed",
                      account_last4=account_number[-4:])
            raise

        specimens = []
        for img_el in root.iter(f"{{{_NS}}}SIG_IMAGE"):
            if img_el.text:
                specimens.append(base64.b64decode(img_el.text))
        # Also try without namespace prefix
        if not specimens:
            for img_el in root.iter("SIG_IMAGE"):
                if img_el.text:
                    specimens.append(base64.b64decode(img_el.text))
        return specimens

    async def check_stop_payment(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> StopPaymentResult:
        self._assert_ready()
        body = (
            f"<fcubs:SP_REQ>"
            f"<fcubs:ACCOUNT_NO>{account_number}</fcubs:ACCOUNT_NO>"
            f"<fcubs:CHQ_NUM>{cheque_number}</fcubs:CHQ_NUM>"
            f"</fcubs:SP_REQ>"
        )
        try:
            root = await self._call("QueryStopPayment", body)
        except CBSUnavailableError:
            log.error("cbs.flexcube.check_stop_payment.failed",
                      account_last4=account_number[-4:], cheque=cheque_number)
            raise

        flag = _find_text(root, "SP_FLAG") or "N"
        reason = _find_text(root, "SP_REASON") or None
        stopped_at = _find_text(root, "SP_DATE") or None

        return StopPaymentResult(
            is_stopped=(flag.upper() == "Y"),
            reason=reason if reason else None,
            stopped_at=stopped_at if stopped_at else None,
        )

    async def get_pps_entries(self, account_number: str, bank_id: str) -> list[PPSEntry]:
        self._assert_ready()
        body = f"<fcubs:PPS_REQ><fcubs:ACCOUNT_NO>{account_number}</fcubs:ACCOUNT_NO></fcubs:PPS_REQ>"
        try:
            root = await self._call("QueryPPS", body)
        except CBSUnavailableError:
            log.error("cbs.flexcube.get_pps_entries.failed",
                      account_last4=account_number[-4:])
            raise

        entries = []
        # Collect all PPS_REC elements (with or without namespace)
        recs = list(root.iter(f"{{{_NS}}}PPS_REC")) or list(root.iter("PPS_REC"))
        for rec in recs:
            def _t(tag: str, _rec=rec) -> str:
                el = _rec.find(f"{{{_NS}}}{tag}")
                if el is None:
                    el = _rec.find(tag)
                return (el.text or "") if el is not None else ""

            entries.append(PPSEntry(
                cheque_series_start=_t("CHQ_FROM"),
                cheque_series_end=_t("CHQ_TO"),
                amount=float(_t("PPS_AMT") or 0.0),
                is_active=(_t("PPS_STATUS") == "A"),
            ))
        return entries

    async def get_cheque_status(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> str:
        self._assert_ready()
        body = (
            f"<fcubs:CHQ_REQ>"
            f"<fcubs:ACCOUNT_NO>{account_number}</fcubs:ACCOUNT_NO>"
            f"<fcubs:CHQ_NUM>{cheque_number}</fcubs:CHQ_NUM>"
            f"</fcubs:CHQ_REQ>"
        )
        try:
            root = await self._call("QueryChequeStatus", body)
        except CBSUnavailableError:
            log.error("cbs.flexcube.get_cheque_status.failed",
                      account_last4=account_number[-4:], cheque=cheque_number)
            raise

        return _find_text(root, "CHQ_STATUS") or "ACTIVE"

    async def get_signatory_data(
        self,
        account_number: str,
        bank_id: str,
    ) -> list[CBSSignatoryData]:
        """
        Fetch authorized signatories with specimen BLOB images via FlexCube SOAP.

        SOAP operation: getSignatories
        Returns response with: .signatories — list of objects with:
          .signatoryId, .role, .nameMasked, .operationType, .specimenBlobs (list[bytes])

        Raises CBSUnavailableError on SOAP fault or any other exception.
        """
        self._assert_ready()
        try:
            response = self._soap_client.service.getSignatories(
                accountId=account_number,
                bankId=bank_id,
            )
        except Exception as exc:
            log.error(
                "cbs.flexcube.get_signatory_data.failed",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            raise CBSUnavailableError(f"FlexCube get_signatory_data failed: {exc}") from exc

        result: list[CBSSignatoryData] = []
        for sig in getattr(response, "signatories", []) or []:
            specimen_images: list[bytes] = []
            for blob in getattr(sig, "specimenBlobs", []) or []:
                if blob:
                    specimen_images.append(bytes(blob))
            result.append(CBSSignatoryData(
                signatory_id=str(getattr(sig, "signatoryId", "")),
                role=str(getattr(sig, "role", "")),
                name_masked=str(getattr(sig, "nameMasked", "***")),
                specimen_images=specimen_images,
                operation_type=str(getattr(sig, "operationType", "J")),
            ))
        return result

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "FlexCubeCBSConnector.connect() has not been called. "
                "Call it in the service startup before querying CBS."
            )
