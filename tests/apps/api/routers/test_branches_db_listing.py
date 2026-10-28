"""GET /v1/branches against the database path: a search must not break the count query, and offset must page."""
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args)); return []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args)); return {"cnt": 0}


class _Pool:
    def __init__(self): self.conn = _Conn()

    def acquire(self):
        pool = self

        class A:
            async def __aenter__(s): return pool.conn
            async def __aexit__(s, *x): return False
        return A()


def _client(pool):
    from apps.api.routers import branches
    app = FastAPI(); app.include_router(branches.router_v1)
    app.dependency_overrides[branches._require_read] = lambda: {"bank_id": "kbl", "user_id": "u", "role": "ops_manager"}
    app.state.db_pool_cts = pool
    return TestClient(app, raise_server_exceptions=False)


def _needed(sql):
    import re
    return max((int(n) for n in re.findall(r"\$(\d+)", sql)), default=0)


def test_a_search_passes_every_parameter_the_count_query_uses():
    pool = _Pool()
    r = _client(pool).get("/v1/branches", params={"q": "CBIN0285109", "limit": 5})
    assert r.status_code == 200, r.text
    for _kind, sql, args in pool.conn.calls:
        assert _needed(sql) == len(args), (sql, args)


def test_offset_pages_through_the_list():
    pool = _Pool()
    r = _client(pool).get("/v1/branches", params={"limit": 50, "offset": 100})
    assert r.status_code == 200, r.text
    kind, sql, args = pool.conn.calls[0]
    assert "OFFSET" in sql.upper() and 100 in args
    for _kind, s, a in pool.conn.calls:
        assert _needed(s) == len(a), (s, a)
