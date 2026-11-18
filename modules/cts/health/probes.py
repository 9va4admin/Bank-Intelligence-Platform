"""How each dependency is checked, and where the targets come from.

Targets come from deployment configuration (the same keys the worker already uses), so a new environment needs no code change; a dependency that is
not configured is not probed. Bank-specific extras (CCTV adapters, a second CBS ...) are added in hot-reloadable config:
    platform_health.extra_probes = [{"component": "...", "kind": "tcp|http|redis|postgres", "target": "...", "critical": false, "slow_ms": 800}]
Probe errors never contain a password: DSN credentials are masked before an error is kept.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from modules.cts.health.state_machine import Probe
from shared.messages import get_message

log = structlog.get_logger()

_CRED = re.compile(r"(\w+://[^:/@\s]+):[^@\s]+@")


class ProbeSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    component: str
    kind: str                         # tcp | http | redis | postgres
    target: str
    critical: bool = True
    slow_ms: Optional[float] = None   # a successful probe slower than this counts as slow
    timeout_s: float = 3.0
    limit: Optional[float] = None     # disk / memory: the percent used above which the probe fails


def _mask(text: str) -> str:
    return _CRED.sub(r"\1:***@", text)[:240]


def _redis_from_url(url: str, timeout: float):
    import redis.asyncio as aioredis
    return aioredis.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)


async def _pg_connect(dsn: str, timeout: float):
    import asyncpg
    return await asyncpg.connect(dsn, timeout=timeout)


async def _tcp(target: str, timeout: float) -> None:
    host, _, port = target.rpartition(":")
    _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def _http(target: str, timeout: float) -> None:
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(target)
    if resp.status_code >= 500:
        raise RuntimeError(get_message("CTS_HTTP", status_code=resp.status_code))          # below 500 (even a 404) proves the service is answering


async def _redis(target: str, timeout: float) -> None:
    client = _redis_from_url(target, timeout)
    try:
        await asyncio.wait_for(client.ping(), timeout)
    finally:
        await client.aclose()


async def _postgres(target: str, timeout: float) -> None:
    conn = await _pg_connect(target, timeout)
    try:
        await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout)
    finally:
        await conn.close()


_KINDS = {"tcp": _tcp, "http": _http, "redis": _redis, "postgres": _postgres}


class _Breach(Exception):
    """A host resource over its limit: the message is the whole story."""


def _disk_usage(path: str):
    import psutil
    return psutil.disk_usage(path)


def _memory_percent() -> float:
    import psutil
    return float(psutil.virtual_memory().percent)


async def _disk(target: str, limit: float) -> None:
    used = (await asyncio.to_thread(_disk_usage, target)).percent
    if used >= limit:
        raise _Breach(get_message("HEALTH_PROBE_DISK_FULL", path=target, used=format(used, "g"), limit=format(limit, "g")))


async def _memory(target: str, limit: float) -> None:
    used = await asyncio.to_thread(_memory_percent)
    if used >= limit:
        raise _Breach(get_message("HEALTH_PROBE_MEMORY_HIGH", used=format(used, "g"), limit=format(limit, "g")))


_LIMITED = {"disk": _disk, "memory": _memory}


async def run_probe(spec: ProbeSpec) -> Probe:
    base = dict(component=spec.component, slow_ms=spec.slow_ms, critical=spec.critical)
    fn = _KINDS.get(spec.kind)
    if fn is None and spec.kind not in _LIMITED:
        return Probe(ok=False, error=get_message("CTS_UNKNOWN_PROBE_KIND", kind=spec.kind), **base)
    started = time.perf_counter()
    try:
        if fn is None:
            await asyncio.wait_for(_LIMITED[spec.kind](spec.target, spec.limit if spec.limit is not None else 90.0), spec.timeout_s + 1.0)
        else:
            await asyncio.wait_for(fn(spec.target, spec.timeout_s), spec.timeout_s + 1.0)
    except _Breach as exc:
        return Probe(ok=False, error=str(exc), **base)
    except asyncio.TimeoutError:
        return Probe(ok=False, error=f"timed out after {spec.timeout_s:g}s", **base)
    except Exception as exc:
        if "Timeout" in type(exc).__name__:                      # httpx.ReadTimeout, ConnectTimeout, ... all read as one thing
            return Probe(ok=False, error=f"timed out after {spec.timeout_s:g}s", **base)
        text = _mask(str(exc))
        return Probe(ok=False, error=f"{type(exc).__name__}: {text}" if text else type(exc).__name__, **base)
    return Probe(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 1), **base)


# ---------------- targets from configuration -----------------

def _platform(cfg: Any, key: str) -> Optional[str]:
    try:
        v = cfg.get_platform(key)
    except Exception:
        return None
    return v.strip() if isinstance(v, str) and v.strip() else None


async def _l3(cfg: Any, key: str) -> Optional[Any]:
    try:
        return await cfg.get(key)
    except Exception:
        return None


async def _secret(cfg: Any, key: str) -> Optional[str]:
    try:
        v = await cfg.get_secret(key)
    except Exception:
        return None
    return v.strip() if isinstance(v, str) and v.strip() else None


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def build_specs(cfg: Any) -> list[ProbeSpec]:
    """Probe targets from configuration. platform_health.probe_timeout_seconds (default 3) applies to every built-in probe; a slow link or a
    slow developer machine raises it, and an extra probe can set its own timeout_s."""
    specs = await _build_default_specs(cfg)
    try:
        timeout = float(await _l3(cfg, "platform_health.probe_timeout_seconds") or 3.0)
    except (TypeError, ValueError):
        timeout = 3.0
    specs = [s.model_copy(update={"timeout_s": timeout}) for s in specs]
    if await _l3(cfg, "platform_health.host_probes_enabled") not in (False, "false", "False", 0):
        disk_limit = _num(await _l3(cfg, "platform_health.disk_max_percent"), 90.0)
        mem_limit = _num(await _l3(cfg, "platform_health.memory_max_percent"), 90.0)
        specs.append(ProbeSpec(component="disk", kind="disk", target=os.path.abspath(os.sep), limit=disk_limit, critical=False, timeout_s=timeout))
        specs.append(ProbeSpec(component="memory", kind="memory", target="host", limit=mem_limit, critical=False, timeout_s=timeout))
    raw = await _l3(cfg, "platform_health.extra_probes")
    if raw:
        try:
            for item in (json.loads(raw) if isinstance(raw, str) else raw):
                specs.append(ProbeSpec(**item))
        except Exception as exc:
            log.warning("platform_health.extra_probes_ignored", error=str(exc)[:120])
    return specs


async def _build_default_specs(cfg: Any) -> list[ProbeSpec]:
    specs: list[ProbeSpec] = []
    if dsn := await _l3(cfg, "db.cts.dsn"):
        specs.append(ProbeSpec(component="yugabyte", kind="postgres", target=dsn, slow_ms=500))
    if url := await _l3(cfg, "redis.cts.url"):
        specs.append(ProbeSpec(component="redis", kind="redis", target=url, slow_ms=100))
    if addr := _platform(cfg, "temporal.address"):
        specs.append(ProbeSpec(component="temporal", kind="tcp", target=addr, slow_ms=500))
    if brokers := _platform(cfg, "kafka.bootstrap_servers"):
        specs.append(ProbeSpec(component="kafka", kind="tcp", target=brokers.split(",")[0].strip(), slow_ms=500))
    if host := _platform(cfg, "immudb.host"):
        specs.append(ProbeSpec(component="immudb", kind="tcp", target=f"{host}:{_platform(cfg, 'immudb.port') or '3322'}", slow_ms=500))
    if vault := _platform(cfg, "vault.addr"):
        specs.append(ProbeSpec(component="vault", kind="http", target=vault.rstrip("/") + "/v1/sys/health?standbyok=true", slow_ms=500))
    if endpoint := await _secret(cfg, "minio.endpoint"):
        scheme = "https" if (_platform(cfg, "minio.secure") or "").lower() == "true" else "http"
        specs.append(ProbeSpec(component="minio", kind="http", target=f"{scheme}://{endpoint}/minio/health/live", slow_ms=500))
    # AI services: a dead one degrades to human review rather than stopping clearing, so they are not "critical".
    if url := await _l3(cfg, "vllm.url"):
        specs.append(ProbeSpec(component="vllm", kind="http", target=url.rstrip("/") + "/health", critical=False, slow_ms=1000))
    for component, key, path in (("sig_detector", "services.sig_detector.url", ""), ("indic_ocr", "services.indic_ocr.url", "/health")):
        if url := await _l3(cfg, key):
            specs.append(ProbeSpec(component=component, kind="http", target=url.rstrip("/") + path, critical=False, slow_ms=1000))
    if url := _platform(cfg, "cbs.base_url"):
        specs.append(ProbeSpec(component="cbs", kind="http", target=url, slow_ms=2000))
    if url := _platform(cfg, "ngch.rest_base_url"):
        specs.append(ProbeSpec(component="ngch", kind="http", target=url, slow_ms=2000))

    return specs
