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


# ---------------- Vault panel without a Vault client: ask Vault's own health endpoint -----------------

def _vault_server(status_code, body):
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_json.dumps(body).encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_vault_panel_falls_back_to_the_health_endpoint_when_there_is_no_client():
    import asyncio
    from apps.api.routers.observability import _fetch_vault_panel
    for code, body, sealed in ((200, {"sealed": False}, "unsealed"), (429, {"sealed": False}, "unsealed"), (503, {"sealed": True}, "sealed")):
        srv, url = _vault_server(code, body)
        try:
            p = asyncio.run(_fetch_vault_panel(None, "kbl", vault_addr=url))
        finally:
            srv.shutdown()
        assert p.connected and p.seal_status == sealed and not p.degraded, (code, p)


def test_vault_panel_is_degraded_when_the_endpoint_is_unreachable_or_unconfigured():
    import asyncio
    from apps.api.routers.observability import _fetch_vault_panel
    assert asyncio.run(_fetch_vault_panel(None, "kbl")).degraded
    assert asyncio.run(_fetch_vault_panel(None, "kbl", vault_addr="http://127.0.0.1:1")).degraded
