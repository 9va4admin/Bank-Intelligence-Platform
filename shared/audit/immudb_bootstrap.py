"""Build the synchronous ImmuDB client used by API routers (app.state.immudb_client).

Returns None (logged) when ImmuDB is unconfigured or unreachable: the API keeps serving, and the
routers' guarded audit helpers report the failure instead of writing. The CTS worker builds its own
async-wrapped client (modules/cts/worker_activities.py).
"""
from typing import Any, Optional

import structlog

log = structlog.get_logger()


async def build_sync_immudb_client(config_service: Any, bank_id: str) -> Optional[Any]:
    try:
        from shared.audit.immudb_client import ImmudbClient
        host = config_service.get_platform("immudb.host")
        port = int(config_service.get_platform("immudb.port"))
        username = await config_service.get_secret("immudb.username")
        password = await config_service.get_secret("immudb.password")
        client = ImmudbClient()
        client.connect(host=host, port=port, bank_id=bank_id, username=username, password=password)
        log.info("api_gateway.immudb_client_ready", bank_id=bank_id)
        return client
    except Exception as exc:  # noqa: BLE001
        log.warning("api_gateway.immudb_client_unavailable", bank_id=bank_id, error=str(exc))
        return None
