"""Scanner machine-token authentication (get_bank_id_scanner_or_user): the edge scanner agent has a bearer token, not a user session."""
import contextlib
import hashlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.cts_deps import get_bank_id_scanner_or_user


class _Conn:
    def __init__(self, row):
        self.row, self.sql, self.args = row, [], []

    async def fetchrow(self, sql, *args):
        self.sql.append(sql); self.args.append(args)
        return self.row


class _Pool:
    def __init__(self, row):
        self.conn = _Conn(row)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


def _client(pool):
    app = FastAPI()

    @app.get("/who")
    async def who(bank_id: str = Depends(get_bank_id_scanner_or_user)):
        return {"bank_id": bank_id}

    if pool is not None:
        app.state.db_pool_cts = pool
    return TestClient(app, raise_server_exceptions=False)


def test_valid_token_resolves_the_banks_id():
    pool = _Pool({"bank_id": "kbl"})
    r = _client(pool).get("/who", headers={"Authorization": "Bearer scanner-secret"})
    assert r.status_code == 200 and r.json() == {"bank_id": "kbl"}
    assert pool.conn.args[0] == (hashlib.sha256(b"scanner-secret").hexdigest(),)   # only the hash is looked up


def test_unknown_or_revoked_token_is_rejected():
    r = _client(_Pool(None)).get("/who", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_no_credentials_is_rejected():
    assert _client(_Pool(None)).get("/who").status_code == 401


def test_lookup_excludes_revoked_and_expired_tokens():
    """expires_at was never checked, so a scanner token kept working after its expiry."""
    pool = _Pool({"bank_id": "kbl"})
    _client(pool).get("/who", headers={"Authorization": "Bearer t"})
    sql = pool.conn.sql[0]
    assert "revoked = false" in sql and "expires_at > now()" in sql


def test_database_error_never_authenticates():
    class _Bad:
        @contextlib.asynccontextmanager
        async def acquire(self):
            raise RuntimeError("db down")
            yield
    assert _client(_Bad()).get("/who", headers={"Authorization": "Bearer t"}).status_code == 401
