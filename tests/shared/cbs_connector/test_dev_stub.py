"""DevStubCBSConnector — clearly-labelled dev/test stand-in for a real CBS.

Not a bank integration: it serves seeded fixture data so the full inward
pipeline can run without a Finacle/BaNCS/FlexCube. Refuses to start outside
ASTRA_ENV=development so it can never front a production bank.
"""
import json
import pytest

from shared.cbs_connector.exceptions import AccountNotFoundError

DATA = {
    "accounts": {
        "111": {"status": "ACTIVE", "balance": 50000.0},
        "222": {"status": "FROZEN", "balance": 10.0},
    },
    "stopped_cheques": {"111": ["000777"]},
}


@pytest.fixture
def stub(tmp_path, monkeypatch):
    from shared.cbs_connector.dev_stub import DevStubCBSConnector
    monkeypatch.setenv("ASTRA_ENV", "development")
    f = tmp_path / "cbs.json"
    f.write_text(json.dumps(DATA))
    c = DevStubCBSConnector(base_url=str(f), bank_id="kbl", pepper="test-pepper")
    c.connect()
    return c


@pytest.mark.asyncio
async def test_account_info_active_with_balance(stub):
    info = await stub.get_account_info("111", "kbl")
    assert info.status.value == "ACTIVE" and info.available_balance == 50000.0
    assert info.account_number_last4 == "111"


@pytest.mark.asyncio
async def test_frozen_account_reported_frozen(stub):
    assert (await stub.get_account_info("222", "kbl")).status.value == "FROZEN"


@pytest.mark.asyncio
async def test_unknown_account_raises_not_found(stub):
    with pytest.raises(AccountNotFoundError):
        await stub.get_account_info("999", "kbl")


@pytest.mark.asyncio
async def test_stop_payment_hit_and_miss(stub):
    assert (await stub.check_stop_payment("111", "000777", "kbl")).is_stopped is True
    assert (await stub.check_stop_payment("111", "000778", "kbl")).is_stopped is False


def test_refuses_outside_development(tmp_path, monkeypatch):
    from shared.cbs_connector.dev_stub import DevStubCBSConnector
    monkeypatch.setenv("ASTRA_ENV", "production")
    f = tmp_path / "c.json"; f.write_text("{}")
    with pytest.raises(RuntimeError, match="development"):
        DevStubCBSConnector(base_url=str(f), bank_id="kbl", pepper="p").connect()
