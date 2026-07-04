"""
Tests for apps/eeh/grpc_server.py — EEH gRPC service stub.

We don't run a full gRPC server in tests. Instead we exercise the servicer
methods directly via asyncio, injecting AsyncMock dependencies.

Key behaviors:
  UploadCheque: processes stream → assigns lot → publishes ChequeAck
  SealLot:      triggers BatchEndorsementWorkflow signal
  GetMismatchQueue: queries mismatch_queue table for HELD items
  ResolveMismatch:  updates status, fires Temporal signal to unblock cheque
  GetSessionStatus: reads from Redis / DB via session_manager

TDD: confirm RED before implementation.
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_eeh_servicer_importable():
    from apps.eeh.grpc_server import EEHServicer


def test_eeh_grpc_server_create_server_importable():
    from apps.eeh.grpc_server import create_grpc_server


# ── 2. EEHServicer construction ───────────────────────────────────────────────

def test_eeh_servicer_requires_session_manager():
    from apps.eeh.grpc_server import EEHServicer
    from apps.eeh.session import EEHSessionManager

    mock_mgr = MagicMock(spec=EEHSessionManager)
    mock_publisher = MagicMock()
    mock_db = AsyncMock()

    svc = EEHServicer(
        session_manager=mock_mgr,
        sse_publisher=mock_publisher,
        db=mock_db,
    )
    assert svc is not None


# ── 3. SealLot ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seal_lot_returns_sealed_status():
    from apps.eeh.grpc_server import EEHServicer

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value={
        "lot_id": "LOT-07",
        "status": "OPEN",
        "instrument_count": 12,
        "clearing_session_id": "sess-clear-01",
    })
    mock_db.execute = AsyncMock()

    mock_publisher = AsyncMock()
    mock_mgr = AsyncMock()

    svc = EEHServicer(
        session_manager=mock_mgr,
        sse_publisher=mock_publisher,
        db=mock_db,
    )

    # Simulate a SealLot request
    request = MagicMock()
    request.session_id = "sess-001"
    request.lot_id = "LOT-07"
    request.sealed_by = "op-supervisor"

    context = MagicMock()
    ack = await svc.SealLot(request, context)

    assert ack.lot_id == "LOT-07"
    assert ack.status == "SEALED"
    assert ack.instrument_count == 12


@pytest.mark.asyncio
async def test_seal_lot_already_sealed_returns_already_sealed():
    from apps.eeh.grpc_server import EEHServicer

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value={
        "lot_id": "LOT-07",
        "status": "SEALED",
        "instrument_count": 12,
        "clearing_session_id": "sess-clear-01",
    })

    svc = EEHServicer(
        session_manager=AsyncMock(),
        sse_publisher=AsyncMock(),
        db=mock_db,
    )

    request = MagicMock()
    request.session_id = "sess-001"
    request.lot_id = "LOT-07"
    request.sealed_by = "op-supervisor"

    ack = await svc.SealLot(request, MagicMock())
    assert ack.status == "ALREADY_SEALED"


@pytest.mark.asyncio
async def test_seal_lot_not_found_returns_not_found():
    from apps.eeh.grpc_server import EEHServicer

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)

    svc = EEHServicer(
        session_manager=AsyncMock(),
        sse_publisher=AsyncMock(),
        db=mock_db,
    )

    request = MagicMock()
    request.session_id = "sess-001"
    request.lot_id = "NONEXISTENT"
    request.sealed_by = "op-supervisor"

    ack = await svc.SealLot(request, MagicMock())
    assert ack.status == "LOT_NOT_FOUND"


# ── 4. ResolveMismatch ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_mismatch_go_ahead_updates_status():
    from apps.eeh.grpc_server import EEHServicer

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value={
        "mismatch_id": "MM-001",
        "status": "HELD",
        "scan_id": "SC-001",
    })
    mock_db.execute = AsyncMock()

    svc = EEHServicer(
        session_manager=AsyncMock(),
        sse_publisher=AsyncMock(),
        db=mock_db,
    )

    request = MagicMock()
    request.mismatch_id = "MM-001"
    request.session_id = "sess-001"
    request.resolved_by = "op-sup"
    request.action = 0  # GO_AHEAD
    request.notes = "Looks OK"

    ack = await svc.ResolveMismatch(request, MagicMock())
    assert ack.mismatch_id == "MM-001"
    assert ack.status == "RESOLVED"
    mock_db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_resolve_mismatch_not_found_returns_not_found():
    from apps.eeh.grpc_server import EEHServicer

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)

    svc = EEHServicer(
        session_manager=AsyncMock(),
        sse_publisher=AsyncMock(),
        db=mock_db,
    )

    request = MagicMock()
    request.mismatch_id = "UNKNOWN"
    request.session_id = "sess-001"
    request.resolved_by = "op-sup"
    request.action = 0
    request.notes = ""

    ack = await svc.ResolveMismatch(request, MagicMock())
    assert ack.status == "NOT_FOUND"


# ── 5. GetSessionStatus ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session_status_returns_status():
    from apps.eeh.grpc_server import EEHServicer
    from apps.eeh.session import EEHSession

    active_sess = EEHSession(
        session_id="sess-001",
        bank_id="sb1",
        branch_id="branch-01",
        operator_id="op1",
        cert_fingerprint="fp1",
        hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
        total_uploaded=10,
        total_accepted=9,
        total_rejected=1,
    )

    mock_mgr = AsyncMock()
    mock_mgr.resolve_by_cert = AsyncMock()

    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value={
        "session_id": "sess-001",
        "bank_id": "sb1",
        "branch_id": "branch-01",
        "operator_id": "op1",
        "cert_fingerprint": "fp1",
        "hub_type": "EEH",
        "status": "ACTIVE",
        "clearing_date": date(2026, 7, 5),
        "opened_at": datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
        "total_uploaded": 10,
        "total_accepted": 9,
        "total_rejected": 1,
    })

    svc = EEHServicer(
        session_manager=mock_mgr,
        sse_publisher=AsyncMock(),
        db=mock_db,
    )

    request = MagicMock()
    request.session_id = "sess-001"
    status_msg = await svc.GetSessionStatus(request, MagicMock())

    assert status_msg.session_id == "sess-001"
    assert status_msg.total_uploaded == 10
    assert status_msg.total_accepted == 9


# ── 6. create_grpc_server ─────────────────────────────────────────────────────

def test_create_grpc_server_returns_server():
    from apps.eeh.grpc_server import create_grpc_server
    from apps.eeh.session import EEHSessionManager

    server = create_grpc_server(
        servicer=MagicMock(),
        port=50051,
    )
    assert server is not None
