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


# ---------------------------------------------------------------------------
# Session reconciliation: fetch_settlement_report / submit_representation
#
# Real gap found reading the outward pipeline end to end: SessionReconciliationWorkflow calls
# fetch_ngch_settlement_report -> ngch_client.fetch_settlement_report, which existed on neither
# adapter — session reconciliation and RRF generation had never run at all. Same "no real NGCH
# sandbox to simulate" dev-stub philosophy as submit_outward_lot: auto-acknowledge every
# instrument this same stub already accepted for the session (looked up for real off
# cts.clearing_sessions / cts.cheque_instruments) as SETTLED.
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, session_row, instrument_rows):
        self._session_row = session_row
        self._instrument_rows = instrument_rows

    async def fetchrow(self, query, *args):
        return self._session_row

    async def fetch(self, query, *args):
        return self._instrument_rows


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeDbPool:
    def __init__(self, session_row=None, instrument_rows=None):
        self._conn = _FakeConn(session_row, instrument_rows or [])

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


@pytest.mark.asyncio
async def test_fetch_settlement_report_no_db_pool_returns_empty(stub):
    rows = await stub.fetch_settlement_report(
        session_id="16e423fa-d334-5a6c-b368-6e0d87e12bae",
        clearing_date="2026-09-22", bank_ifsc="KARB0000001",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_settlement_report_unknown_session_returns_empty(monkeypatch):
    from modules.cts.mcp.dev_stub_ngch import DevStubNGCHAdapter
    monkeypatch.setenv("ASTRA_ENV", "development")
    a = DevStubNGCHAdapter(bank_id="kbl", db_pool=_FakeDbPool(session_row=None))
    a.connect()
    rows = await a.fetch_settlement_report(
        session_id="16e423fa-d334-5a6c-b368-6e0d87e12bae",
        clearing_date="2026-09-22", bank_ifsc="KARB0000001",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_settlement_report_reports_matched_instruments_settled(monkeypatch):
    from modules.cts.mcp.dev_stub_ngch import DevStubNGCHAdapter
    monkeypatch.setenv("ASTRA_ENV", "development")
    session_row = {"ngch_session_ref": "NGCH-DEV-E18F3FE7D8F65619"}
    instrument_rows = [{"instrument_id": "aaaaaaaa-0000-0000-0000-000000000001"},
                       {"instrument_id": "aaaaaaaa-0000-0000-0000-000000000002"}]
    a = DevStubNGCHAdapter(
        bank_id="kbl",
        db_pool=_FakeDbPool(session_row=session_row, instrument_rows=instrument_rows),
    )
    a.connect()
    rows = await a.fetch_settlement_report(
        session_id="16e423fa-d334-5a6c-b368-6e0d87e12bae",
        clearing_date="2026-09-22", bank_ifsc="KARB0000001",
    )
    assert len(rows) == 2
    assert all(r["status"] == "SETTLED" for r in rows)
    assert {r["instrument_id"] for r in rows} == {
        "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002",
    }


@pytest.mark.asyncio
async def test_submit_representation_returns_a_reference(stub):
    ref = await stub.submit_representation(
        instrument_id="i1", bank_ifsc="KARB0000001",
        return_reason_code="RETURN_INSUFFICIENT_FUNDS", original_session_id="sess-1",
    )
    assert ref.startswith("NGCH-DEV-REP-")


@pytest.mark.asyncio
async def test_submit_representation_idempotent_per_instrument(stub):
    ref1 = await stub.submit_representation(
        instrument_id="i1", bank_ifsc="KARB0000001",
        return_reason_code="RETURN_INSUFFICIENT_FUNDS", original_session_id="sess-1",
    )
    ref2 = await stub.submit_representation(
        instrument_id="i1", bank_ifsc="KARB0000001",
        return_reason_code="RETURN_INSUFFICIENT_FUNDS", original_session_id="sess-1",
    )
    assert ref1 == ref2
