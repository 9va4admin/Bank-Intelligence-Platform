"""
TDD: cts.lots — scanning batch lot management

Tests written BEFORE implementation — must FAIL first.

Covers:
  _ensure_open_lot()          — create/find/auto-seal scanning batch lots
  PATCH /v1/cts/outward/lots/{lot_id}/seal
  POST  /v1/cts/outward/lots/seal-all
  submit_outward_scan lot side-effects (total_uploaded + lot tracking)
  Updated hub-summary response includes current_lot + lots_sealed_today + total_held
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext

from apps.api.routers.cts import (
    BranchSessionInfo,
    BranchSessionSummary,
    HubSummaryResponse,
    LotInfo,
    get_hub_summary,
    seal_lot,
    seal_all_lots,
    _ensure_open_lot,
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


def _make_pool(rows_or_row=None, *, fetchrow=None, fetch=None, execute_effect=None):
    """
    Build a mock pool whose conn.fetchrow / conn.fetch / conn.execute can be pre-programmed.
    """
    mock_conn = AsyncMock()
    if fetchrow is not None:
        mock_conn.fetchrow = AsyncMock(side_effect=fetchrow) if callable(fetchrow) else AsyncMock(return_value=fetchrow)
    if fetch is not None:
        mock_conn.fetch = AsyncMock(return_value=fetch)
    if execute_effect is not None:
        mock_conn.execute = AsyncMock(side_effect=execute_effect)
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool, mock_conn


# ─── LotInfo model ────────────────────────────────────────────────────────────

class TestLotInfoModel:

    def test_lot_info_open(self):
        lot = LotInfo(lot_id="LOT-B1-001", filled=12, max=25, status="OPEN")
        assert lot.filled == 12
        assert lot.status == "OPEN"

    def test_lot_info_sealed(self):
        lot = LotInfo(lot_id="LOT-B1-001", filled=25, max=25, status="SEALED")
        assert lot.status == "SEALED"


# ─── _ensure_open_lot ─────────────────────────────────────────────────────────

class TestEnsureOpenLot:

    @pytest.mark.asyncio
    async def test_creates_new_lot_when_none_exists(self):
        """No existing lot → creates LOT with sequence 1, instrument_count=1."""
        mock_conn = AsyncMock()
        # fetchrow: first call (find open lot) → None; second call (max seq) → {"max_seq": 0}
        mock_conn.fetchrow = AsyncMock(side_effect=[None, {"max_seq": 0}])
        mock_conn.execute = AsyncMock(return_value=None)

        lot_id, count = await _ensure_open_lot(
            mock_conn,
            bank_id="test-bank",
            branch_id="BRANCH-01",
            session_id="sess-001",
            clearing_date=date(2026, 9, 2),
        )

        assert count == 1
        assert "BRANCH-01" in lot_id
        # INSERT called once
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_increments_existing_open_lot(self):
        """Existing OPEN lot with 5 instruments → returns same lot_id, count=6."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "lot_id": "LOT-BRANCH-01-20260902-0001",
            "instrument_count": 5,
            "max_instruments": 25,
        })
        mock_conn.execute = AsyncMock(return_value=None)

        lot_id, count = await _ensure_open_lot(
            mock_conn,
            bank_id="test-bank",
            branch_id="BRANCH-01",
            session_id="sess-001",
            clearing_date=date(2026, 9, 2),
        )

        assert lot_id == "LOT-BRANCH-01-20260902-0001"
        assert count == 6

    @pytest.mark.asyncio
    async def test_auto_seals_full_lot_and_creates_next(self):
        """Lot at max (24 of 25) → fill to 25, auto-seal, create lot 2."""
        mock_conn = AsyncMock()
        # First call: find open lot → nearly full
        # Second call (after seal): find open lot → None (sealed)
        # Third call: max seq → 1 (one already exists)
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {"lot_id": "LOT-BRANCH-01-20260902-0001", "instrument_count": 24, "max_instruments": 25},
            None,              # after seal, no open lot
            {"max_seq": 1},    # max sequence
        ])
        mock_conn.execute = AsyncMock(return_value=None)

        lot_id, count = await _ensure_open_lot(
            mock_conn,
            bank_id="test-bank",
            branch_id="BRANCH-01",
            session_id="sess-001",
            clearing_date=date(2026, 9, 2),
        )

        # Should be lot 2
        assert count == 1
        assert "0002" in lot_id
        # execute called at least twice: UPDATE (seal) + INSERT (new lot)
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_respects_custom_max_instruments(self):
        """Custom max_instruments=10 seals at 10, not 25."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=[
            {"lot_id": "LOT-BRANCH-01-20260902-0001", "instrument_count": 9, "max_instruments": 10},
            None,
            {"max_seq": 1},
        ])
        mock_conn.execute = AsyncMock(return_value=None)

        lot_id, count = await _ensure_open_lot(
            mock_conn,
            bank_id="test-bank",
            branch_id="BRANCH-01",
            session_id="sess-001",
            clearing_date=date(2026, 9, 2),
            max_instruments=10,
        )

        assert count == 1
        assert "0002" in lot_id


# ─── Seal lot endpoint ────────────────────────────────────────────────────────

class TestSealLot:

    @pytest.mark.asyncio
    async def test_seal_lot_success(self):
        lot_id = "LOT-BRANCH-01-20260902-0001"
        existing = {"lot_id": lot_id, "bank_id": "test-bank", "status": "OPEN", "instrument_count": 18}
        pool, mock_conn = _make_pool(fetchrow=existing)
        mock_conn.execute = AsyncMock(return_value=None)

        result = await seal_lot(
            lot_id=lot_id,
            request=_make_request(pool),
            ctx=_make_ctx(),
        )

        assert result["lot_id"] == lot_id
        assert result["status"] == "SEALED"
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_seal_lot_not_found_raises_404(self):
        from fastapi import HTTPException
        pool, mock_conn = _make_pool(fetchrow=None)  # not found

        with pytest.raises(HTTPException) as exc:
            await seal_lot(
                lot_id="LOT-MISSING",
                request=_make_request(pool),
                ctx=_make_ctx(),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_seal_already_sealed_raises_409(self):
        from fastapi import HTTPException
        lot_id = "LOT-BRANCH-01-20260902-0001"
        pool, _ = _make_pool(fetchrow={"lot_id": lot_id, "bank_id": "test-bank", "status": "SEALED", "instrument_count": 25})

        with pytest.raises(HTTPException) as exc:
            await seal_lot(lot_id=lot_id, request=_make_request(pool), ctx=_make_ctx())
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_seal_wrong_role_raises_403(self):
        from fastapi import HTTPException
        pool, _ = _make_pool(fetchrow=None)

        with pytest.raises(HTTPException) as exc:
            await seal_lot(
                lot_id="LOT-X",
                request=_make_request(pool),
                ctx=_make_ctx(role="ops_reviewer"),
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_seal_lot_no_db_raises_503(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await seal_lot(lot_id="LOT-X", request=_make_request(None), ctx=_make_ctx())
        assert exc.value.status_code == 503


# ─── Seal-all endpoint ────────────────────────────────────────────────────────

class TestSealAllLots:

    @pytest.mark.asyncio
    async def test_seal_all_returns_sealed_count(self):
        pool, mock_conn = _make_pool(
            fetch=[
                {"lot_id": "LOT-B1-001", "bank_id": "test-bank", "status": "OPEN", "instrument_count": 18},
                {"lot_id": "LOT-B2-001", "bank_id": "test-bank", "status": "OPEN", "instrument_count": 7},
            ]
        )
        mock_conn.execute = AsyncMock(return_value=None)

        result = await seal_all_lots(
            request=_make_request(pool),
            ctx=_make_ctx(),
        )

        assert result["sealed"] == 2
        assert result["bank_id"] == "test-bank"

    @pytest.mark.asyncio
    async def test_seal_all_no_open_lots_returns_zero(self):
        pool, mock_conn = _make_pool(fetch=[])

        result = await seal_all_lots(request=_make_request(pool), ctx=_make_ctx())

        assert result["sealed"] == 0

    @pytest.mark.asyncio
    async def test_seal_all_wrong_role_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await seal_all_lots(request=_make_request(None), ctx=_make_ctx(role="fraud_analyst"))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_seal_all_no_db_raises_503(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await seal_all_lots(request=_make_request(None), ctx=_make_ctx())
        assert exc.value.status_code == 503


# ─── Hub summary with lot data ────────────────────────────────────────────────

class TestHubSummaryWithLots:

    def _make_pool_with_rows(self, rows):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        return pool

    @pytest.mark.asyncio
    async def test_hub_summary_includes_current_lot(self):
        rows = [{
            "branch_id": "B1", "branch_name": "Branch One",
            "branch_ifsc": "SRCB0001", "hub_type": "EEH",
            "scanner_health": "HEALTHY",
            "session_id": "sess-001", "session_status": "ACTIVE",
            "opened_at": datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc),
            "total_uploaded": 43, "total_accepted": 41,
            "total_rejected": 2, "total_held": 0,
            "current_lot_id": "LOT-B1-0002",
            "current_lot_filled": 18,
            "current_lot_max": 25,
            "current_lot_status": "OPEN",
            "lots_sealed_today": 1,
        }]
        result = await get_hub_summary(
            request=_make_request(self._make_pool_with_rows(rows)),
            ctx=_make_ctx(),
        )
        b = result.branches[0]
        assert b.session.total_uploaded == 43
        assert b.session.total_held == 0
        assert b.current_lot is not None
        assert b.current_lot.lot_id == "LOT-B1-0002"
        assert b.current_lot.filled == 18
        assert b.current_lot.max == 25
        assert b.lots_sealed_today == 1

    @pytest.mark.asyncio
    async def test_hub_summary_no_lot_when_branch_has_no_session(self):
        rows = [{
            "branch_id": "B2", "branch_name": "Branch Two",
            "branch_ifsc": "SRCB0002", "hub_type": "EEH",
            "scanner_health": "OFFLINE",
            "session_id": None, "session_status": None,
            "opened_at": None,
            "total_uploaded": None, "total_accepted": None,
            "total_rejected": None, "total_held": None,
            "current_lot_id": None,
            "current_lot_filled": None,
            "current_lot_max": None,
            "current_lot_status": None,
            "lots_sealed_today": 0,
        }]
        result = await get_hub_summary(
            request=_make_request(self._make_pool_with_rows(rows)),
            ctx=_make_ctx(),
        )
        b = result.branches[0]
        assert b.session is None
        assert b.current_lot is None
        assert b.lots_sealed_today == 0
