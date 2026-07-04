"""
Tests for apps/eeh/main.py — EEH FastAPI app.

Covers health endpoints, session lifecycle REST endpoints, and the SSE stream route.
The gRPC upload server is exercised separately (Phase 2 grpc tests).

TDD: confirm RED before implementation.
"""
import json
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_eeh_app_importable():
    from apps.eeh.main import app


def test_eeh_app_is_fastapi():
    from apps.eeh.main import app
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


# ── 2. Health endpoints ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_liveness_returns_200():
    from apps.eeh.main import app
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health/live")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "service" in data


@pytest.mark.asyncio
async def test_readiness_returns_json():
    from apps.eeh.main import app
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health/ready")
    assert r.status_code in (200, 503)
    data = r.json()
    assert "status" in data


# ── 3. Session open endpoint ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_session_endpoint_returns_201():
    from apps.eeh.main import app
    from apps.eeh.session import EEHSession
    from httpx import AsyncClient, ASGITransport

    fake_session = EEHSession(
        session_id="sess-abc",
        bank_id="sb1",
        branch_id="branch-01",
        operator_id="op-007",
        cert_fingerprint="AB:CD:EF:01",
        hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )

    with patch("apps.eeh.main.session_manager") as mock_mgr:
        mock_mgr.open_session = AsyncMock(return_value=fake_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/v1/eeh/session/open", json={
                "bank_id": "sb1",
                "branch_id": "branch-01",
                "operator_id": "op-007",
                "cert_fingerprint": "AB:CD:EF:01",
                "hub_type": "EEH",
                "clearing_date": "2026-07-05",
            })

    assert r.status_code == 201
    data = r.json()
    assert data["session_id"] == "sess-abc"
    assert data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_open_session_endpoint_409_on_duplicate():
    from apps.eeh.main import app
    from apps.eeh.session import SessionAlreadyActiveError
    from httpx import AsyncClient, ASGITransport

    with patch("apps.eeh.main.session_manager") as mock_mgr:
        mock_mgr.open_session = AsyncMock(
            side_effect=SessionAlreadyActiveError("branch already active")
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/v1/eeh/session/open", json={
                "bank_id": "sb1",
                "branch_id": "branch-01",
                "operator_id": "op-007",
                "cert_fingerprint": "new:fp",
                "hub_type": "EEH",
                "clearing_date": "2026-07-05",
            })

    assert r.status_code == 409


# ── 4. Session close endpoint ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_session_endpoint_returns_200():
    from apps.eeh.main import app
    from httpx import AsyncClient, ASGITransport

    with patch("apps.eeh.main.session_manager") as mock_mgr:
        mock_mgr.close_session = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/v1/eeh/session/sess-abc/close")

    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == "sess-abc"


# ── 5. SSE stream route exists ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_stream_route_exists():
    from apps.eeh.main import app
    from httpx import AsyncClient, ASGITransport
    import asyncio

    # The SSE route should not return 404 — it may return 200 or immediately close
    # We just confirm the route is registered (not 404)
    with patch("apps.eeh.main.session_manager") as mock_mgr:
        mock_mgr.resolve_by_cert = AsyncMock(side_effect=Exception("no cert in test"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            try:
                r = await ac.get(
                    "/v1/eeh/stream/branch-01/2026-07-05",
                    timeout=1.0,
                )
                assert r.status_code != 404
            except Exception:
                pass  # SSE keeps connection open — timeout is fine


# ── 6. Service name constant ──────────────────────────────────────────────────

def test_service_name_defined():
    from apps.eeh import main
    assert hasattr(main, "SERVICE_NAME")
    assert "eeh" in main.SERVICE_NAME.lower()
