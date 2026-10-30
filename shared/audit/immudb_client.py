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
        self._credentials: tuple[str, str, str] | None = None   # kept to re-login when the token expires

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def connect(
        self,
        host: str,
        port: int,
        bank_id: str,
        collection: str = "cts_events",
        *,
        username: str,
        password: str,
        database: str = "defaultdb",
    ) -> None:
        """
        Establish gRPC connection to immudb and authenticate.

        Called once at service startup — not async because immudb-py is synchronous.
        username/password are required (no default) — Vault-sourced in production,
        matching security.md's no-hardcoded-credentials rule. immudb requires an
        authenticated session before any set()/get() call succeeds; the real SDK
        manages the resulting token internally after login(), so this only needs
        to run once per connection, not per call.
        """
        try:
            from immudb import ImmudbClient as _SDK  # type: ignore[import]
            self._stub = _SDK(f"{host}:{port}")
            self._stub.login(username, password, database=database.encode())
            self._credentials = (username, password, database)
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
            response = self._call(self._stub.verifiedSet, key, value)
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
            response = self._call(self._stub.verifiedGet, key)
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

    @staticmethod
    def _token_expired(exc: Exception) -> bool:
        text = str(exc).lower()
        return "token has expired" in text or "token validation error" in text

    def _call(self, fn, *args):
        """Run an immudb call; if the session token has expired, log in again once and retry once.

        immudb session tokens expire. Without this a long-running worker or API answered every audit write with
        PERMISSION_DENIED for ever, and cheque workflows stalled on the unlimited audit retry.
        """
        try:
            return fn(*args)
        except Exception as exc:
            if self._credentials is None or not self._token_expired(exc):
                raise
            username, password, database = self._credentials
            log.warning("immudb.token_expired_relogin", bank_id=self._bank_id)
            self._stub.login(username, password, database=database.encode())
            return fn(*args)

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
