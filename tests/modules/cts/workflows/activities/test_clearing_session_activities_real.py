"""Live-run defects in clearing session activities:
  1. seal_all_lots looked up lots by the API-invented random session_id — lots carry the SCANNER session_id, so
     the query always returned []. Real grouping key is (bank_id, clearing_date, pu_ids-derived branches).
  2. It selected status='SEALED', but endorsement moves lots to 'ENDORSED' — never matched a real lot.
  3. Nothing ever inserted the cts.clearing_sessions row, and it needs a center_id (FK to processing_centers,
     itself FK to clearing_zones) that is never created anywhere.
  4. update_session_status wrote npci_ack_ref/updated_at, which do not exist on cts.clearing_sessions
     (real columns: ngch_session_ref, no updated_at).
"""
from datetime import date

import pytest

from modules.cts.workflows.activities.clearing_session_activities import (
    SealAllLotsInput, seal_all_lots, UpdateSessionStatusInput, update_session_status,
)


class Conn:
    def __init__(self, lot_rows=None, zone_row=None, center_row=None):
        self.lot_rows = lot_rows or []
        self.zone_row, self.center_row = zone_row, center_row
        self.executed = []

    async def fetch(self, sql, *a):
        if "FROM cts.lots" in sql:
            return self.lot_rows
        return []

    async def fetchrow(self, sql, *a):
        if "FROM cts.clearing_zones" in sql:
            return self.zone_row
        if "FROM cts.processing_centers" in sql:
            return self.center_row
        return None

    async def execute(self, sql, *a):
        self.executed.append((sql, a))

    def transaction(self):
        class T:
            async def __aenter__(s): return s
            async def __aexit__(s, *e): return False
        return T()


class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self):
        c = self.conn
        class A:
            async def __aenter__(s): return c
            async def __aexit__(s, *e): return False
        return A()


def _lot_row(lot_id="LOT-1", pu_id="KBL-PU-01", routing_no="KARB", branch_ifsc="KARB0000001", zone="CHENNAI"):
    return {"lot_id": lot_id, "sequence_number": 1, "instrument_count": 3, "branch_id": "br-1",
            "branch_ifsc": branch_ifsc, "pu_id": pu_id, "routing_no": routing_no, "zone_id": zone}


@pytest.mark.asyncio
async def test_seal_all_lots_queries_by_bank_and_date_not_scanner_session_id():
    conn = Conn(lot_rows=[_lot_row()], zone_row={"zone_id": "CHENNAI"}, center_row={"center_id": "c-1"})
    res = await seal_all_lots(
        SealAllLotsInput(session_id="clearsess-abcd1234", bank_id="kbl", pu_ids=["KBL-PU-01"],
                         clearing_date="2026-09-21"),
        db_pool=Pool(conn),
    )
    assert res.status == "OK"
    assert res.sealed_lots == [{"lot_id": "LOT-1", "sequence_number": 1, "instrument_count": 3, "branch_id": "br-1",
                                "branch_ifsc": "KARB0000001", "pu_id": "KBL-PU-01", "routing_no": "KARB",
                                "zone_id": "CHENNAI"}]
    sql, args = conn.executed and conn.executed[-1] or (None, None)
    # a clearing_sessions row must be inserted, addressing a real center_id (not left null)
    insert_sql = [c for c in conn.executed if "INSERT INTO cts.clearing_sessions" in c[0]]
    assert insert_sql, "no INSERT into cts.clearing_sessions"
    assert "c-1" in insert_sql[0][1]
    assert res.session_uuid


@pytest.mark.asyncio
async def test_seal_all_lots_creates_zone_and_center_when_missing():
    conn = Conn(lot_rows=[_lot_row()], zone_row=None, center_row=None)
    await seal_all_lots(
        SealAllLotsInput(session_id="s", bank_id="kbl", pu_ids=["KBL-PU-01"], clearing_date="2026-09-21"),
        db_pool=Pool(conn),
    )
    assert any("INSERT INTO cts.clearing_zones" in c[0] for c in conn.executed)
    assert any("INSERT INTO cts.processing_centers" in c[0] for c in conn.executed)


@pytest.mark.asyncio
async def test_seal_all_lots_empty_pu_ids_means_all_pus_of_bank():
    conn = Conn(lot_rows=[_lot_row()], zone_row={"zone_id": "CHENNAI"}, center_row={"center_id": "c-1"})
    res = await seal_all_lots(
        SealAllLotsInput(session_id="s", bank_id="kbl", pu_ids=[], clearing_date="2026-09-21"),
        db_pool=Pool(conn),
    )
    assert res.sealed_lots


@pytest.mark.asyncio
async def test_update_session_status_writes_real_columns():
    conn = Conn()
    res = await update_session_status(
        UpdateSessionStatusInput(session_id="sess-uuid-1", bank_id="kbl", status="SUBMITTED",
                                 npci_ack_ref="NGCH-REF-1"),
        db_pool=Pool(conn),
    )
    sql, args = conn.executed[0]
    assert "ngch_session_ref" in sql and "npci_ack_ref" not in sql and "updated_at" not in sql
    assert args == ("SUBMITTED", "NGCH-REF-1", None, "sess-uuid-1", "kbl")
    assert res.updated is True
