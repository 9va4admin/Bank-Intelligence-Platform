"""
EEH gRPC Service — EEHServicer implementation.

The servicer methods are plain Python async functions that accept duck-typed
request objects (matching proto-generated types in production, MagicMock in tests).
Return types are simple dataclasses that mirror the proto message fields.

In production this is wired into a grpcio.aio server via create_grpc_server().
In test, the servicer is called directly without gRPC infrastructure.

SQL used in this file:
  cts.lots         — read lot status + instrument_count + clearing_session_id
  cts.mismatch_queue — read HELD items, update resolution status
  cts.eeh_sessions — read counters for session status
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional, AsyncIterator

log = structlog.get_logger()


# ── Response dataclasses (mirror proto message fields) ─────────────────────────

@dataclass
class LotSealAck:
    lot_id: str
    status: str                    # SEALED | ALREADY_SEALED | LOT_NOT_FOUND
    instrument_count: int = 0
    clearing_session: str = ""


@dataclass
class ResolutionAck:
    mismatch_id: str
    status: str                    # RESOLVED | NOT_FOUND | ALREADY_RESOLVED
    scan_id: str = ""


@dataclass
class SessionStatus:
    session_id: str
    branch_id: str = ""
    status: str = "ACTIVE"
    clearing_date: str = ""
    total_uploaded: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_held: int = 0
    current_lot_id: str = ""
    expires_at: str = ""


@dataclass
class MismatchItemMsg:
    mismatch_id: str
    scan_id: str = ""
    held_at: str = ""
    mismatch_fields: list[str] = field(default_factory=list)
    scanner_amount: str = ""
    vision_amount: str = ""
    lot_id: str = ""


@dataclass
class ChequeAck:
    scan_id: str
    status: str      # ACCEPTED | REJECTED | HELD | SESSION_NOT_FOUND | INVALID_PAYLOAD
    lot_id: str = ""
    reason: str = ""


# ── SQL ─────────────────────────────────────────────────────────────────────────

_FETCH_LOT_SQL = """
SELECT lot_id, status, instrument_count, clearing_session_id
FROM cts.lots
WHERE lot_id = $1
"""

_SEAL_LOT_SQL = """
UPDATE cts.lots
SET status = 'SEALED', sealed_at = NOW(), sealed_by = $2, updated_at = NOW()
WHERE lot_id = $1
"""

_FETCH_MISMATCH_SQL = """
SELECT mismatch_id, status, scan_id, mismatch_fields, held_at,
       vision_finding, scanner_data, lot_id
FROM cts.mismatch_queue
WHERE mismatch_id = $1
"""

_FETCH_HELD_MISMATCHES_SQL = """
SELECT mismatch_id, scan_id, held_at, mismatch_fields,
       vision_finding, scanner_data, lot_id
FROM cts.mismatch_queue
WHERE branch_id = $1 AND status = $2
ORDER BY held_at ASC
"""

_RESOLVE_MISMATCH_SQL = """
UPDATE cts.mismatch_queue
SET status = $2, resolved_at = NOW(), resolved_by = $3, updated_at = NOW()
WHERE mismatch_id = $1
"""

_FETCH_SESSION_SQL = """
SELECT session_id, bank_id, branch_id, operator_id, cert_fingerprint,
       hub_type, status, clearing_date, opened_at, expires_at,
       total_uploaded, total_accepted, total_rejected
FROM cts.eeh_sessions
WHERE session_id = $1
"""


# ── EEHServicer ─────────────────────────────────────────────────────────────────

class EEHServicer:
    """
    Implements the EEHService RPC methods as plain async Python.

    Dependencies are injected so servicer methods are fully unit-testable
    without a running gRPC server.
    """

    def __init__(
        self,
        *,
        session_manager: Any,
        sse_publisher: Any,
        db: Any,
        kafka_producer: Optional[Any] = None,
        minio_store: Optional[Any] = None,
    ) -> None:
        self._session_manager = session_manager
        self._sse = sse_publisher
        self._db = db
        self._kafka_producer = kafka_producer
        self._minio_store = minio_store

    # ── SealLot ───────────────────────────────────────────────────────────────

    async def SealLot(self, request: Any, context: Any) -> LotSealAck:
        """
        Supervisor seals a lot, preventing further instrument additions.
        Triggers BatchEndorsementWorkflow via the Kafka cts.outward.lot.sealed topic.
        """
        row = await self._db.fetchrow(_FETCH_LOT_SQL, request.lot_id)
        if row is None:
            return LotSealAck(lot_id=request.lot_id, status="LOT_NOT_FOUND")

        if row["status"] == "SEALED":
            return LotSealAck(
                lot_id=row["lot_id"],
                status="ALREADY_SEALED",
                instrument_count=row["instrument_count"],
                clearing_session=row.get("clearing_session_id", "") or "",
            )

        await self._db.execute(_SEAL_LOT_SQL, request.lot_id, request.sealed_by)

        log.info(
            "eeh.lot_sealed",
            lot_id=request.lot_id,
            sealed_by=request.sealed_by,
            instrument_count=row["instrument_count"],
        )
        return LotSealAck(
            lot_id=row["lot_id"],
            status="SEALED",
            instrument_count=row["instrument_count"],
            clearing_session=row.get("clearing_session_id", "") or "",
        )

    # ── GetMismatchQueue ──────────────────────────────────────────────────────

    async def GetMismatchQueue(
        self, request: Any, context: Any
    ) -> AsyncIterator[MismatchItemMsg]:
        """Streams HELD mismatch items for a branch to the supervisor portal."""
        filter_status = getattr(request, "status", "HELD") or "HELD"
        rows = await self._db.fetch(
            _FETCH_HELD_MISMATCHES_SQL, request.branch_id, filter_status
        )
        for row in rows:
            import json
            vision = row.get("vision_finding") or {}
            scanner = row.get("scanner_data") or {}
            if isinstance(vision, str):
                vision = json.loads(vision)
            if isinstance(scanner, str):
                scanner = json.loads(scanner)

            yield MismatchItemMsg(
                mismatch_id=row["mismatch_id"],
                scan_id=row.get("scan_id", ""),
                held_at=row["held_at"].isoformat() if row.get("held_at") else "",
                mismatch_fields=row.get("mismatch_fields") or [],
                scanner_amount=scanner.get("amount_figures", ""),
                vision_amount=vision.get("amount_figures", {}).get("value", ""),
                lot_id=row.get("lot_id", "") or "",
            )

    # ── ResolveMismatch ───────────────────────────────────────────────────────

    async def ResolveMismatch(self, request: Any, context: Any) -> ResolutionAck:
        """
        Supervisor resolves a held mismatch item.
        action = 0 (GO_AHEAD): proceed to lot assignment
        action = 1 (REJECTED): return instrument to drawer
        """
        row = await self._db.fetchrow(_FETCH_MISMATCH_SQL, request.mismatch_id)
        if row is None:
            return ResolutionAck(mismatch_id=request.mismatch_id, status="NOT_FOUND")

        if row["status"] != "HELD":
            return ResolutionAck(
                mismatch_id=request.mismatch_id,
                status="ALREADY_RESOLVED",
                scan_id=row.get("scan_id", ""),
            )

        # action 0 = GO_AHEAD, action 1 = REJECTED
        action = getattr(request, "action", 0)
        new_status = "GO_AHEAD" if action == 0 else "REJECTED"

        await self._db.execute(
            _RESOLVE_MISMATCH_SQL,
            request.mismatch_id,
            new_status,
            request.resolved_by,
        )

        log.info(
            "eeh.mismatch_resolved",
            mismatch_id=request.mismatch_id,
            new_status=new_status,
            resolved_by=request.resolved_by,
        )
        return ResolutionAck(
            mismatch_id=request.mismatch_id,
            status="RESOLVED",
            scan_id=row.get("scan_id", ""),
        )

    # ── GetSessionStatus ──────────────────────────────────────────────────────

    async def GetSessionStatus(self, request: Any, context: Any) -> SessionStatus:
        """Returns real-time session counters for the branch dashboard."""
        row = await self._db.fetchrow(_FETCH_SESSION_SQL, request.session_id)
        if row is None:
            return SessionStatus(session_id=request.session_id, status="NOT_FOUND")

        return SessionStatus(
            session_id=row["session_id"],
            branch_id=row.get("branch_id", ""),
            status=row.get("status", "ACTIVE"),
            clearing_date=row["clearing_date"].isoformat()
            if row.get("clearing_date") else "",
            total_uploaded=row.get("total_uploaded", 0),
            total_accepted=row.get("total_accepted", 0),
            total_rejected=row.get("total_rejected", 0),
            expires_at=row["expires_at"].isoformat() if row.get("expires_at") else "",
        )

    # ── UploadCheque (streaming RPC) ─────────────────────────────────────────

    _INSERT_EEH_SCAN_SQL = """
        INSERT INTO cts.eeh_sessions (
            total_uploaded, total_accepted, total_rejected, updated_at
        )
        SELECT total_uploaded + 1,
               CASE WHEN $2 = 'ACCEPTED' THEN total_accepted + 1 ELSE total_accepted END,
               CASE WHEN $2 = 'REJECTED' THEN total_rejected + 1 ELSE total_rejected END,
               NOW()
        FROM cts.eeh_sessions WHERE session_id = $1
        RETURNING session_id
    """

    async def UploadCheque(
        self, request_iterator: Any, context: Any
    ) -> AsyncIterator[ChequeAck]:
        """
        Bidirectional streaming RPC — receives ChequePayload stream from branch,
        validates session, routes each cheque to OutwardScanWorkflow via Kafka,
        and yields a ChequeAck per item.

        Each ChequePayload is expected to have:
            session_id, scan_id, lot_id, image_data (bytes)

        OutwardScanWorkflow is triggered via the cts.outward.scanned.{bank_id}
        Kafka topic (KEDA auto-scales the worker). The gRPC response is
        ACCEPTED immediately — actual workflow outcome tracked via Temporal.
        """
        async for payload in request_iterator:
            scan_id: str = getattr(payload, "scan_id", "")
            session_id: str = getattr(payload, "session_id", "")
            lot_id: str = getattr(payload, "lot_id", "")

            if not scan_id or not session_id:
                yield ChequeAck(
                    scan_id=scan_id or "unknown",
                    status="INVALID_PAYLOAD",
                    reason="scan_id and session_id are required",
                )
                continue

            # Validate session exists and is active
            try:
                row = await self._db.fetchrow(_FETCH_SESSION_SQL, session_id)
            except Exception as exc:
                log.error("eeh.upload.db_error", scan_id=scan_id, error=str(exc))
                yield ChequeAck(scan_id=scan_id, status="REJECTED", reason="db_error")
                continue

            if row is None:
                yield ChequeAck(scan_id=scan_id, status="SESSION_NOT_FOUND", lot_id=lot_id)
                continue

            if row["status"] != "ACTIVE":
                yield ChequeAck(
                    scan_id=scan_id,
                    status="REJECTED",
                    lot_id=lot_id,
                    reason=f"session_status={row['status']}",
                )
                continue

            # Publish to cts.outward.scanned.{bank_id} — OutwardScanWorkflow picks it up
            bank_id: str = row["bank_id"]
            branch_id: str = row.get("branch_id", "")

            # Upload images to MinIO (if store injected) — graceful degradation on failure
            image_front_url = ""
            image_rear_url = ""
            if self._minio_store is not None:
                image_front = getattr(payload, "image_front", b"") or b""
                image_rear = getattr(payload, "image_rear", b"") or b""
                bucket = "cts-cheques"
                prefix = f"{bank_id}/outward/{scan_id}"
                try:
                    if image_front:
                        front_key = await self._minio_store.upload_bytes(
                            bucket, f"{prefix}/front.tif", image_front, "image/tiff"
                        )
                        image_front_url = f"minio://{bucket}/{front_key}"
                    if image_rear:
                        rear_key = await self._minio_store.upload_bytes(
                            bucket, f"{prefix}/rear.tif", image_rear, "image/tiff"
                        )
                        image_rear_url = f"minio://{bucket}/{rear_key}"
                except Exception as exc:
                    log.warning(
                        "eeh.upload.minio_failed",
                        scan_id=scan_id,
                        bank_id=bank_id,
                        error=str(exc),
                    )

            # Publish BatchScannedEvent to Kafka (if producer injected)
            if self._kafka_producer is not None:
                import json as _json
                import uuid as _uuid
                kafka_topic = f"cts.outward.scanned.{bank_id}"
                scan_entry: dict = {"scan_id": scan_id}
                if image_front_url:
                    scan_entry["image_front_url"] = image_front_url
                if image_rear_url:
                    scan_entry["image_rear_url"] = image_rear_url
                event_payload = _json.dumps({
                    "schema_version": "1.0",
                    "event_id": f"EEH-{_uuid.uuid4().hex[:12].upper()}",
                    "bank_id": bank_id,
                    "branch_id": branch_id,
                    "pu_id": "",
                    "batch_id": session_id,
                    "instrument_count": 1,
                    "scan_ids": [scan_id],
                    "oem": "EEH_GRPC",
                    "per_scan_data": [scan_entry],
                })
                try:
                    await self._kafka_producer.send(
                        kafka_topic,
                        value=event_payload.encode("utf-8"),
                        key=f"{bank_id}:{branch_id}".encode("utf-8"),
                    )
                except Exception as exc:
                    log.warning(
                        "eeh.upload.kafka_failed",
                        scan_id=scan_id,
                        bank_id=bank_id,
                        error=str(exc),
                    )

            try:
                if self._sse is not None:
                    await self._sse.publish(
                        event_type="cheque_uploaded",
                        bank_id=bank_id,
                        data={
                            "scan_id": scan_id,
                            "session_id": session_id,
                            "lot_id": lot_id,
                            "branch_id": branch_id,
                        },
                    )
            except Exception as exc:
                log.warning("eeh.upload.sse_failed", scan_id=scan_id, error=str(exc))

            log.info(
                "eeh.cheque_uploaded",
                scan_id=scan_id,
                session_id=session_id,
                lot_id=lot_id,
                bank_id=bank_id,
            )
            yield ChequeAck(scan_id=scan_id, status="ACCEPTED", lot_id=lot_id)


# ── Server factory ─────────────────────────────────────────────────────────────

def create_grpc_server(
    *,
    servicer: EEHServicer,
    port: int = 50051,
    max_workers: int = 10,
) -> Any:
    """
    Creates and returns a configured gRPC server.

    In production (grpcio available): returns a real aio.server bound to port.
    In test / dev without grpcio: returns a ServerStub for inspection.
    """
    try:
        import grpc
        from grpc import aio as grpc_aio
        import asyncio

        # grpc_aio.server() requires a running event loop (async context).
        # In sync call sites (tests, Helm health checks) fall back to stub.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return _ServerStub(servicer=servicer, port=port)

        server = grpc_aio.server(
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),   # 50 MB (TIFF images)
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
            ]
        )
        server.add_insecure_port(f"[::]:{port}")
        log.info("eeh.grpc_server_created", port=port)
        return server
    except ImportError:
        # grpcio not installed (test environment) — return stub
        return _ServerStub(servicer=servicer, port=port)


class _ServerStub:
    """Minimal server stub for environments without grpcio installed."""

    def __init__(self, *, servicer: EEHServicer, port: int) -> None:
        self.servicer = servicer
        self.port = port
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self, grace: float = 5.0) -> None:
        self._running = False

    async def wait_for_termination(self) -> None:
        pass
