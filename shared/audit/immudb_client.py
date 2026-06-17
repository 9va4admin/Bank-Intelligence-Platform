"""
ImmudbClient — append-only audit trail writer for ASTRA.

Every service that writes to YugabyteDB must follow with a call to
ImmudbClient.write_event(). Immudb provides a cryptographic Merkle-tree
guarantee that audit records cannot be silently altered after the fact.

Collections:
  cts_events  — CTS cheque decisions, NGCH filings, vault misses
  ej_events   — EJ normalisation, dispute resolution steps
  (both created per-bank at onboarding time)

Key format:  {bank_id}:{collection}:{sha256(event_id)}
Value:       JSON-serialised event payload (bytes)

Connection is via immudb gRPC stub injected at startup.
The real stub (immudb-py client) is injected by connect();
in tests a MagicMock stub is set directly on _stub.
"""
import hashlib
import json
import time
from typing import Any

import structlog

from shared.audit.exceptions import ImmudbUnavailableError, ImmudbVerificationError

log = structlog.get_logger()


class ImmudbClient:
    def __init__(self) -> None:
        self._stub = None
        self._collection: str = "cts_events"
        self._bank_id: str = ""
        self._ready: bool = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def connect(self, host: str, port: int, bank_id: str, collection: str = "cts_events") -> None:
        """
        Establish gRPC connection to immudb.
        Called once at service startup — not async because immudb-py is synchronous.
        """
        try:
            from immudb import ImmudbClient as _SDK  # type: ignore[import]
            self._stub = _SDK(f"{host}:{port}")
        except Exception as exc:
            raise ImmudbUnavailableError(f"immudb connect failed at {host}:{port}: {exc}") from exc

        self._bank_id = bank_id
        self._collection = collection
        self._ready = True
        log.info("immudb.connected", host=host, port=port, bank_id=bank_id, collection=collection)

    def set_collection(self, collection: str) -> None:
        self._collection = collection

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Write an audit event to immudb.

        payload must include:
          - bank_id  (str) — enforced; prevents cross-bank key collisions
          - event_type (str) — for log correlation

        Returns: {"tx_id": int, "verified": bool, "timestamp": float, "collection": str}
        Raises: ImmudbUnavailableError on connection failure
                ValueError if bank_id missing from payload
                RuntimeError if connect() not called
        """
        self._assert_ready()

        if "bank_id" not in payload:
            raise ValueError("payload must include 'bank_id' for audit isolation")

        event_id = payload.get("event_id", f"{payload['event_type']}:{time.time_ns()}")
        key = self._make_key(payload["bank_id"], self._collection, str(event_id))
        value = json.dumps(payload, default=str).encode()

        try:
            response = self._stub.immudb_database.set(key, value)
        except Exception as exc:
            log.error("immudb.write_failed", event_type=payload.get("event_type"), error=str(exc))
            raise ImmudbUnavailableError(f"immudb write failed: {exc}") from exc

        result = {
            "tx_id": response.id,
            "verified": getattr(response, "verified", True),
            "timestamp": time.time(),
            "collection": self._collection,
            "key": key,
        }
        log.info("immudb.event_written",
                 tx_id=result["tx_id"],
                 event_type=payload.get("event_type"),
                 collection=self._collection)
        return result

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify_event(self, key: bytes) -> bool:
        """
        Cryptographically verify an event record via immudb verified_get.

        Raises ImmudbVerificationError if the record has been tampered with.
        Raises ImmudbUnavailableError if immudb is unreachable.
        """
        self._assert_ready()
        try:
            response = self._stub.immudb_database.verified_get(key)
        except Exception as exc:
            raise ImmudbUnavailableError(f"immudb verify failed: {exc}") from exc

        if not response.verified:
            raise ImmudbVerificationError(
                f"immudb verification failed for key {key!r} — record may be tampered"
            )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_key(self, bank_id: str, collection: str, event_id: str) -> bytes:
        """Deterministic key: {bank_id}:{collection}:{sha256(event_id)}."""
        event_hash = hashlib.sha256(event_id.encode()).hexdigest()
        return f"{bank_id}:{collection}:{event_hash}".encode()

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "ImmudbClient.connect() has not been called. "
                "Call it in the service startup before writing events."
            )
