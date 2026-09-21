"""Outward accept must write ONE full cheque_instruments row (direction=OUTWARD) with lot + image keys, exactly once."""
import uuid
from datetime import date

import pytest

from modules.cts.workflows.activities.persist_outward_instrument import (
    PersistOutwardInstrumentInput, persist_outward_instrument_row, object_key_from_url,
)
from shared.utils.instrument_uuid import to_instrument_uuid

MICR = "⑆000787⑆⑈560229002⑈ 000000 10⑉"


class FakeConn:
    def __init__(self, existing=None):
        self.existing, self.executed, self.lot_calls = existing, [], 0

    async def fetchrow(self, sql, *a):
        if "FROM cts.cheque_instruments" in sql:
            return self.existing
        raise AssertionError(sql)

    async def execute(self, sql, *a):
        self.executed.append((sql, a))

    def transaction(self):
        class T:
            async def __aenter__(s): return s
            async def __aexit__(s, *e): return False
        return T()


def _inp(**kw):
    base = dict(bank_id="kbl", instrument_id="000787-0eec", scan_id="000787-0eec", bank_ifsc="KARB0000001",
                session_id="SES-1", branch_id="BR-1", pu_id="PU-1", micr_line=MICR, cheque_number="000787",
                amount_str="25000", cheque_date="2026-09-01", registered_drawee_ifsc="SBIN0000001",
                image_front_url="s3://astra-cts/scans/a_front.tif", image_rear_url="s3://astra-cts/scans/a_rear.tif",
                front_dpi=200)
    base.update(kw)
    return PersistOutwardInstrumentInput(**base)


def test_object_key_from_s3_and_http_urls():
    assert object_key_from_url("s3://astra-cts/scans/a.tif") == "scans/a.tif"
    assert object_key_from_url("http://localhost:19000/astra-cts/scans/a.tif?X-Amz=1") == "scans/a.tif"


@pytest.mark.asyncio
async def test_inserts_outward_row_with_lot_and_keys(monkeypatch):
    async def fake_lot(conn, **kw):
        return "LOT-1", 3
    monkeypatch.setattr("modules.cts.workflows.activities.persist_outward_instrument.ensure_open_lot", fake_lot)
    conn = FakeConn()
    res = await persist_outward_instrument_row(conn, _inp(), pepper="p", today=date(2026, 9, 21))
    assert res.lot_id == "LOT-1" and res.inserted is True
    assert res.instrument_uuid == str(to_instrument_uuid("kbl", "000787-0eec"))
    sql, args = conn.executed[0]
    assert "INSERT INTO cts.cheque_instruments" in sql and "'OUTWARD'" in sql
    assert "LOT-1" in args and "scans/a_front.tif" in args and "scans/a_rear.tif" in args
    assert 2500000 in args                       # paise
    assert date(2026, 9, 1) in args              # real date object, not str
    assert not any(a == "25000" for a in args)   # no raw amount string
    assert not any(isinstance(a, str) and "002" in a and len(a) > 20 and "560229002" not in a and a.isdigit() for a in args)


@pytest.mark.asyncio
async def test_retry_is_idempotent_and_does_not_reassign_lot(monkeypatch):
    called = []
    async def fake_lot(conn, **kw):
        called.append(1); return "LOT-2", 1
    monkeypatch.setattr("modules.cts.workflows.activities.persist_outward_instrument.ensure_open_lot", fake_lot)
    conn = FakeConn(existing={"lot_id": "LOT-1"})
    res = await persist_outward_instrument_row(conn, _inp(), pepper="p", today=date(2026, 9, 21))
    assert res.lot_id == "LOT-1" and res.inserted is False and not called and not conn.executed


@pytest.mark.asyncio
async def test_unparseable_micr_raises_not_silent():
    with pytest.raises(ValueError):
        await persist_outward_instrument_row(FakeConn(), _inp(micr_line="garbage"), pepper="p", today=date(2026, 9, 21))


@pytest.mark.asyncio
async def test_missing_date_raises(monkeypatch):
    with pytest.raises(ValueError):
        await persist_outward_instrument_row(FakeConn(), _inp(cheque_date=None), pepper="p", today=date(2026, 9, 21))
