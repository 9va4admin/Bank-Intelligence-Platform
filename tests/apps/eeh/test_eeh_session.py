"""
Tests for apps/eeh/session.py — EEH Session Manager.

Manages authenticated branch upload sessions. One active session per branch per
clearing date. Sessions are backed by Redis (hot lookup by cert fingerprint) and
YugabyteDB (persistent record, feeds the EEHSession table).

TDD: confirm RED before implementation.
"""

import json
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_eeh_session_manager_importable():
    from apps.eeh.session import EEHSessionManager


def test_eeh_session_importable():
    from apps.eeh.session import EEHSession


def test_session_already_active_error_importable():
    from apps.eeh.session import SessionAlreadyActiveError


def test_session_not_found_error_importable():
    from apps.eeh.session import SessionNotFoundError


def test_cert_revoked_error_importable():
    from apps.eeh.session import CertRevokedError


# ── 2. EEHSession dataclass ───────────────────────────────────────────────────

def test_eeh_session_fields():
    from apps.eeh.session import EEHSession
    s = EEHSession(
        session_id="sess-01",
        bank_id="sb1",
        branch_id="branch-01",
        operator_id="op-007",
        cert_fingerprint="ab:cd:ef:01",
        hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert s.session_id == "sess-01"
    assert s.hub_type == "EEH"


def test_eeh_session_status_defaults_active():
    from apps.eeh.session import EEHSession
    s = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="fp1", hub_type="IEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, 0, tzinfo=timezone.utc),
    )
    assert s.status == "ACTIVE"


def test_eeh_session_to_dict_roundtrip():
    from apps.eeh.session import EEHSession
    s = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="fp1", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, 0, tzinfo=timezone.utc),
    )
    d = s.to_dict()
    assert d["session_id"] == "s1"
    assert "clearing_date" in d


# ── 3. open_session ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_session_creates_redis_entry():
    from apps.eeh.session import EEHSessionManager

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # no existing session
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    mgr = EEHSessionManager(redis=mock_redis, db=mock_db)
    session = await mgr.open_session(
        bank_id="sb1",
        branch_id="branch-01",
        operator_id="op-007",
        cert_fingerprint="ab:cd:ef:01",
        hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        session_ttl_seconds=3600,
    )

    assert session.bank_id == "sb1"
    assert session.branch_id == "branch-01"
    assert session.status == "ACTIVE"
    mock_redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_open_session_raises_if_already_active():
    from apps.eeh.session import EEHSessionManager, SessionAlreadyActiveError, EEHSession

    existing = EEHSession(
        session_id="old-sess", bank_id="sb1", branch_id="branch-01",
        operator_id="op1", cert_fingerprint="old:fp", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(existing.to_dict()))

    mgr = EEHSessionManager(redis=mock_redis, db=AsyncMock())

    with pytest.raises(SessionAlreadyActiveError):
        await mgr.open_session(
            bank_id="sb1", branch_id="branch-01", operator_id="op2",
            cert_fingerprint="new:fp", hub_type="EEH",
            clearing_date=date(2026, 7, 5), session_ttl_seconds=3600,
        )


@pytest.mark.asyncio
async def test_open_session_writes_to_db():
    from apps.eeh.session import EEHSessionManager

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_db = AsyncMock()

    mgr = EEHSessionManager(redis=mock_redis, db=mock_db)
    await mgr.open_session(
        bank_id="sb1", branch_id="b1", operator_id="op1",
        cert_fingerprint="fp1", hub_type="EEH",
        clearing_date=date(2026, 7, 5), session_ttl_seconds=3600,
    )

    mock_db.execute.assert_awaited_once()


# ── 4. resolve_by_cert ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_by_cert_returns_active_session():
    from apps.eeh.session import EEHSessionManager, EEHSession

    active = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="AB:CD:EF:01", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(active.to_dict()))

    mgr = EEHSessionManager(redis=mock_redis, db=AsyncMock())
    session = await mgr.resolve_by_cert("AB:CD:EF:01")
    assert session.session_id == "s1"


@pytest.mark.asyncio
async def test_resolve_by_cert_raises_not_found_on_miss():
    from apps.eeh.session import EEHSessionManager, SessionNotFoundError

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)

    mgr = EEHSessionManager(redis=mock_redis, db=mock_db)

    with pytest.raises(SessionNotFoundError):
        await mgr.resolve_by_cert("unknown:fp")


@pytest.mark.asyncio
async def test_resolve_by_cert_raises_revoked_for_revoked_session():
    from apps.eeh.session import EEHSessionManager, EEHSession, CertRevokedError

    revoked = EEHSession(
        session_id="s-rev", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="BAD:FP", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
        status="REVOKED",
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(revoked.to_dict()))

    mgr = EEHSessionManager(redis=mock_redis, db=AsyncMock())

    with pytest.raises(CertRevokedError):
        await mgr.resolve_by_cert("BAD:FP")


# ── 5. close_session ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_session_updates_redis_status():
    from apps.eeh.session import EEHSessionManager, EEHSession

    active = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="FP1", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(active.to_dict()))
    mock_db = AsyncMock()

    mgr = EEHSessionManager(redis=mock_redis, db=mock_db)
    await mgr.close_session("s1")

    # Redis must be updated with CLOSED status
    mock_redis.set.assert_awaited()
    set_call = mock_redis.set.await_args
    stored = json.loads(set_call[0][1])
    assert stored["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_close_session_updates_db():
    from apps.eeh.session import EEHSessionManager, EEHSession

    active = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="FP1", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(active.to_dict()))
    mock_db = AsyncMock()

    mgr = EEHSessionManager(redis=mock_redis, db=mock_db)
    await mgr.close_session("s1")

    mock_db.execute.assert_awaited()


# ── 6. increment_counters ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_increment_uploaded_counter():
    from apps.eeh.session import EEHSessionManager, EEHSession

    active = EEHSession(
        session_id="s1", bank_id="sb1", branch_id="b1",
        operator_id="op1", cert_fingerprint="FP1", hub_type="EEH",
        clearing_date=date(2026, 7, 5),
        expires_at=datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(active.to_dict()))

    mgr = EEHSessionManager(redis=mock_redis, db=AsyncMock())
    await mgr.record_batch_result(session_id="s1", accepted=3, rejected=1)

    # Redis must be updated with incremented counters
    mock_redis.set.assert_awaited()
    set_call = mock_redis.set.await_args
    stored = json.loads(set_call[0][1])
    assert stored["total_uploaded"] == 4
    assert stored["total_accepted"] == 3
    assert stored["total_rejected"] == 1


# ── 7. Redis key helper ───────────────────────────────────────────────────────

def test_session_redis_key_by_cert():
    from apps.eeh.session import session_cert_key
    key = session_cert_key("AB:CD:EF:01")
    assert key == "eeh:cert:AB:CD:EF:01"


def test_session_redis_key_by_id():
    from apps.eeh.session import session_id_key
    key = session_id_key("sess-01")
    assert key == "eeh:sess:sess-01"
