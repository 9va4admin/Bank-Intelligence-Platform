"""Outward maker-checker: the maker's decision on a held outward instrument is staged, not final; a different person
(the checker) confirms or overrules it through /outward/review/{id}/validate."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import Role

BANK = "kbl"


class FakeDb:
    """Just enough of an asyncpg pool: remembers staged rows and the instrument status updates."""

    def __init__(self):
        self.stage: dict[str, dict] = {}
        self.updates: list[tuple] = []

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
            self.stage[iid] = {"maker_id": maker, "maker_decision": decision, "maker_reason": reason, "status": "MAKER_DECIDED"}
            return "INSERT 0 1"
        if s.startswith("UPDATE cts.outward_review_stage"):
            self.stage[args[1]]["status"] = "FINAL"
            return "UPDATE 1"
        if s.startswith("UPDATE cts.cheque_instruments"):
            self.updates.append(args)
        return "OK"

    async def fetchrow(self, sql, *args):
        if "FROM cts.outward_review_stage" in sql:
            row = self.stage.get(args[1])
            return dict(row, instrument_id=args[1]) if row and row["status"] == "MAKER_DECIDED" else None
        return None

    async def fetch(self, sql, *args):
        if "FROM cts.outward_review_stage" in sql:
            return [dict(v, instrument_id=k, cheque_number="C", payee_display="P***", amount_range="₹[<1L]",
                         review_reason="r", branch_id="b", lot_id=None, instrument_category="CHEQUE",
                         made_at="2026-10-28T10:00:00")
                    for k, v in self.stage.items() if v["status"] == "MAKER_DECIDED"]
        return []


def _client(user, on=True, role="ops_reviewer", db=None):
    from apps.api.routers import cts_outward_data
    from apps.api.routers.cts_deps import get_current_user_context
    app = FastAPI(); app.include_router(cts_outward_data.router_v1)
    ctx = MagicMock(); ctx.role = Role[role.upper()]; ctx.bank_id = BANK; ctx.user_id = user
    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.state.db_pool_cts = db if db is not None else FakeDb()
    cs = AsyncMock(); cs.get_cts_config.return_value = {"maker_checker_enabled": on}
    app.state.config_service = cs
    c = TestClient(app, raise_server_exceptions=False)
    c.db = app.state.db_pool_cts
    return c


BODY = {"action": "CONFIRMED", "reason": "fields match", "reason_category": "manual"}


def test_with_maker_checker_on_the_makers_decision_is_staged_and_the_instrument_is_untouched():
    c = _client("maker")
    r = c.post("/v1/cts/outward/review/I-1/decide", json=BODY)
    assert r.status_code == 200 and "checker" in r.json()["message"].lower()
    assert c.db.stage["I-1"]["maker_id"] == "maker" and c.db.updates == []


def test_with_maker_checker_off_the_decision_is_final_as_before():
    c = _client("maker", on=False)
    assert c.post("/v1/cts/outward/review/I-1/decide", json=BODY).status_code == 200
    assert c.db.stage == {} and len(c.db.updates) == 1


def test_a_second_maker_decision_on_the_same_instrument_is_refused():
    db = FakeDb()
    assert _client("m1", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY).status_code == 200
    assert _client("m2", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY).status_code == 409


def test_a_different_person_validates_and_the_decision_becomes_final():
    db = FakeDb(); _client("maker", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY)
    r = _client("checker", db=db).post("/v1/cts/outward/review/I-1/validate",
                                       json={"action": "REJECTED", "reason": "overrule", "reason_category": "manual"})
    assert r.status_code == 200
    assert db.stage["I-1"]["status"] == "FINAL" and db.updates[0][0] == "STP_RETURN"


def test_the_maker_cannot_validate_their_own_decision():
    db = FakeDb(); _client("maker", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY)
    r = _client("maker", db=db).post("/v1/cts/outward/review/I-1/validate", json=BODY)
    assert r.status_code == 403 and "different person" in r.json()["detail"]
    assert db.updates == []


def test_validate_needs_a_staged_decision():
    assert _client("checker").post("/v1/cts/outward/review/I-9/validate", json=BODY).status_code == 409


def test_validate_is_refused_when_maker_checker_is_off():
    db = FakeDb(); _client("maker", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY)
    assert _client("checker", on=False, db=db).post("/v1/cts/outward/review/I-1/validate", json=BODY).status_code == 409


@pytest.mark.parametrize("role", ["compliance_officer", "fraud_analyst"])
def test_other_roles_cannot_validate(role):
    assert _client("x", role=role).post("/v1/cts/outward/review/I-1/validate", json=BODY).status_code == 403


def test_the_validation_queue_lists_staged_items_with_who_made_the_decision():
    db = FakeDb(); _client("maker", db=db).post("/v1/cts/outward/review/I-1/decide", json=BODY)
    r = _client("checker", db=db).get("/v1/cts/outward/validation-queue")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["instrument_id"] == "I-1" and item["maker_id"] == "maker" and item["maker_decision"] == "CONFIRMED"
