"""Live reproduction of the 30 s stall: a pooled Redis connection the network silently stops carrying.

A TCP proxy sits between the client and the real integration Redis. After the first command it goes silent (accepts bytes,
forwards nothing), which is what a dropped idle connection looks like to the client. A client with no socket timeout waits
for the OS; ours must give up in about the configured socket timeout and reconnect."""
from __future__ import annotations

import asyncio
import time

import pytest
import redis.asyncio as aioredis

from shared.config.redis_options import redis_options
from tests.integration.conftest import REDIS_HOST, REDIS_PORT

pytestmark = pytest.mark.asyncio


class _Proxy:
    def __init__(self):
        self.silent = False
        self.server = None
        self.conns = []

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _handle(self, cr, cw):
        try:
            ur, uw = await asyncio.open_connection(REDIS_HOST, REDIS_PORT)
        except OSError:
            cw.close()
            return
        self.conns.append((cw, uw))

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    if not self.silent:
                        dst.write(data)
                        await dst.drain()
            except (ConnectionError, OSError):
                pass
        await asyncio.gather(pipe(cr, uw), pipe(ur, cw))

    async def stop(self):
        self.server.close()
        for cw, uw in self.conns:
            cw.close()
            uw.close()


def _platform(values):
    from shared.config.exceptions import ConfigKeyNotFoundError

    def get(key):
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]
    return get


async def _timed_get(client) -> float:
    t = time.monotonic()
    await client.get("stale-test-key")
    return time.monotonic() - t


async def test_a_silently_dropped_connection_costs_one_socket_timeout_not_thirty_seconds(require_redis):
    proxy = _Proxy()
    port = await proxy.start()
    opts = redis_options(_platform({"redis.socket_timeout_seconds": "1"}))
    client = aioredis.from_url(f"redis://127.0.0.1:{port}", decode_responses=True, **opts)
    try:
        await client.ping()                       # pooled, healthy
        first_proxied = proxy.conns[:]
        proxy.silent = True                       # the network stops carrying it
        # Reconnecting must work, so let new connections through once the old one is detected as dead.
        async def heal():
            await asyncio.sleep(0.5)
            proxy.silent = False
            for cw, uw in first_proxied:          # the dead one stays dead
                cw.close(); uw.close()
        asyncio.create_task(heal())
        elapsed = await _timed_get(client)        # must succeed (retry on a fresh connection), and quickly
        assert elapsed < 5, f"waited {elapsed:.1f}s on a dead connection"
    finally:
        await client.aclose()
        await proxy.stop()
