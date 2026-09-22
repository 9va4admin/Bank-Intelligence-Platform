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


# ---------------------------------------------------------------------------
# Outward: submit_outward_lot / query_status_outward
#
# Real live-run bug: NGCHSubmissionWorkflow's submit_to_ngch/confirm_acknowledgement activities call
# these two methods, which existed on neither the dev stub nor the real NGCHAdapter — outward NGCH
# submission had never been exercised end to end. The dev stub auto-acknowledges (no async NGCH
# pipeline to simulate), matching every other dev stand-in's spirit of "just enough to complete
# end-to-end", and stays idempotent per lot_number.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_outward_lot_returns_a_reference(stub):
    ref = await stub.submit_outward_lot(bank_ifsc="KARB0000001", lot_number="LOT-1",
                                        file_path="cxf/LOT-1", cibf_file_path=None, checksum="abc")
    assert ref.startswith("NGCH-DEV-")


@pytest.mark.asyncio
async def test_submit_outward_lot_idempotent_per_lot(stub):
    ref1 = await stub.submit_outward_lot(bank_ifsc="KARB0000001", lot_number="LOT-1",
                                         file_path="cxf/LOT-1", cibf_file_path=None, checksum="abc")
    ref2 = await stub.submit_outward_lot(bank_ifsc="KARB0000001", lot_number="LOT-1",
                                         file_path="cxf/LOT-1", cibf_file_path=None, checksum="abc")
    assert ref1 == ref2


@pytest.mark.asyncio
async def test_query_status_outward_acknowledged_after_submit(stub):
    ref = await stub.submit_outward_lot(bank_ifsc="KARB0000001", lot_number="LOT-2",
                                        file_path="cxf/LOT-2", cibf_file_path=None, checksum="abc")
    ack = await stub.query_status_outward(reference=ref)
    assert ack.acknowledged is True and ack.reason is None


@pytest.mark.asyncio
async def test_query_status_outward_unknown_reference_not_acknowledged(stub):
    ack = await stub.query_status_outward(reference="NGCH-DEV-never-submitted")
    assert ack.acknowledged is False and ack.reason
