"""Custody of original instruments: kept at the branch for a while, handed over (a batch, with a courier reference), received
at central storage by a different person, kept to the end of the retention period, then disposed of. Everything about timing is
bank configuration; the original is never the system's to lose: items missing at receipt are flagged, not forgotten."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import Role

BANK = "kbl"
CFG = {"custody_branch_hold_days": 7, "custody_retention_years": 10}


class FakeDb:
    """Just enough of the database: accepted outward items, custody rows, handovers, events."""

    def __init__(self, accepted):
        self.accepted = accepted                       # {instrument_id: (branch_id, age_days)}
        self.custody, self.handovers, self.events = {}, {}, []

    def acquire(self):
        db = self

        class A:
            async def __aenter__(s): return db
            async def __aexit__(s, *x): return False
        return A()

    def transaction(self):
        class T:
            async def __aenter__(s): return s
            async def __aexit__(s, *x): return False
        return T()

    async def fetch(self, sql, *a):
        from apps.api.routers import cts_custody as C
        if sql == C.SQL_PENDING:
            branch = a[1]
            return [{"instrument_id": i, "cheque_number": i, "branch_id": b, "amount_range": "r", "payee_display": "P***",
                     "captured_at": "t", "age_days": age}
                    for i, (b, age) in self.accepted.items() if i not in self.custody and (branch is None or b == branch)]
        if sql == C.SQL_ELIGIBLE:
            return [{"instrument_id": i} for i in a[2] if i in self.accepted and self.accepted[i][0] == a[1] and i not in self.custody]
        if sql == C.SQL_HANDOVERS:
            return [dict(h, handover_id=k) for k, h in self.handovers.items() if a[1] is None or h["status"] == a[1]]
        if sql == C.SQL_HANDOVER_ITEMS:
            return [{"instrument_id": i} for i, c in self.custody.items() if c.get("handover_id") == a[1]]
        if sql == C.SQL_DUE:
            return [dict(c, instrument_id=i) for i, c in self.custody.items()
                    if c["status"] == "STORED" and c["retention_until"] <= date.today()]
        if sql == C.SQL_HISTORY:
            return [e for e in self.events if e["instrument_id"] == a[1]]
        raise AssertionError("unexpected fetch: " + sql[:70])

    async def fetchrow(self, sql, *a):
        from apps.api.routers import cts_custody as C
        if sql == C.SQL_HANDOVER_ONE:
            h = self.handovers.get(a[1]); return dict(h, handover_id=a[1]) if h else None
        if sql == C.SQL_CUSTODY_ONE:
            c = self.custody.get(a[1]); return dict(c, instrument_id=a[1]) if c else None
        raise AssertionError("unexpected fetchrow: " + sql[:70])

    async def execute(self, sql, *a):
        from apps.api.routers import cts_custody as C
        if sql == C.SQL_INSERT_HANDOVER:
            _, hid, branch, courier, notes, n, who = a
            self.handovers[hid] = {"branch_id": branch, "status": "IN_TRANSIT", "courier_ref": courier, "notes": notes,
                                   "item_count": n, "created_by": who, "created_at": "t", "received_by": None, "received_at": None}
            return "INSERT 0 1"
        if sql == C.SQL_INSERT_CUSTODY:
            _, iid, branch, hid = a
            self.custody[iid] = {"branch_id": branch, "status": "IN_TRANSIT", "handover_id": hid, "location": None,
                                 "retention_until": None}
            return "INSERT 0 1"
        if sql == C.SQL_RECEIVE_ITEM:
            _, iid, who, location, years = a
            self.custody[iid].update(status="STORED", location=location, received_by=who,
                                     retention_until=date.today() + timedelta(days=365 * years))
            return "UPDATE 1"
        if sql == C.SQL_MISSING_ITEM:
            self.custody[a[1]]["status"] = "MISSING"; return "UPDATE 1"
        if sql == C.SQL_RECEIVE_HANDOVER:
            _, hid, status_, who, notes = a
            if self.handovers[hid]["status"] != "IN_TRANSIT":
                return "UPDATE 0"
            self.handovers[hid].update(status=status_, received_by=who); return "UPDATE 1"
        if sql == C.SQL_DISPOSE:
            _, iid, who = a
            c = self.custody.get(iid)
            if not c or c["status"] != "STORED" or c["retention_until"] > date.today():
                return "UPDATE 0"
            c["status"] = "DISPOSED"; return "UPDATE 1"
        if sql == C.SQL_EVENT:
            self.events.append({"instrument_id": a[1], "event": a[3], "actor": a[4]}); return "INSERT 0 1"
        raise AssertionError("unexpected execute: " + sql[:70])


def _client(user, db, role="ops_manager", branch_ids=(), cfg=CFG):
    from apps.api.routers import cts_custody
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI(); app.include_router(cts_custody.router_v1)
    ctx = MagicMock(); ctx.role = Role[role.upper()]; ctx.bank_id = BANK; ctx.user_id = user
    ctx.branch_ids = list(branch_ids); ctx.branch_code = None
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.db_pool_cts = db
    cs = AsyncMock(); cs.get_cts_config.return_value = cfg
    app.state.config_service = cs
    return TestClient(app, raise_server_exceptions=False)


def _db():
    return FakeDb({"I1": ("B1", 2.0), "I2": ("B1", 9.0), "I3": ("B2", 1.0)})


def test_accepted_items_still_at_the_branch_are_listed_and_the_late_ones_flagged():
    items = {i["instrument_id"]: i for i in _client("mgr", _db()).get("/v1/cts/custody/pending").json()["items"]}
    assert set(items) == {"I1", "I2", "I3"}
    assert items["I2"]["overdue"] is True and items["I1"]["overdue"] is False         # held longer than custody_branch_hold_days


def test_branch_staff_see_and_hand_over_only_their_own_branch():
    db = _db()
    c = _client("b1", db, role="ops_reviewer", branch_ids=["B1"])
    assert {i["instrument_id"] for i in c.get("/v1/cts/custody/pending").json()["items"]} == {"I1", "I2"}
    assert c.post("/v1/cts/custody/handovers", json={"branch_id": "B2", "instrument_ids": ["I3"]}).status_code == 403


def test_central_staff_cannot_hand_over_from_a_branch():
    c = _client("central", _db(), role="ops_reviewer")                                 # no branches: central staff
    assert c.get("/v1/cts/custody/pending").status_code == 403
    assert c.post("/v1/cts/custody/handovers", json={"branch_id": "B1", "instrument_ids": ["I1"]}).status_code == 403


def test_a_handover_moves_the_items_in_transit_and_they_leave_the_pending_list():
    db = _db()
    r = _client("b1", db, role="ops_reviewer", branch_ids=["B1"]).post(
        "/v1/cts/custody/handovers", json={"branch_id": "B1", "instrument_ids": ["I1", "I2"], "courier_ref": "AWB-77"})
    assert r.status_code == 201 and r.json()["item_count"] == 2 and r.json()["status"] == "IN_TRANSIT"
    assert db.custody["I1"]["status"] == "IN_TRANSIT" and {e["event"] for e in db.events} == {"HANDED_OVER"}
    assert {i["instrument_id"] for i in _client("mgr", db).get("/v1/cts/custody/pending").json()["items"]} == {"I3"}


def test_an_item_that_is_not_an_accepted_item_of_that_branch_is_refused_and_nothing_is_recorded():
    db = _db()
    r = _client("b1", db, role="ops_reviewer", branch_ids=["B1"]).post(
        "/v1/cts/custody/handovers", json={"branch_id": "B1", "instrument_ids": ["I1", "I3", "GHOST"]})
    assert r.status_code == 422 and db.handovers == {} and db.custody == {}


def _handed_over(db, items=("I1", "I2")):
    r = _client("b1", db, role="ops_reviewer", branch_ids=["B1"]).post(
        "/v1/cts/custody/handovers", json={"branch_id": "B1", "instrument_ids": list(items)})
    return r.json()["handover_id"]


def test_central_storage_receives_the_batch_and_the_retention_period_starts():
    db = _db(); hid = _handed_over(db)
    r = _client("store", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-12"})
    assert r.status_code == 200 and r.json()["status"] == "RECEIVED"
    assert db.custody["I1"]["status"] == "STORED" and db.custody["I1"]["location"] == "BOX-12"
    assert db.custody["I1"]["retention_until"] > date.today() + timedelta(days=365 * 9)         # custody_retention_years = 10


def test_the_person_who_sent_the_batch_cannot_receive_it():
    db = _db(); hid = _handed_over(db)
    assert _client("b1", db, role="ops_manager").post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "X"}).status_code == 403


def test_an_item_not_in_the_box_is_flagged_missing_and_the_handover_is_a_discrepancy():
    db = _db(); hid = _handed_over(db)
    r = _client("store", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-12", "received_ids": ["I1"]})
    assert r.status_code == 200 and r.json()["status"] == "DISCREPANCY" and r.json()["missing"] == ["I2"]
    assert db.custody["I2"]["status"] == "MISSING" and db.custody["I1"]["status"] == "STORED"


def test_a_batch_can_only_be_received_once():
    db = _db(); hid = _handed_over(db)
    _client("store", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-12"})
    assert _client("store2", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-13"}).status_code == 409


def test_in_transit_batches_can_be_listed_for_the_receiving_team():
    db = _db(); _handed_over(db)
    rows = _client("store", db).get("/v1/cts/custody/handovers?status=IN_TRANSIT").json()["handovers"]
    assert len(rows) == 1 and rows[0]["item_count"] == 2


def test_nothing_is_disposed_before_its_retention_ends_and_only_a_manager_may_dispose():
    db = _db(); hid = _handed_over(db)
    _client("store", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-12"})
    assert _client("mgr", db).post("/v1/cts/custody/instruments/I1/dispose", json={"reason": "retention over"}).status_code == 409
    db.custody["I1"]["retention_until"] = date.today() - timedelta(days=1)                       # retention is over
    assert _client("rev", db, role="ops_reviewer").post("/v1/cts/custody/instruments/I1/dispose", json={"reason": "x"}).status_code == 403
    assert [i["instrument_id"] for i in _client("mgr", db).get("/v1/cts/custody/due-for-disposal").json()["items"]] == ["I1"]
    assert _client("mgr", db).post("/v1/cts/custody/instruments/I1/dispose", json={"reason": "retention over"}).status_code == 200
    assert db.custody["I1"]["status"] == "DISPOSED"


def test_an_instruments_history_lists_every_step():
    db = _db(); hid = _handed_over(db)
    _client("store", db).post(f"/v1/cts/custody/handovers/{hid}/receive", json={"location": "BOX-12"})
    events = _client("mgr", db).get("/v1/cts/custody/instruments/I1/history").json()["events"]
    assert [e["event"] for e in events] == ["HANDED_OVER", "RECEIVED"]
