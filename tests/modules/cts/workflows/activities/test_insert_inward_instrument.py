"""
insert_inward_instrument had no tests, and had never worked on a real database: it passed the cheque date as a string
for a DATE column, so asyncpg rejected every insert (found on the first live inward run, 2026-11-16). The IET deadline column is
double precision, so it stays a float. The fake connection below checks argument types the way asyncpg does.
"""
import contextlib
import datetime as dt

import pytest

from modules.cts.workflows.activities.insert_inward_instrument import (
    InsertInwardInstrumentInput, insert_inward_instrument,
)


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


def _inp(**kw):
    base = dict(bank_id="kbl", batch_id="B1", session_id="S1", item_seq_no="ITEM600001", iet_deadline=1_800_000_000.0,
                pps_flag="N", micr_line="600001033290062", drawee_ifsc="KARB0000001", drawee_account="4242424242",
                amount_paise=2_500_000, front_bw_key="k/f", back_bw_key="k/b", front_gray_key="k/g")
    base.update(kw)
    return InsertInwardInstrumentInput(**base)


@pytest.mark.asyncio
async def test_inserts_an_inward_row_and_returns_its_id():
    pool = _Pool()
    res = await insert_inward_instrument(_inp(), db_pool=pool)
    assert res.inserted is True and res.instrument_id
    assert "INSERT INTO cts.cheque_instruments" in pool.conn.calls[0][0]


@pytest.mark.asyncio
async def test_cheque_date_is_a_real_date_and_the_deadline_stays_a_float():
    pool = _Pool()
    await insert_inward_instrument(_inp(), db_pool=pool)
    args = pool.conn.calls[0][1]
    assert any(isinstance(a, dt.date) and not isinstance(a, dt.datetime) for a in args), "cheque_date must be a date object"
    assert not any(isinstance(a, str) and a == dt.date.today().isoformat() for a in args)
    assert 1_800_000_000.0 in args


@pytest.mark.asyncio
async def test_no_database_degrades_without_raising():
    res = await insert_inward_instrument(_inp(), db_pool=None)
    assert res.inserted is False and res.error == "DB_UNAVAILABLE"
