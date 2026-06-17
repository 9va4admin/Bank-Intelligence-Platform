"""
FlexCubeCBSConnector — Oracle FlexCube Core Banking adapter (stub).

Full implementation follows the same pattern as FinacleCBSConnector.
FlexCube uses an XML/SOAP interface — this stub is present so the factory
can select it when cbs.connector.type = "flexcube".
"""
from shared.cbs_connector.base import AccountInfo, CBSConnector


class FlexCubeCBSConnector(CBSConnector):
    def __init__(self, base_url: str, bank_id: str) -> None:
        self._base_url = base_url
        self._bank_id = bank_id
        self._ready = False

    def connect(self, http_client=None) -> None:
        self._ready = True

    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        raise NotImplementedError("FlexCube adapter not yet implemented")

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        raise NotImplementedError("FlexCube adapter not yet implemented")
