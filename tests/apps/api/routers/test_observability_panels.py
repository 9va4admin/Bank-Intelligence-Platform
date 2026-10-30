"""Ops dashboard panels: the IET query must compare epoch seconds to epoch seconds, and the vault coverage count must
iterate the async Redis scan (both silently degraded the panels before)."""
import pytest


class _Conn:
    def __init__(self): self.sql = []

    async def fetchrow(self, sql, *a):
        self.sql.append(sql)
        return {"near_breach": 1, "in_processing": 3, "queue_depth": 2, "avg_wait": 4.0, "accounts": 10}


class _Pool:
    def __init__(self): self.conn = _Conn()

    def acquire(self):
        pool = self

        class A:
            async def __aenter__(s): return pool.conn
            async def __aexit__(s, *x): return False
        return A()


class _AsyncRedis:
    async def _gen(self, n):
        for i in range(n):
            yield f"sig:kbl:{i}"

    def scan_iter(self, match=None, count=None):
        return self._gen(4)                     # an async generator, as redis.asyncio returns


@pytest.mark.asyncio
async def test_the_iet_risk_query_compares_epoch_seconds():
    from apps.api.routers.observability import _fetch_dashboard_panels
    pool = _Pool()
    iet, review = await _fetch_dashboard_panels("kbl", pool)
    assert iet.degraded is False and iet.near_breach_count == 1
    iet_sql = next(s for s in pool.conn.sql if "near_breach" in s)
    assert "EXTRACT(EPOCH" in iet_sql.upper(), "iet_deadline is a double precision epoch; comparing it to NOW() raises"


@pytest.mark.asyncio
async def test_vault_coverage_counts_keys_from_the_async_scan():
    from apps.api.routers.observability import _fetch_vault_coverage
    panel = await _fetch_vault_coverage("kbl", _Pool(), _AsyncRedis())
    assert panel.degraded is False and panel.redis_sig_keys == 4 and panel.yugabyte_accounts == 10
