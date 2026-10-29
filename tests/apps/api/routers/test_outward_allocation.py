"""Outward held items use the same allocation as inward: a reviewer holds an item while deciding, AUTO mode assigns on poll,
the maker's decision releases the item for a checker (never the maker), and a staged decision no checker takes in time is
filed on the maker's word."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.cts.allocation.lock_service import LockService
from shared.auth.rbac import Role
from tests.modules.cts.allocation.fake_redis import FakeRedis

BANK = "kbl"
CFG = {"maker_checker_enabled": True, "allocation_mode": "AUTO", "allocation_lock_ttl_minutes": 10,
       "allocation_max_per_reviewer": 0, "checker_review_timeout_minutes": 15}
BODY = {"action": "CONFIRMED", "reason": "fields match", "reason_category": "manual"}


def run(coro):
    return asyncio.run(coro)


class FakeDb:
    def __init__(self, held=(), pu_of=None):
        self.held = [dict(instrument_id=i, cheque_number=i, account_display="****", payee_display="P***", amount_range="r",
                          status="MISMATCH_HELD", fraud_score=None, ocr_confidence=None, review_reason="x", pu_id=(pu_of or {}).get(i, "PU-1"),
                          received_at="t", branch_id="b", lot_id=None, instrument_category="CHEQUE") for i in held]
        self.stage, self.updates = {}, []

    def acquire(self):
        db = self

        class A:
            async def __aenter__(s): return db
            async def __aexit__(s, *x): return False
        return A()

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO cts.outward_review_stage"):
            _, iid, maker, decision, reason = args
            if iid in self.stage:
                return "INSERT 0 0"
            self.stage[iid] = {"maker_id": maker, "maker_decision": decision, "maker_reason": reason, "status": "MAKER_DECIDED",
                               "age_seconds": 0.0}
            return "INSERT 0 1"
        if s.startswith("UPDATE cts.outward_review_stage"):
            row = self.stage.get(args[1])
            if not row or row["status"] != "MAKER_DECIDED":
                return "UPDATE 0"
            row["status"] = "FINAL"; row["checker_id"] = args[2]
            return "UPDATE 1"
        if s.startswith("UPDATE cts.cheque_instruments"):
            self.updates.append(args)
        return "OK"

    async def fetchrow(self, sql, *args):
        if "cts.branches" in sql and "outward_scan_events" in sql:          # the PU of an instrument, through its branch
            row = next((r for r in self.held if r["instrument_id"] == args[1]), None)
            return {"pu_id": row["pu_id"]} if row else None
        if "FROM cts.outward_review_stage" in sql:
            row = self.stage.get(args[1])
            return dict(row, instrument_id=args[1]) if row and row["status"] == "MAKER_DECIDED" else None
        return None

    async def fetch(self, sql, *args):
        if "LEFT JOIN cts.outward_scan_events" in sql:
            return [dict(v, instrument_id=k, cheque_number="C", payee_display="P***", amount_range="r", review_reason="r",
                         branch_id="b", lot_id=None, instrument_category="CHEQUE", made_at="2026-10-28T10:00:00",
                         pu_id=next((h["pu_id"] for h in self.held if h["instrument_id"] == k), None))
                    for k, v in self.stage.items() if v["status"] == "MAKER_DECIDED"]
        if "FROM cts.outward_scan_events" in sql:
            staged = {k for k, v in self.stage.items()}
            return [r for r in self.held if r["instrument_id"] not in staged]
        return []


def _client(user, db, redis, cfg=CFG, role="ops_reviewer", pu_ids=()):
    from apps.api.routers import cts_outward_data
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI(); app.include_router(cts_outward_data.router_v1)
    ctx = MagicMock(); ctx.role = Role[role.upper()]; ctx.bank_id = BANK; ctx.user_id = user; ctx.pu_ids = list(pu_ids)
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.db_pool_cts = db
    app.state.redis_cts = redis
    cs = AsyncMock(); cs.get_cts_config.return_value = cfg
    app.state.config_service = cs
    return TestClient(app, raise_server_exceptions=False)


def _queue(c):
    return {i["instrument_id"]: i for i in c.get("/v1/cts/outward/human-review-queue").json()["items"]}


def _lock(redis, iid, who):
    return run(LockService(redis).acquire_lock(iid, who, CFG))


def _holder(redis, iid):
    return run(LockService(redis).get_lock_holder(iid))


def test_the_queue_says_who_holds_each_item_and_which_are_mine():
    redis, db = FakeRedis(), FakeDb(held=["A1", "A2"])
    _lock(redis, "A1", "maker"); _lock(redis, "A2", "someone")
    rows = _queue(_client("maker", db, redis, cfg={**CFG, "allocation_mode": "SELF"}))
    assert rows["A1"]["assigned_to_me"] is True and rows["A2"]["assigned_to_me"] is False and rows["A2"]["assigned_to"] == "someone"


def test_auto_mode_assigns_unassigned_items_to_the_reviewers_who_are_active():
    redis, db = FakeRedis(), FakeDb(held=["A1", "A2", "A3", "A4"])
    for who in ("r1", "r2"):
        run(LockService(redis).heartbeat_reviewer(BANK, who))
    rows = _queue(_client("r1", db, redis))
    owners = {rows[i]["assigned_to"] for i in rows}
    assert owners == {"r1", "r2"}                       # least-loaded spreads the work over both


def test_self_mode_leaves_items_for_reviewers_to_claim():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    rows = _queue(_client("r1", db, redis, cfg={**CFG, "allocation_mode": "SELF"}))
    assert rows["A1"]["assigned_to"] is None


def test_a_reviewer_cannot_decide_an_item_another_reviewer_holds():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    _lock(redis, "A1", "someone")
    r = _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    assert r.status_code == 409 and "someone" not in r.text and db.stage == {}


def test_deciding_takes_the_item_and_the_makers_decision_releases_it_for_a_checker():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    r = _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    assert r.status_code == 200 and db.stage["A1"]["maker_id"] == "maker"
    assert _holder(redis, "A1") is None


def test_a_checker_cannot_validate_an_item_another_checker_holds_and_validating_releases_it():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    _lock(redis, "A1", "checker-2")
    assert _client("checker-1", db, redis).post("/v1/cts/outward/review/A1/validate", json=BODY).status_code == 409
    run(LockService(redis).release_lock("A1", "checker-2"))
    assert _client("checker-1", db, redis).post("/v1/cts/outward/review/A1/validate", json=BODY).status_code == 200
    assert _holder(redis, "A1") is None and db.stage["A1"]["status"] == "FINAL"


def test_the_validation_queue_assigns_checkers_but_never_the_maker():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    for who in ("maker", "checker"):
        run(LockService(redis).heartbeat_reviewer(BANK, who))
    rows = {i["instrument_id"]: i for i in _client("checker", db, redis).get("/v1/cts/outward/validation-queue").json()["items"]}
    assert rows["A1"]["assigned_to"] == "checker" and rows["A1"]["assigned_to_me"] is True


def test_a_staged_decision_no_checker_takes_in_time_is_filed_on_the_makers_word():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    db.stage["A1"]["age_seconds"] = 16 * 60.0                    # older than checker_review_timeout_minutes (15)
    rows = _client("checker", db, redis).get("/v1/cts/outward/validation-queue").json()["items"]
    assert rows == [] and db.stage["A1"]["status"] == "FINAL" and db.stage["A1"]["checker_id"] == "SYSTEM"
    assert db.updates and db.updates[0][0] == "STP_CONFIRM"       # the maker's CONFIRMED was filed


def test_a_staged_decision_within_the_timeout_is_left_for_a_checker():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    _client("maker", db, redis).post("/v1/cts/outward/review/A1/decide", json=BODY)
    db.stage["A1"]["age_seconds"] = 5 * 60.0
    rows = _client("checker", db, redis).get("/v1/cts/outward/validation-queue").json()["items"]
    assert len(rows) == 1 and db.stage["A1"]["status"] == "MAKER_DECIDED"


# --- processing unit and the session cut-off ------------------------------------------------------------------------------

def _cutoff_in(minutes):
    """A cfg whose only cut-off is `minutes` from now (local time), so tests do not depend on the wall clock."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    t = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(minutes=minutes)
    return {**CFG, "outward_session_cutoffs": [f"{t.hour:02d}:{t.minute:02d}"], "outward_session_timezone": "Asia/Kolkata",
            "outward_cutoff_guard_minutes": 10}


def test_queue_items_carry_their_pu_and_the_time_the_session_closes():
    import time
    redis, db = FakeRedis(), FakeDb(held=["A1"], pu_of={"A1": "PU-9"})
    cfg = _cutoff_in(120)
    row = _queue(_client("r1", db, redis, cfg={**cfg, "allocation_mode": "SELF"}))["A1"]
    assert row["pu_id"] == "PU-9" and 100 * 60 < row["due_at"] - time.time() <= 121 * 60


def test_the_allocation_record_remembers_the_pu_and_the_deadline():
    redis, db = FakeRedis(), FakeDb(held=["A1"], pu_of={"A1": "PU-9"})
    _queue(_client("r1", db, redis, cfg=_cutoff_in(120)))
    meta = run(LockService(redis).get_item_meta(BANK, "A1"))
    assert meta["pu_id"] == "PU-9" and meta["iet_deadline"] > 0


def test_a_reviewer_scoped_to_another_pu_is_not_given_the_item_and_cannot_decide_it():
    redis, db = FakeRedis(), FakeDb(held=["A1"], pu_of={"A1": "PU-1"})
    run(LockService(redis).heartbeat_reviewer(BANK, "other", pu_ids=["PU-2"]))
    rows = _queue(_client("other", db, redis, pu_ids=["PU-2"]))
    assert rows["A1"]["assigned_to"] is None                         # AUTO assignment respects the PU scope
    r = _client("other", db, redis, pu_ids=["PU-2"]).post("/v1/cts/outward/review/A1/decide", json=BODY)
    assert r.status_code == 403 and db.stage == {}


def test_a_reviewer_scoped_to_the_items_pu_may_decide_and_all_may_decide_anything():
    redis, db = FakeRedis(), FakeDb(held=["A1", "A2"], pu_of={"A1": "PU-1", "A2": "PU-1"})
    assert _client("r1", db, redis, pu_ids=["PU-1"]).post("/v1/cts/outward/review/A1/decide", json=BODY).status_code == 200
    assert _client("r2", db, redis, pu_ids=["ALL"]).post("/v1/cts/outward/review/A2/decide", json=BODY).status_code == 200


def test_an_item_close_to_the_cutoff_is_assigned_even_when_everyone_is_at_the_cap():
    redis, db = FakeRedis(), FakeDb(held=["BUSY", "URGENT"])
    run(LockService(redis).heartbeat_reviewer(BANK, "r1"))
    _lock(redis, "BUSY", "r1")
    cfg = {**_cutoff_in(5), "allocation_max_per_reviewer": 1, "allocation_urgent_margin_minutes": 30}
    rows = _queue(_client("r1", db, redis, cfg=cfg))
    assert rows["URGENT"]["assigned_to"] == "r1"


def test_a_staged_decision_is_filed_shortly_before_the_cutoff_even_though_the_checker_timeout_has_not_passed():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    cfg = _cutoff_in(5)                                               # 5 minutes left, guard is 10
    _client("maker", db, redis, cfg=cfg).post("/v1/cts/outward/review/A1/decide", json=BODY)
    db.stage["A1"]["age_seconds"] = 60.0                              # staged a minute ago: well inside the 15 minute timeout
    assert _client("checker", db, redis, cfg=cfg).get("/v1/cts/outward/validation-queue").json()["items"] == []
    assert db.stage["A1"]["checker_id"] == "SYSTEM" and db.updates


def test_a_staged_decision_is_left_for_a_checker_while_the_cutoff_is_far():
    redis, db = FakeRedis(), FakeDb(held=["A1"])
    cfg = _cutoff_in(180)
    _client("maker", db, redis, cfg=cfg).post("/v1/cts/outward/review/A1/decide", json=BODY)
    db.stage["A1"]["age_seconds"] = 60.0
    assert len(_client("checker", db, redis, cfg=cfg).get("/v1/cts/outward/validation-queue").json()["items"]) == 1
