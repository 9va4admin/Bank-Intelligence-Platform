"""
BaNCSCBSConnector — TCS BaNCS Core Banking adapter (stub).

Full implementation follows the same pattern as FinacleCBSConnector.
BaNCS uses a different REST API shape and different status string vocabulary.
This stub is present so that the factory in __init__.py can select it
at startup when cbs.connector.type = "bancs".
"""
from shared.cbs_connector.base import AccountInfo, AccountStatus, CBSConnector
from shared.cbs_connector.exceptions import CBSUnavailableError


class BaNCSCBSConnector(CBSConnector):
    def __init__(self, base_url: str, bank_id: str) -> None:
        self._base_url = base_url
        self._bank_id = bank_id
        self._ready = False

    def connect(self, http_client=None) -> None:
        import httpx  # type: ignore[import]
        self._http = http_client or httpx.AsyncClient(timeout=10.0)
        self._ready = True

    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def get_cheque_status(self, cheque_number: str, account_number: str, bank_id: str):
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def check_stop_payment(self, cheque_number: str, account_number: str, bank_id: str) -> bool:
        raise NotImplementedError("BaNCS adapter not yet implemented")

    async def get_pps_entries(self, account_number: str, bank_id: str) -> list:
        raise NotImplementedError("BaNCS adapter not yet implemented")
