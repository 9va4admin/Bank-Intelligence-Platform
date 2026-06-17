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

from shared.cbs_connector.base import AccountInfo, AccountStatus, CBSConnector
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

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "FinacleCBSConnector.connect() has not been called. "
                "Call it in the service startup before querying CBS."
            )
