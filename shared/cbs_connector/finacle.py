"""
FinacleCBSConnector — Infosys Finacle Core Banking adapter.

Communicates with Finacle's REST/JSON API (Finacle 10.x+).
Older Finacle versions use a SOAP interface — handled by a separate adapter
not yet implemented (finacle_soap.py) for banks still on Finacle 7.x.

Status mapping from Finacle status strings → AccountStatus enum.
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
    "ACTIVE":   AccountStatus.ACTIVE,
    "FROZEN":   AccountStatus.FROZEN,
    "CLOSED":   AccountStatus.CLOSED,
    "DORMANT":  AccountStatus.DORMANT,
    "NPA":      AccountStatus.NPA,
    "INOPERATIVE": AccountStatus.DORMANT,
    "BLOCKED":  AccountStatus.FROZEN,
}


class FinacleCBSConnector(CBSConnector):
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
        log.info("cbs.finacle.connected", base_url=self._base_url, bank_id=self._bank_id)

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
            log.error("cbs.finacle.get_account_info.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"Finacle get_account_info failed: {exc}") from exc

        raw_status = data.get("status", "ACTIVE")
        status = _STATUS_MAP.get(raw_status, AccountStatus.ACTIVE)
        account_hash = self._hash_account(account_number)

        return AccountInfo(
            account_number_hash=account_hash,
            account_number_last4=account_number[-4:],
            status=status,
            bank_id=bank_id,
            available_balance=data.get("availableBalance"),
            currency=data.get("currency", "INR"),
            cbs_account_id=data.get("accountId"),
        )

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/signatures"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.finacle.get_signatures.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"Finacle get_signature_specimens failed: {exc}") from exc

        specimens = []
        for item in data.get("specimens", []):
            img_b64 = item.get("image", "")
            if img_b64:
                specimens.append(base64.b64decode(img_b64))
        return specimens

    async def check_stop_payment(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> StopPaymentResult:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/chequebook/{cheque_number}/stop-payment"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.finacle.check_stop_payment.failed",
                      account_last4=account_number[-4:], cheque=cheque_number, error=str(exc))
            raise CBSUnavailableError(f"Finacle check_stop_payment failed: {exc}") from exc

        return StopPaymentResult(
            is_stopped=bool(data.get("stopPayment", False)),
            reason=data.get("stopReason"),
            stopped_at=data.get("stoppedAt"),
        )

    async def get_pps_entries(self, account_number: str, bank_id: str) -> list[PPSEntry]:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/positive-pay"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.finacle.get_pps_entries.failed",
                      account_last4=account_number[-4:], error=str(exc))
            raise CBSUnavailableError(f"Finacle get_pps_entries failed: {exc}") from exc

        entries = []
        for raw in data.get("ppsEntries", []):
            entries.append(PPSEntry(
                cheque_series_start=str(raw.get("chequeSeriesStart", "")),
                cheque_series_end=str(raw.get("chequeSeriesEnd", "")),
                amount=float(raw.get("amount", 0.0)),
                is_active=bool(raw.get("isActive", False)),
            ))
        return entries

    async def get_cheque_status(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> str:
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/chequebook/{cheque_number}"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            log.error("cbs.finacle.get_cheque_status.failed",
                      account_last4=account_number[-4:], cheque=cheque_number, error=str(exc))
            raise CBSUnavailableError(f"Finacle get_cheque_status failed: {exc}") from exc

        return str(data.get("status", "ACTIVE"))

    async def get_signatory_data(
        self,
        account_number: str,
        bank_id: str,
    ) -> list[CBSSignatoryData]:
        """
        Fetch authorized signatories with their specimen images via Finacle REST.

        Endpoint: GET /api/v1/accounts/{account_number}/signatories
        Response: {"signatories": [{signatoryId, role, nameMasked, operationType,
                                    specimens: [{imageBase64}]}]}

        Raises AccountNotFoundError on 404.
        Raises CBSUnavailableError on any other failure.
        Images returned as decoded bytes — caller embeds immediately and discards.
        """
        self._assert_ready()
        url = f"{self._base_url}/api/v1/accounts/{account_number}/signatories"
        try:
            response = await self._http.get(url)
            if response.status_code == 404:
                raise AccountNotFoundError(f"Account {account_number[-4:]} not found in Finacle")
            response.raise_for_status()
            data = response.json()
        except AccountNotFoundError:
            raise
        except Exception as exc:
            log.error(
                "cbs.finacle.get_signatory_data.failed",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            raise CBSUnavailableError(f"Finacle get_signatory_data failed: {exc}") from exc

        result: list[CBSSignatoryData] = []
        for sig in data.get("signatories", []):
            specimen_images: list[bytes] = []
            for specimen in sig.get("specimens", []):
                raw_b64 = specimen.get("imageBase64", "")
                if raw_b64:
                    specimen_images.append(base64.b64decode(raw_b64))
            result.append(CBSSignatoryData(
                signatory_id=str(sig.get("signatoryId", "")),
                role=str(sig.get("role", "")),
                name_masked=str(sig.get("nameMasked", "***")),
                specimen_images=specimen_images,
                operation_type=str(sig.get("operationType", "J")),
            ))
        return result

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "FinacleCBSConnector.connect() has not been called. "
                "Call it in the service startup before querying CBS."
            )
