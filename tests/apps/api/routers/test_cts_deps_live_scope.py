"""A reviewer's access is read from the database on every request, not trusted from the session. An admin who narrows a
reviewer's branches or units, or disables the account, takes effect on that reviewer's very next request."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.routers.cts_deps import get_current_user_context
from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


def _ctx(pu=("PU-1", "PU-2"), branches=("B1", "B2")):
    return UserContext(user_id="usr-1", role=Role.OPS_REVIEWER, bank_id="kbl", bank_type=BankType.SB,
                       permission_level=PermissionLevel.EDIT, pu_ids=list(pu), branch_ids=list(branches))


class _Pool:
    def __init__(self, row=None, error=None):
        self.row, self.error, self.asked = row, error, []

    def acquire(self):
        pool = self

        class A:
            async def __aenter__(s): return s
            async def __aexit__(s, *x): return False

            async def fetchrow(s, sql, *args):
                pool.asked.append((sql, args))
                if pool.error:
                    raise pool.error
                return pool.row
        return A()


def _request(pool, which="db_pool_platform"):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**{which: pool})))


def run(req, ctx):
    return asyncio.run(get_current_user_context(req, ctx))


def test_the_current_scope_replaces_what_the_session_carries():
    pool = _Pool({"pu_ids": ["PU-1"], "branch_ids": ["B1"], "is_active": True})
    out = run(_request(pool), _ctx())
    assert out.pu_ids == ["PU-1"] and out.branch_ids == ["B1"]
    assert pool.asked[0][1] == ("usr-1", "kbl")                    # looked up by user and bank, never by anything the client sends


def test_an_admin_taking_every_branch_away_makes_the_reviewer_central_staff_at_once():
    out = run(_request(_Pool({"pu_ids": [], "branch_ids": [], "is_active": True})), _ctx())
    assert out.branch_ids == []


def test_a_disabled_account_is_refused_even_with_a_valid_session():
    with pytest.raises(HTTPException) as e:
        run(_request(_Pool({"pu_ids": ["PU-1"], "branch_ids": [], "is_active": False})), _ctx())
    assert e.value.status_code == 403


def test_a_user_with_no_local_account_row_keeps_the_scope_from_the_identity_provider():
    out = run(_request(_Pool(None)), _ctx())
    assert out.pu_ids == ["PU-1", "PU-2"] and out.branch_ids == ["B1", "B2"]


def test_when_the_lookup_fails_the_session_scope_is_used_rather_than_locking_everyone_out():
    out = run(_request(_Pool(error=RuntimeError("db down"))), _ctx())
    assert out.pu_ids == ["PU-1", "PU-2"]


def test_without_a_database_pool_nothing_changes():
    out = run(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), _ctx())
    assert out.branch_ids == ["B1", "B2"]


def test_the_cts_pool_is_used_when_there_is_no_platform_pool():
    pool = _Pool({"pu_ids": ["PU-9"], "branch_ids": [], "is_active": True})
    assert run(_request(pool, "db_pool_cts"), _ctx()).pu_ids == ["PU-9"]


def test_a_row_that_is_not_an_account_row_is_treated_as_a_failed_lookup():
    out = run(_request(_Pool({"lot_id": "L1"})), _ctx())
    assert out.pu_ids == ["PU-1", "PU-2"]
