"""TDD for shared.auth.enrollment_store.YugabyteDBAccountEnrollmentStore."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _pool(fetchval_return=None):
    """Return a mock asyncpg pool whose connection returns the given fetchval."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncContextManager(conn))
    pool._conn = conn  # expose for assertion access
    return pool


class _AsyncContextManager:
    def __init__(self, value):
        self._v = value

    async def __aenter__(self):
        return self._v

    async def __aexit__(self, *a):
        pass


class TestYugabyteDBAccountEnrollmentStore:
    @pytest.mark.asyncio
    async def test_is_totp_enrolled_returns_true_when_db_true(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool(fetchval_return=True)
        store = YugabyteDBAccountEnrollmentStore(pool)
        result = await store.is_totp_enrolled("user-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_totp_enrolled_returns_false_when_db_false(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool(fetchval_return=False)
        store = YugabyteDBAccountEnrollmentStore(pool)
        result = await store.is_totp_enrolled("user-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_totp_enrolled_returns_false_when_user_not_found(self):
        """fetchval returns None when no row matches — must return False, not crash."""
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool(fetchval_return=None)
        store = YugabyteDBAccountEnrollmentStore(pool)
        result = await store.is_totp_enrolled("unknown-user")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_totp_enrolled_queries_correct_table(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool(fetchval_return=False)
        store = YugabyteDBAccountEnrollmentStore(pool)
        await store.is_totp_enrolled("user-1")
        call_args = pool._conn.fetchval.call_args
        sql = call_args.args[0]
        assert "platform.local_auth_accounts" in sql
        assert "totp_enrolled" in sql

    @pytest.mark.asyncio
    async def test_is_totp_enrolled_passes_user_id_as_param(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool(fetchval_return=False)
        store = YugabyteDBAccountEnrollmentStore(pool)
        await store.is_totp_enrolled("usr-999")
        call_args = pool._conn.fetchval.call_args
        assert "usr-999" in call_args.args

    @pytest.mark.asyncio
    async def test_set_totp_enrolled_true_executes_update(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool()
        store = YugabyteDBAccountEnrollmentStore(pool)
        await store.set_totp_enrolled("user-1", True)
        pool._conn.execute.assert_called_once()
        call_args = pool._conn.execute.call_args
        sql = call_args.args[0]
        assert "totp_enrolled" in sql
        assert "UPDATE" in sql.upper()

    @pytest.mark.asyncio
    async def test_set_totp_enrolled_passes_correct_args(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool()
        store = YugabyteDBAccountEnrollmentStore(pool)
        await store.set_totp_enrolled("usr-42", True)
        call_args = pool._conn.execute.call_args
        positional_args = call_args.args
        assert "usr-42" in positional_args
        assert True in positional_args

    @pytest.mark.asyncio
    async def test_set_totp_enrolled_false_still_executes_update(self):
        from shared.auth.enrollment_store import YugabyteDBAccountEnrollmentStore
        pool = _pool()
        store = YugabyteDBAccountEnrollmentStore(pool)
        await store.set_totp_enrolled("user-1", False)
        pool._conn.execute.assert_called_once()
        call_args = pool._conn.execute.call_args
        assert False in call_args.args
