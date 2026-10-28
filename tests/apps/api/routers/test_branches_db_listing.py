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

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args)); return "INSERT 0 1"

    def transaction(self):
        class T:
            async def __aenter__(s): return s
            async def __aexit__(s, *x): return False
        return T()


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


# --- bulk import carries the processing unit ------------------------------------------------------------------------

CSV_HEAD = "Branch Name,Complete Address,City,District,State,PIN Code,IFSC Code,Phone Number"


def _import(csv_text, pool=None):
    import io
    from apps.api.routers import branches
    branches._BRANCH_STORE.clear()
    app = FastAPI(); app.include_router(branches.router_v1)
    app.dependency_overrides[branches.get_current_user] = lambda: {"bank_id": "kbl", "user_id": "admin", "role": "bank_it_admin"}
    if pool is not None:
        app.state.db_pool_cts = pool
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/v1/branches/bulk-import", files={"file": ("b.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})
    return r


def test_an_optional_pu_id_column_is_stored_on_the_branch():
    from apps.api.routers import branches
    r = _import(CSV_HEAD + ",PU ID\nGoa Main,Addr,Panaji,North Goa,Goa,403001,CBIN0280001,0832,PU-MUMBAI\n")
    assert r.status_code == 200, r.text
    assert branches._BRANCH_STORE["CBIN0280001"]["pu_id"] == "PU-MUMBAI"


def test_without_the_pu_column_the_branch_has_no_pu_as_before():
    from apps.api.routers import branches
    r = _import(CSV_HEAD + "\nGoa Main,Addr,Panaji,North Goa,Goa,403001,CBIN0280001,0832\n")
    assert r.status_code == 200, r.text
    assert branches._BRANCH_STORE["CBIN0280001"]["pu_id"] is None


def test_the_database_upsert_writes_pu_id_and_keeps_an_existing_one_when_the_file_has_none():
    pool = _Pool()
    _import(CSV_HEAD + ",PU ID\nGoa Main,Addr,Panaji,North Goa,Goa,403001,CBIN0280001,0832,PU-MUMBAI\n", pool)
    inserts = [(sql, args) for kind, sql, args in pool.conn.calls if kind == "execute"]
    assert inserts, "no insert was run"
    sql, args = inserts[0]
    assert "pu_id = COALESCE(EXCLUDED.pu_id" in sql and "PU-MUMBAI" in args
