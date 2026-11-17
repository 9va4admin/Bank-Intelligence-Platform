"""Probes: how each dependency is checked, and where the targets come from (deployment configuration, never hardcoded).

TCP and HTTP probes run against real local servers here; Redis and Postgres probes are checked with stand-in clients (their live check is the dev stack).
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.health.probes import ProbeSpec, build_specs, run_probe


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            threading.Event().wait(1.5)
        code = {"/ok": 200, "/missing": 404, "/boom": 500, "/slow": 200}.get(self.path, 200)
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *a):
        pass


@pytest.fixture()
def http_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def _run(spec):
    return asyncio.run(run_probe(spec))


def test_tcp_probe_succeeds_against_a_listening_port_and_measures_latency():
    async def go():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            return await run_probe(ProbeSpec(component="kafka", kind="tcp", target=f"127.0.0.1:{port}"))
        finally:
            server.close()
    r = asyncio.run(go())
    assert r.ok and r.component == "kafka" and r.latency_ms is not None and r.latency_ms >= 0 and r.error is None


def test_tcp_probe_fails_with_a_readable_reason_when_nothing_listens():
    s = socket_free_port()
    r = _run(ProbeSpec(component="kafka", kind="tcp", target=f"127.0.0.1:{s}", timeout_s=1.0))
    assert not r.ok and r.error and r.latency_ms is None


def socket_free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_http_probe_treats_anything_below_500_as_alive_and_500_as_down(http_server):
    base = f"http://127.0.0.1:{http_server}"
    assert _run(ProbeSpec(component="sig_detector", kind="http", target=base + "/ok")).ok
    assert _run(ProbeSpec(component="sig_detector", kind="http", target=base + "/missing")).ok        # a 404 still proves the service answers
    bad = _run(ProbeSpec(component="sig_detector", kind="http", target=base + "/boom"))
    assert not bad.ok and "500" in bad.error


def test_http_probe_times_out_instead_of_hanging(http_server):
    r = _run(ProbeSpec(component="vllm", kind="http", target=f"http://127.0.0.1:{http_server}/slow", timeout_s=0.3))
    assert not r.ok and "timed out" in r.error.lower()


def test_the_slow_limit_and_criticality_travel_with_the_result(http_server):
    r = _run(ProbeSpec(component="vllm", kind="http", target=f"http://127.0.0.1:{http_server}/ok", slow_ms=250.0, critical=False))
    assert r.slow_ms == 250.0 and r.critical is False


def test_redis_probe_pings():
    fake = MagicMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    with patch("modules.cts.health.probes._redis_from_url", return_value=fake):
        r = _run(ProbeSpec(component="redis", kind="redis", target="redis://localhost:6379/0"))
    assert r.ok and fake.ping.await_count == 1


def test_redis_probe_reports_the_error():
    fake = MagicMock()
    fake.ping = AsyncMock(side_effect=ConnectionError("refused"))
    fake.aclose = AsyncMock()
    with patch("modules.cts.health.probes._redis_from_url", return_value=fake):
        r = _run(ProbeSpec(component="redis", kind="redis", target="redis://x"))
    assert not r.ok and "refused" in r.error


def test_postgres_probe_runs_select_one_and_closes():
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.close = AsyncMock()
    with patch("modules.cts.health.probes._pg_connect", AsyncMock(return_value=conn)):
        r = _run(ProbeSpec(component="yugabyte", kind="postgres", target="postgresql://u:p@h/db"))
    assert r.ok and conn.fetchval.await_args.args[0] == "SELECT 1" and conn.close.await_count == 1


def test_an_unknown_probe_kind_is_a_failed_probe_not_a_crash():
    r = _run(ProbeSpec(component="x", kind="carrier-pigeon", target="t"))
    assert not r.ok and "carrier-pigeon" in r.error


def test_the_error_never_carries_the_password_in_a_dsn():
    with patch("modules.cts.health.probes._pg_connect", AsyncMock(side_effect=RuntimeError("could not connect to postgresql://yugabyte:hunter2@db:5433/x"))):
        r = _run(ProbeSpec(component="yugabyte", kind="postgres", target="postgresql://yugabyte:hunter2@db:5433/x"))
    assert "hunter2" not in r.error


# ---------------- where the targets come from -----------------

class _Cfg:
    def __init__(self, platform=None, layer3=None, secrets=None):
        self.p, self.l3, self.s = platform or {}, layer3 or {}, secrets or {}

    def get_platform(self, key):
        env = key.upper().replace(".", "_")
        if env not in self.p:
            from shared.config.config_service import ConfigKeyNotFoundError
            raise ConfigKeyNotFoundError(key)
        return self.p[env]

    async def get(self, key):
        if key not in self.l3:
            from shared.config.config_service import ConfigKeyNotFoundError
            raise ConfigKeyNotFoundError(key)
        return self.l3[key]

    async def get_secret(self, key):
        if key not in self.s:
            raise KeyError(key)
        return self.s[key]


def _specs(cfg):
    return {s.component: s for s in asyncio.run(build_specs(cfg))}


def test_targets_are_built_from_configuration_and_unconfigured_ones_are_skipped():
    cfg = _Cfg(platform={"TEMPORAL_ADDRESS": "temporal:7233", "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092,kafka2:9092",
                         "IMMUDB_HOST": "immudb", "IMMUDB_PORT": "3322", "VAULT_ADDR": "http://vault:8200"},
               layer3={"db.cts.dsn": "postgresql://u:p@yb:5433/db", "redis.cts.url": "redis://r:6379/0", "vllm.url": "http://gpu:8000",
                       "services.sig_detector.url": "http://sig:8020", "services.indic_ocr.url": "http://ocr:8021"},
               secrets={"minio.endpoint": "minio:9000"})
    s = _specs(cfg)
    assert s["yugabyte"].kind == "postgres" and s["redis"].kind == "redis"
    assert (s["temporal"].kind, s["temporal"].target) == ("tcp", "temporal:7233")
    assert s["kafka"].target == "kafka:9092"                      # the first broker; a broker list is one component
    assert (s["immudb"].kind, s["immudb"].target) == ("tcp", "immudb:3322")
    assert s["vault"].target == "http://vault:8200/v1/sys/health?standbyok=true"
    assert s["minio"].target == "http://minio:9000/minio/health/live"
    assert s["vllm"].target == "http://gpu:8000/health" and s["vllm"].critical is False      # a dead model server degrades to human review
    assert "sig_detector" in s and "indic_ocr" in s
    assert "cbs" not in s and "ngch" not in s                      # not configured -> not probed


def test_minio_is_probed_over_https_when_secure():
    cfg = _Cfg(platform={"MINIO_SECURE": "true"}, secrets={"minio.endpoint": "minio:9000"})
    assert _specs(cfg)["minio"].target.startswith("https://minio:9000")


def test_extra_probes_can_be_added_from_hot_reloadable_config():
    extra = json.dumps([{"component": "cctv_adapter", "kind": "http", "target": "http://cctv:9000/health", "critical": False, "slow_ms": 800}])
    s = _specs(_Cfg(layer3={"platform_health.extra_probes": extra}))
    assert s["cctv_adapter"].critical is False and s["cctv_adapter"].slow_ms == 800


def test_a_malformed_extra_probes_value_is_ignored_not_fatal():
    assert _specs(_Cfg(layer3={"platform_health.extra_probes": "{not json"})) == {}


def test_the_probe_timeout_is_configurable_and_an_extra_probe_can_override_it():
    cfg = _Cfg(platform={"TEMPORAL_ADDRESS": "temporal:7233"},
               layer3={"platform_health.probe_timeout_seconds": 9, "db.cts.dsn": "postgresql://u:p@yb:5433/db",
                       "platform_health.extra_probes": json.dumps([{"component": "slow_link", "kind": "tcp", "target": "far:1", "timeout_s": 20}])})
    s = _specs(cfg)
    assert s["temporal"].timeout_s == 9 and s["yugabyte"].timeout_s == 9
    assert s["slow_link"].timeout_s == 20


def test_without_the_setting_the_default_timeout_stays_three_seconds():
    assert _specs(_Cfg(platform={"TEMPORAL_ADDRESS": "t:1"}))["temporal"].timeout_s == 3.0


def test_the_redis_client_uses_the_probes_timeout_not_a_hardcoded_one():
    """The client had its own 3 s socket timeout, so a probe allowed 10 s reported 'timed out after 10s' after 3 s (found on the live run)."""
    fake = MagicMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    with patch("modules.cts.health.probes._redis_from_url", return_value=fake) as factory:
        _run(ProbeSpec(component="redis", kind="redis", target="redis://x", timeout_s=7.0))
    assert factory.call_args.args == ("redis://x", 7.0)
