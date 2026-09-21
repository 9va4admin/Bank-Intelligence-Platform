"""update_lot_status must address the real cts.lots columns (lot_id, not lot_number)."""
import pytest
from modules.cts.workflows.activities.batch_endorsement_activities import UpdateLotStatusInput, update_lot_status


class Conn:
    def __init__(self): self.calls = []
    async def execute(self, sql, *a): self.calls.append((sql, a))


class Pool:
    def __init__(self): self.conn = Conn()
    def acquire(self):
        c = self.conn
        class A:
            async def __aenter__(s): return c
            async def __aexit__(s, *e): return False
        return A()


@pytest.mark.asyncio
async def test_updates_by_lot_id_with_existing_columns():
    pool = Pool()
    res = await update_lot_status(UpdateLotStatusInput(lot_number="LOT-1", bank_id="kbl", outcome="ENDORSED",
                                                       endorsed_count=3, failed_count=0), db_pool=pool)
    sql, args = pool.conn.calls[0]
    assert "lot_number" not in sql and "WHERE lot_id = $4" in sql
    assert args == ("ENDORSED", 3, 0, "LOT-1", "kbl") and res.updated is True
