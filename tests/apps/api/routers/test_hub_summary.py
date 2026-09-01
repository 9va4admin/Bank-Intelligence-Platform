"""
TDD: GET /v1/cts/outward/hub-summary

Tests written BEFORE implementation — must FAIL first.

The endpoint returns a per-branch aggregation of:
  cts.branches JOIN cts.eeh_sessions (today, ACTIVE) JOIN cts.scanner_registrations

Demo-only fields (current_lot, lots_sealed_today, total_held, eeh_latency_ms)
are NOT returned by this endpoint — the frontend guards them with ?. and ?? 0.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext

from apps.api.routers.cts import (
    BranchSessionInfo,
    BranchSessionSummary,
    HubSummaryResponse,
    get_hub_summary,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_ctx(role: str = "ops_manager", bank_id: str = "test-bank") -> UserContext:
    return UserContext(
        user_id="user-001",
        role=Role(role),
        bank_id=bank_id,
        bank_type=BankType.SB,
        permission_level=PermissionLevel.READ_ONLY,
    )


def _make_request(db_pool=None) -> MagicMock:
    req = MagicMock()
    req.app.state.db_pool_cts = db_pool
    return req


# ─── Model tests ──────────────────────────────────────────────────────────────

class TestHubSummaryModels:

    def test_branch_session_info_fields(self):
        info = BranchSessionInfo(
            session_id="sess-001",
            status="ACTIVE",
            opened_at="2026-09-01T03:30:00Z",
            total_uploaded=120,
            total_accepted=118,
            total_rejected=2,
        )
        assert info.total_uploaded == 120
        assert info.total_rejected == 2

    def test_branch_session_summary_with_session(self):
        s = BranchSessionSummary(
            branch_id="BRANCH-ANDHERI-01",
            branch_name="Andheri Branch",
            branch_ifsc="SRCB0001234",
            hub_type="EEH",
            scanner_health="HEALTHY",
            session=BranchSessionInfo(
                session_id="sess-001",
                status="ACTIVE",
                opened_at="2026-09-01T03:30:00Z",
                total_uploaded=50,
                total_accepted=49,
                total_rejected=1,
            ),
        )
        assert s.scanner_health == "HEALTHY"
        assert s.session.total_uploaded == 50

    def test_branch_session_summary_no_session(self):
        s = BranchSessionSummary(
            branch_id="BRANCH-DADAR-02",
            branch_name="Dadar Branch",
            branch_ifsc="SRCB0002345",
            hub_type="EEH",
            scanner_health="OFFLINE",
            session=None,
        )
        assert s.session is None
        assert s.scanner_health == "OFFLINE"

    def test_hub_summary_response_shape(self):
        resp = HubSummaryResponse(
            bank_id="test-bank",
            clearing_date="2026-09-01",
            branches=[],
            total_branches=0,
            active_sessions=0,
            generated_at="2026-09-01T09:00:00Z",
        )
        assert resp.total_branches == 0
        assert resp.active_sessions == 0

    def test_hub_summary_active_sessions_count(self):
        sess = BranchSessionInfo(
            session_id="s1", status="ACTIVE",
            opened_at="2026-09-01T03:30:00Z",
            total_uploaded=10, total_accepted=10, total_rejected=0,
        )
        resp = HubSummaryResponse(
            bank_id="test-bank",
            clearing_date="2026-09-01",
            branches=[
                BranchSessionSummary(
                    branch_id="B1", branch_name="Branch One",
                    branch_ifsc="SRCB0000001", hub_type="EEH",
                    scanner_health="HEALTHY", session=sess,
                ),
                BranchSessionSummary(
                    branch_id="B2", branch_name="Branch Two",
                    branch_ifsc="SRCB0000002", hub_type="EEH",
                    scanner_health="OFFLINE", session=None,
                ),
            ],
            total_branches=2,
            active_sessions=1,
            generated_at="2026-09-01T09:00:00Z",
        )
        assert resp.total_branches == 2
        assert resp.active_sessions == 1


# ─── Endpoint function tests (in-memory path) ─────────────────────────────────

class TestGetHubSummaryInMemory:
    """Tests the in-memory fallback (no DB pool) used in POC/dev."""

    @pytest.mark.asyncio
    async def test_no_db_returns_empty_list(self):
        result = await get_hub_summary(request=_make_request(), ctx=_make_ctx())
        assert isinstance(result, HubSummaryResponse)
        assert result.bank_id == "test-bank"
        assert result.branches == []
        assert result.total_branches == 0
        assert result.active_sessions == 0

    @pytest.mark.asyncio
    async def test_wrong_role_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_hub_summary(
                request=_make_request(),
                ctx=_make_ctx(role="fraud_analyst"),
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ops_reviewer_role_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await get_hub_summary(
                request=_make_request(),
                ctx=_make_ctx(role="ops_reviewer"),
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_bank_it_admin_allowed(self):
        result = await get_hub_summary(
            request=_make_request(),
            ctx=_make_ctx(role="bank_it_admin"),
        )
        assert isinstance(result, HubSummaryResponse)

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_iso(self):
        result = await get_hub_summary(request=_make_request(), ctx=_make_ctx())
        assert "T" in result.generated_at

    @pytest.mark.asyncio
    async def test_clearing_date_is_today(self):
        from datetime import date
        result = await get_hub_summary(request=_make_request(), ctx=_make_ctx())
        assert result.clearing_date == date.today().isoformat()


# ─── Endpoint function tests (DB path) ────────────────────────────────────────

class TestGetHubSummaryWithDB:
    """Tests the live DB query path."""

    def _make_pool(self, rows: list) -> AsyncMock:
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        return pool

    @pytest.mark.asyncio
    async def test_db_path_returns_branches_with_active_session(self):
        rows = [
            {
                "branch_id": "BRANCH-ANDHERI-01",
                "branch_name": "Andheri Branch",
                "branch_ifsc": "SRCB0001234",
                "hub_type": "EEH",
                "scanner_health": "HEALTHY",
                "session_id": "sess-andheri-001",
                "session_status": "ACTIVE",
                "opened_at": datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc),
                "total_uploaded": 240,
                "total_accepted": 235,
                "total_rejected": 5,
            },
        ]
        result = await get_hub_summary(
            request=_make_request(self._make_pool(rows)),
            ctx=_make_ctx(),
        )
        assert result.total_branches == 1
        assert result.active_sessions == 1
        b = result.branches[0]
        assert b.branch_id == "BRANCH-ANDHERI-01"
        assert b.branch_name == "Andheri Branch"
        assert b.scanner_health == "HEALTHY"
        assert b.session is not None
        assert b.session.total_uploaded == 240
        assert b.session.total_rejected == 5

    @pytest.mark.asyncio
    async def test_db_path_branch_without_session_has_none_session(self):
        rows = [
            {
                "branch_id": "BRANCH-DADAR-02",
                "branch_name": "Dadar Branch",
                "branch_ifsc": "SRCB0002345",
                "hub_type": "EEH",
                "scanner_health": "OFFLINE",
                "session_id": None,
                "session_status": None,
                "opened_at": None,
                "total_uploaded": None,
                "total_accepted": None,
                "total_rejected": None,
            },
        ]
        result = await get_hub_summary(
            request=_make_request(self._make_pool(rows)),
            ctx=_make_ctx(),
        )
        assert result.total_branches == 1
        assert result.active_sessions == 0
        assert result.branches[0].session is None

    @pytest.mark.asyncio
    async def test_db_error_raises_500(self):
        from fastapi import HTTPException
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("connection refused"))
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        with pytest.raises(HTTPException) as exc:
            await get_hub_summary(request=_make_request(pool), ctx=_make_ctx())
        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_scanner_health_defaults_to_unknown_when_no_registration(self):
        rows = [
            {
                "branch_id": "BRANCH-BANDRA-03",
                "branch_name": "Bandra Branch",
                "branch_ifsc": "SRCB0003456",
                "hub_type": "EEH",
                "scanner_health": None,
                "session_id": "sess-bandra-001",
                "session_status": "ACTIVE",
                "opened_at": datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc),
                "total_uploaded": 10,
                "total_accepted": 10,
                "total_rejected": 0,
            },
        ]
        result = await get_hub_summary(
            request=_make_request(self._make_pool(rows)),
            ctx=_make_ctx(),
        )
        assert result.branches[0].scanner_health == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_multiple_branches_mixed_state(self):
        rows = [
            {
                "branch_id": "B1", "branch_name": "Branch One",
                "branch_ifsc": "SRCB0000001", "hub_type": "EEH",
                "scanner_health": "HEALTHY",
                "session_id": "sess-001", "session_status": "ACTIVE",
                "opened_at": datetime(2026, 9, 1, 3, 30, tzinfo=timezone.utc),
                "total_uploaded": 50, "total_accepted": 50, "total_rejected": 0,
            },
            {
                "branch_id": "B2", "branch_name": "Branch Two",
                "branch_ifsc": "SRCB0000002", "hub_type": "EEH",
                "scanner_health": "OFFLINE",
                "session_id": None, "session_status": None, "opened_at": None,
                "total_uploaded": None, "total_accepted": None, "total_rejected": None,
            },
        ]
        result = await get_hub_summary(
            request=_make_request(self._make_pool(rows)),
            ctx=_make_ctx(),
        )
        assert result.total_branches == 2
        assert result.active_sessions == 1
        assert result.branches[0].session is not None
        assert result.branches[1].session is None
