"""record_drawee_name — inward Drawee Name from the account-number lookup in CBS.

Decision (2026-10-13, bank owner): the drawee name is stored as plain text — it is the
operational identifier the reviewer needs, and is exempt from column encryption/masking.
It is still never returned to the workflow (kept out of Temporal history), and a failed
lookup must never change the cheque decision.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.workflows.activities.drawee_name import (
    DraweeNameInput, record_drawee_name,
)
from shared.cbs_connector.base import AccountInfo, AccountStatus
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

_INP = DraweeNameInput(account_number="7001000024", bank_id="kbl", instrument_id="IW-kbl-1")


def _info(name):
    return AccountInfo(account_number_hash="h", account_number_last4="0024",
                       status=AccountStatus.ACTIVE, bank_id="kbl", holder_name=name)


def _conn():
    c = MagicMock()
    c.execute = AsyncMock()
    return c


def _cbs(name=None, exc=None):
    cbs = MagicMock()
    cbs.get_account_info = AsyncMock(return_value=_info(name), side_effect=exc)
    return cbs


class TestAccountInfoHolderName:
    def test_holder_name_is_optional_and_defaults_to_none(self):
        info = AccountInfo(account_number_hash="h", account_number_last4="0024",
                           status=AccountStatus.ACTIVE, bank_id="kbl")
        assert info.holder_name is None


class TestRecordDraweeName:
    @pytest.mark.asyncio
    async def test_name_is_stored_and_result_does_not_carry_it(self):
        conn = _conn()
        res = await record_drawee_name(_INP, cbs_connector=_cbs("JAGADISH.V"), db_conn=conn)
        assert res.stored is True
        assert "JAGADISH" not in repr(res)          # stays out of Temporal history
        assert "JAGADISH.V" in conn.execute.await_args.args

    @pytest.mark.asyncio
    async def test_raw_account_number_is_never_written(self):
        conn = _conn()
        await record_drawee_name(_INP, cbs_connector=_cbs("X"), db_conn=conn)
        assert "7001000024" not in conn.execute.await_args.args

    @pytest.mark.asyncio
    async def test_no_holder_name_in_cbs_stores_nothing(self):
        conn = _conn()
        res = await record_drawee_name(_INP, cbs_connector=_cbs(None), db_conn=conn)
        assert res.stored is False and res.reason == "NO_NAME"
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc,reason", [
        (CBSUnavailableError("down"), "CBS_UNAVAILABLE"),
        (AccountNotFoundError("0024"), "ACCOUNT_NOT_FOUND"),
        (RuntimeError("boom"), "CBS_UNAVAILABLE"),
    ])
    async def test_cbs_failure_degrades_never_raises(self, exc, reason):
        res = await record_drawee_name(_INP, cbs_connector=_cbs(exc=exc), db_conn=_conn())
        assert res.stored is False and res.reason == reason

    @pytest.mark.asyncio
    async def test_no_db_connection_degrades(self):
        res = await record_drawee_name(_INP, cbs_connector=_cbs("X"), db_conn=None)
        assert res.stored is False and res.reason == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_write_failure_degrades(self):
        conn = _conn()
        conn.execute = AsyncMock(side_effect=RuntimeError("db down"))
        res = await record_drawee_name(_INP, cbs_connector=_cbs("X"), db_conn=conn)
        assert res.stored is False and res.reason == "DB_ERROR"

    @pytest.mark.asyncio
    async def test_idempotent_upsert_on_retry(self):
        conn = _conn()
        await record_drawee_name(_INP, cbs_connector=_cbs("X"), db_conn=conn)
        assert "ON CONFLICT" in conn.execute.await_args.args[0]
