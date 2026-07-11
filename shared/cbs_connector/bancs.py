"""
BaNCSCBSConnector — TCS BaNCS Core Banking adapter.

Communicates with TCS BaNCS REST/JSON API. BaNCS uses single-character status codes
and different field names from Finacle — all normalised to the canonical AccountInfo model.

BaNCS status codes:
  A → ACTIVE      F → FROZEN     C → CLOSED
  I → DORMANT     N → NPA        D → DORMANT
"""
import base64
from typing import Any

import structlog

from shared.cbs_connector.base import (
    AccountInfo, AccountStatus, CBSConnector, CBSSignatoryData, PPSEntry, StopPaymentResult,
)
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

log = structlog.get_logger()

_STATUS_MAP: dict[str, AccountStatus] = {
    "A":   AccountStatus.ACTIVE,
    "F":   AccountStatus.FROZEN,
    "C":   AccountStatus.CLOSED,
    "I":   AccountStatus.DORMANT,   # Inactive → Dormant
    "D":   AccountStatus.DORMANT,
    "N":   AccountStatus.NPA,
}


class BaNCSCBSConnector(CBSConnector):
    def __init__(self, base_url: str, bank_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._bank_id = bank_id
        self._http = None
        self._ready = False

    def connect(self, http_client=None) -> None:
        if http_client is not None:
            self._http = http_client
        else:
            import httpx  # type: ignore[import]
            self._http = httpx.AsyncClient(timeout=10.0)
        self._ready = True
        log.info("cbs.bancs.connected", base_url=self._base_url, bank_id=self._bank_id)

    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}"
        try:
            response = await self._http.get(url)
            if response.status_code == 404:
                raise AccountNotFoundError(account_number)
            response.raise_for_status()
            data = response.json()
        except AccountNotFoundError:
            raise
        except Exception as exc:
            log.error("cbs.bancs.get_account_info.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"BaNCS get_account_info failed: {exc}") from exc

        raw_status = data.get("acctSts", "A")
        status = _STATUS_MAP.get(raw_status, AccountStatus.ACTIVE)
        account_hash = self._hash_account(account_number)

        return AccountInfo(
            account_number_hash=account_hash,
            account_number_last4=account_number[-4:],
            status=status,
            bank_id=bank_id,
            available_balance=data.get("avlBal"),
            currency=data.get("ccy", "INR"),
            cbs_account_id=data.get("acctId"),
        )

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/signatures"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.bancs.get_signatures.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"BaNCS get_signature_specimens failed: {exc}") from exc

        specimens = []
        for item in data.get("sigImages", []):
            img_b64 = item.get("imgData", "")
            if img_b64:
                specimens.append(base64.b64decode(img_b64))
        return specimens

    async def check_stop_payment(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> StopPaymentResult:
        self._assert_ready()
        url = (
            f"{self._base_url}/api/v1/accounts/{account_number}"
            f"/chequebook/{cheque_number}/stop-payment"
        )
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.bancs.check_stop_payment.failed",
                      account_last4=account_number[-4:], cheque=cheque_number, error=str(exc))
            raise CBSUnavailableError(f"BaNCS check_stop_payment failed: {exc}") from exc

        return StopPaymentResult(
            is_stopped=bool(data.get("spActive", False)),
            reason=data.get("spReason") or None,
            stopped_at=data.get("spDt") or None,
        )

    async def get_pps_entries(self, account_number: str, bank_id: str) -> list[PPSEntry]:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/positive-pay"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.bancs.get_pps_entries.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"BaNCS get_pps_entries failed: {exc}") from exc

        entries = []
        for raw in data.get("ppsList", []):
            entries.append(PPSEntry(
                cheque_series_start=str(raw.get("chqFrom", "")),
                cheque_series_end=str(raw.get("chqTo", "")),
                amount=float(raw.get("amt", 0.0)),
                is_active=raw.get("sts") == "A",
            ))
        return entries

    async def get_cheque_status(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> str:
        self._assert_ready()
        url = (
            f"{self._base_url}/api/v1/accounts/{account_number}"
            f"/chequebook/{cheque_number}"
        )
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.bancs.get_cheque_status.failed",
                      account_last4=account_number[-4:], cheque=cheque_number, error=str(exc))
            raise CBSUnavailableError(f"BaNCS get_cheque_status failed: {exc}") from exc

        return str(data.get("chqSts", "ACTIVE"))

    async def get_signatory_data(
        self,
        account_number: str,
        bank_id: str,
    ) -> list[CBSSignatoryData]:
        """
        Fetch authorized signatories with specimen images via BaNCS REST.

        BaNCS wraps all calls in {"request": {...}} / {"response": {...}}.
        Endpoint: POST /api/banking/v1/signatory/query
        Response: {"response": {"signatories": [{id, role, displayName, opType,
                                                  images: [{data: base64}]}]}}

        Raises CBSUnavailableError on network failure or error response.
        """
        self._assert_ready()
        url = f"{self._base_url}/api/banking/v1/signatory/query"
        payload = {
            "request": {
                "accountId": account_number,
                "bankId": bank_id,
            }
        }
        try:
            response = await self._http.post(url, json=payload)
            response.raise_for_status()
            outer = response.json()
            data = outer.get("response", {})
        except Exception as exc:
            log.error(
                "cbs.bancs.get_signatory_data.failed",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            raise CBSUnavailableError(f"BaNCS get_signatory_data failed: {exc}") from exc

        result: list[CBSSignatoryData] = []
        for sig in data.get("signatories", []):
            specimen_images: list[bytes] = []
            for img in sig.get("images", []):
                raw_b64 = img.get("data", "")
                if raw_b64:
                    specimen_images.append(base64.b64decode(raw_b64))
            result.append(CBSSignatoryData(
                signatory_id=str(sig.get("id", "")),
                role=str(sig.get("role", "")),
                name_masked=str(sig.get("displayName", "***")),
                specimen_images=specimen_images,
                operation_type=str(sig.get("opType", "J")),
            ))
        return result

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "BaNCSCBSConnector.connect() has not been called. "
                "Call it in the service startup before querying CBS."
            )
