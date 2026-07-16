"""
AsyncImmudbWriter -- async adapter around the sync ImmudbClient.

ImmudbClient.write_event() is synchronous (immudb-py has no asyncio support)
and writes to whatever collection was set at connect-time, not per call.
Every real caller in this codebase (write_audit.py, and shared/audit's
stream consumer) expects an async .write(collection=, event_type=, bank_id=,
instrument_id=None, payload=) that can target a different collection per
call -- this bridges that gap. Without it, the real ImmudbClient returned by
worker_activities._build_immudb_client() has no .write() method at all, so
the first real Temporal execution to reach write_audit() would crash with
AttributeError.

set_collection() + write_event() run inside the SAME asyncio.to_thread()
call so concurrent writes to different collections on one ImmudbClient
instance can never interleave and write to the wrong collection.
"""
import asyncio
from typing import Any, Optional

from shared.audit.immudb_client import ImmudbClient


class AsyncImmudbWriter:
    def __init__(self, client: ImmudbClient) -> None:
        self._client = client

    async def write(
        self,
        *,
        collection: str,
        event_type: str,
        bank_id: str,
        payload: dict[str, Any],
        instrument_id: Optional[str] = None,
    ) -> str:
        def _write_sync() -> dict:
            self._client.set_collection(collection)
            write_payload: dict[str, Any] = {
                "event_type": event_type,
                "bank_id": bank_id,
                "payload": payload,
            }
            if instrument_id is not None:
                write_payload["instrument_id"] = instrument_id
            return self._client.write_event(write_payload)

        result = await asyncio.to_thread(_write_sync)
        return str(result["tx_id"])
