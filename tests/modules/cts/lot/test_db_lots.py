from datetime import date
import pytest
from modules.cts.lot.db_lots import ensure_open_lot


class Conn:
    def __init__(self, open_row=None):
        self.open_row, self.ex = open_row, []
    async def fetchrow(self, sql, *a):
        if "status = 'OPEN'" in sql: return self.open_row
        return {"max_seq": 0}
    async def execute(self, sql, *a): self.ex.append((sql, a))


@pytest.mark.asyncio
async def test_creates_first_lot():
    c = Conn()
    lot, n = await ensure_open_lot(c, bank_id="kbl", branch_id="B", session_id="S", clearing_date=date(2026, 9, 21))
    assert lot == "LOT-B-20260921-0001" and n == 1 and "INSERT INTO cts.lots" in c.ex[0][0]


@pytest.mark.asyncio
async def test_increments_open_lot():
    c = Conn({"lot_id": "L1", "instrument_count": 4, "max_instruments": 25})
    lot, n = await ensure_open_lot(c, bank_id="kbl", branch_id="B", session_id="S", clearing_date=date(2026, 9, 21))
    assert (lot, n) == ("L1", 5)
