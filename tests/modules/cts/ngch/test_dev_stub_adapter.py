"""DevStubNGCHAdapter — DEV/TEST stand-in for NGCH (there is no NPCI sandbox here).
Same file_decision/query_status contract as NGCHAdapter, including exactly-once:
a repeated workflow_id raises DuplicateFilingError. Refuses outside development."""
import pytest

from modules.cts.mcp.ngch_adapter import DuplicateFilingError


@pytest.fixture
def stub(monkeypatch):
    from modules.cts.mcp.dev_stub_ngch import DevStubNGCHAdapter
    monkeypatch.setenv("ASTRA_ENV", "development")
    a = DevStubNGCHAdapter(bank_id="kbl")
    a.connect()
    return a


@pytest.mark.asyncio
async def test_files_confirm_and_returns_ack(stub):
    r = await stub.file_decision("i1", "CONFIRM", "wf-1")
    assert r["acknowledgement_id"].startswith("DEVSTUB-") and r["status"] == "ACCEPTED"


@pytest.mark.asyncio
async def test_same_workflow_id_is_duplicate(stub):
    await stub.file_decision("i1", "RETURN", "wf-1")
    with pytest.raises(DuplicateFilingError):
        await stub.file_decision("i1", "RETURN", "wf-1")


@pytest.mark.asyncio
async def test_invalid_decision_rejected(stub):
    with pytest.raises(ValueError):
        await stub.file_decision("i1", "MAYBE", "wf-2")


@pytest.mark.asyncio
async def test_query_status_reflects_filing(stub):
    await stub.file_decision("i9", "CONFIRM", "wf-9")
    assert (await stub.query_status("i9"))["decision"] == "CONFIRM"


def test_refuses_outside_development(monkeypatch):
    from modules.cts.mcp.dev_stub_ngch import DevStubNGCHAdapter
    monkeypatch.setenv("ASTRA_ENV", "production")
    with pytest.raises(RuntimeError, match="development"):
        DevStubNGCHAdapter(bank_id="kbl").connect()
