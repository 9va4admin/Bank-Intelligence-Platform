"""Bank onboarding through the product. Before this, platform.banks was filled only by a dev seed script,
so a new bank could not be added through the system (found when decisions failed the bank_id FK)."""
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock
from pydantic import ValidationError

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext

from apps.api.routers.platform import BankOnboardRequest, list_banks, onboard_bank


def _ctx(role=Role.PLATFORM_ADMIN):
    return UserContext(user_id="usr-pa", role=role, bank_id="platform", bank_type=BankType.SB,
                       permission_level=PermissionLevel.ADMIN)


def _req(conn, immudb=None):
    req = MagicMock()
    ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock(); pool.acquire = MagicMock(return_value=ctx)
    req.app.state.db_pool_cts = pool
    req.app.state.immudb_client = immudb
    return req


def _body(**kw):
    base = dict(bank_id="kbl", bank_name="Karnataka Bank Ltd", bank_code="KARB", ifsc_prefix="KARB",
                bank_type="PRIVATE")
    base.update(kw)
    return BankOnboardRequest(**base)


@pytest.mark.parametrize("bad", [dict(bank_id="Bad Id"), dict(bank_id="x"), dict(ifsc_prefix="ab"),
                                 dict(ifsc_prefix="KAR1!"), dict(bank_type="NONSENSE"), dict(bank_name="")])
def test_request_validation(bad):
    with pytest.raises(ValidationError):
        _body(**bad)


@pytest.mark.asyncio
async def test_platform_admin_can_onboard_and_it_is_audited():
    conn = AsyncMock(); conn.fetchrow = AsyncMock(return_value={"bank_id": "kbl", "bank_name": "Karnataka Bank Ltd",
        "bank_code": "KARB", "ifsc_prefix": "KARB", "bank_type": "PRIVATE", "is_active": True, "onboarded_at": None,
        "ngch_member_code": None})
    immudb = MagicMock()
    res = await onboard_bank(body=_body(), request=_req(conn, immudb), ctx=_ctx())
    assert res.bank_id == "kbl"
    sql = conn.fetchrow.await_args.args[0]
    assert "INSERT INTO platform.banks" in sql and "ON CONFLICT" in sql
    written = immudb.write_event.call_args.args[0]
    assert written["event_type"] == "BANK_ONBOARDED" and written["bank_id"] == "kbl"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.OPS_MANAGER, Role.BANK_IT_ADMIN, Role.OPS_REVIEWER])
async def test_only_platform_admin_may_onboard(role):
    with pytest.raises(HTTPException) as e:
        await onboard_bank(body=_body(), request=_req(AsyncMock()), ctx=_ctx(role))
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_bank_returns_409():
    conn = AsyncMock(); conn.fetchrow = AsyncMock(return_value=None)      # ON CONFLICT DO NOTHING -> no row
    with pytest.raises(HTTPException) as e:
        await onboard_bank(body=_body(), request=_req(conn), ctx=_ctx())
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_list_requires_platform_admin_and_returns_banks():
    conn = AsyncMock(); conn.fetch = AsyncMock(return_value=[{"bank_id": "kbl", "bank_name": "K", "bank_code": "KARB",
        "ifsc_prefix": "KARB", "bank_type": "PRIVATE", "is_active": True, "onboarded_at": None, "ngch_member_code": None}])
    res = await list_banks(request=_req(conn), ctx=_ctx())
    assert [b.bank_id for b in res.banks] == ["kbl"]
    with pytest.raises(HTTPException):
        await list_banks(request=_req(conn), ctx=_ctx(Role.OPS_MANAGER))
