"""AccountInfo carries the account type used to put a cheque in the CA or IP bucket."""
import json

import pytest

from shared.cbs_connector.base import AccountInfo, AccountStatus
from shared.cbs_connector.dev_stub import DevStubCBSConnector


def test_account_type_is_optional_and_defaults_to_none():
    info = AccountInfo(account_number_hash="h", account_number_last4="1234", status=AccountStatus.ACTIVE, bank_id="kbl")
    assert info.account_type is None
    assert AccountInfo(account_number_hash="h", account_number_last4="1234", status=AccountStatus.ACTIVE,
                       bank_id="kbl", account_type="CORPORATE").account_type == "CORPORATE"


@pytest.mark.asyncio
async def test_dev_stub_serves_the_account_type_from_its_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_ENV", "development")
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({"accounts": {"1111222233": {"status": "ACTIVE", "holder": "ACME LTD", "account_type": "CORPORATE"},
                                              "9999888877": {"status": "ACTIVE", "holder": "A PERSON"}}}), encoding="utf-8")
    cbs = DevStubCBSConnector(base_url=str(path), bank_id="kbl", pepper="p")
    cbs.connect()
    assert (await cbs.get_account_info("1111222233", "kbl")).account_type == "CORPORATE"
    assert (await cbs.get_account_info("9999888877", "kbl")).account_type is None
