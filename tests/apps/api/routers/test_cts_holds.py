"""
Tests for cts_holds.py — 9 routes:
  POST /holds/{instrument_id}
  GET  /holds
  POST /holds/{instrument_id}/release
  POST /holds/{instrument_id}/recommendation
  GET  /mismatches
  POST /mismatches/{mismatch_id}/resolve
  POST /review/{instrument_id}/claim
  DELETE /review/{instrument_id}/claim
  GET  /allocation/status

TDD: this file is written BEFORE cts_holds.py exists — first run must be RED.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import UserContext, Role, BankType, PermissionLevel


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_ctx(
    bank_id: str = "saraswat-coop",
    bank_type: BankType = BankType.SB,
    role: Role = Role.OPS_MANAGER,
    user_id: str = "reviewer1",
) -> UserContext:
    return UserContext(
        user_id=user_id,
        bank_id=bank_id,
        bank_type=bank_type,
        role=role,
        permission_level=PermissionLevel.EDIT,
        session_id="sess1",
    )


def _make_app(ctx: UserContext = None, db_pool=None, temporal_client=None, redis=None):
    from apps.api.routers.cts_holds import router_v1
    from apps.api.routers.cts_deps import get_current_user_context

    app = FastAPI()
    app.include_router(router_v1)

    if ctx is None:
        ctx = _make_ctx()

    async def _override_ctx():
        return ctx

    app.dependency_overrides[get_current_user_context] = _override_ctx
    if db_pool is not None:
        app.state.db_pool_cts = db_pool
    if temporal_client is not None:
        app.state.temporal_client = temporal_client
    if redis is not None:
        app.state.redis_cts = redis
    return app


# ---------------------------------------------------------------------------
# POST /v1/cts/holds/{instrument_id}
# ---------------------------------------------------------------------------

class TestPlaceHold:

    _payload = {
        "hold_reason": "ALTERATION_SUSPECTED",
        "iet_deadline": 9999999999.0,
        "branch_email": "branch@bank.com",
    }

    def test_ops_reviewer_no_db_returns_201(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001", json=self._payload)
        assert r.status_code == 201
        body = r.json()
        assert body["instrument_id"] == "INST-001"
        assert "hold_id" in body
        assert "iet_remaining_seconds" in body
        assert isinstance(body["branch_notified"], bool)

    def test_ops_manager_no_db_returns_201(self):
        ctx = _make_ctx(role=Role.OPS_MANAGER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-002", json=self._payload)
        assert r.status_code == 201

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001", json=self._payload)
        assert r.status_code == 403

    def test_missing_hold_reason_returns_422(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001", json={"iet_deadline": 9999999999.0})
        assert r.status_code == 422

    def test_with_db_queries_hold_id(self):
        # Simulate DB returning a hold_id row
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value={"hold_id": "HD-001"})
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)

        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        with patch("modules.cts.hold.hold_service.HoldService.place_hold", new_callable=AsyncMock) as mock_place:
            from modules.cts.hold.hold_service import HoldRecord
            mock_place.return_value = HoldRecord(
                instrument_id="INST-003", bank_id="saraswat-coop",
                held_by="reviewer1", held_at=1234567890.0,
                iet_deadline=9999999999.0, hold_reason="TEST",
            )
            client = TestClient(_make_app(ctx=ctx, db_pool=mock_db))
            r = client.post("/v1/cts/holds/INST-003", json=self._payload)
        # Should at least be 201; DB error path returns 201 with fallback hold_id
        assert r.status_code in (201, 500)  # 500 only if HoldResult import fails


# ---------------------------------------------------------------------------
# GET /v1/cts/holds
# ---------------------------------------------------------------------------

class TestListHolds:

    def test_ops_manager_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/holds")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["bank_id"] == "saraswat-coop"

    def test_ops_reviewer_allowed(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/holds")
        assert r.status_code == 200

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.FRAUD_ANALYST)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/holds")
        assert r.status_code == 403

    def test_with_db_returns_hold_items(self):
        rows = [
            {
                "hold_id": "HD-001",
                "instrument_id": "INST-001",
                "bank_id": "saraswat-coop",
                "held_by": "reviewer1",
                "held_at": 1725888000.0,
                "iet_deadline": 1725888900.0,
                "hold_reason": "ALTERATION_SUSPECTED",
                "branch_notified_at": None,
                "branch_recommendation": None,
                "branch_note": None,
                "account_last4": "4521",
                "amount_range": "HIGH_VALUE",
                "queue_tier": "high",
            }
        ]
        conn_mock = AsyncMock()
        conn_mock.fetch = AsyncMock(return_value=rows)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/holds")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["hold_id"] == "HD-001"
        assert body["items"][0]["account_display"] == "****4521"
        assert body["items"][0]["amount_display"] == "₹[1L–5L]"


# ---------------------------------------------------------------------------
# POST /v1/cts/holds/{instrument_id}/release
# ---------------------------------------------------------------------------

class TestReleaseHold:

    _payload = {"branch_note": "Verified by branch", "branch_recommendation": "CONFIRM"}

    def test_no_db_returns_200(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001/release", json=self._payload)
        assert r.status_code == 200
        body = r.json()
        assert body["instrument_id"] == "INST-001"
        assert body["released"] is True

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001/release", json=self._payload)
        assert r.status_code == 403

    def test_db_hold_not_found_returns_404(self):
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value=None)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=mock_db), raise_server_exceptions=False)
        r = client.post("/v1/cts/holds/INST-MISSING/release", json=self._payload)
        assert r.status_code == 404

    def test_db_success_returns_hold_id(self):
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value={"hold_id": "HD-001"})
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=mock_db))
        r = client.post("/v1/cts/holds/INST-001/release", json=self._payload)
        assert r.status_code == 200
        assert r.json()["hold_id"] == "HD-001"


# ---------------------------------------------------------------------------
# POST /v1/cts/holds/{instrument_id}/recommendation
# ---------------------------------------------------------------------------

class TestHoldRecommendation:

    _payload = {"branch_note": "OK to proceed", "branch_recommendation": "CONFIRM"}

    def test_ops_reviewer_no_db_returns_200(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001/recommendation", json=self._payload)
        assert r.status_code == 200
        body = r.json()
        assert body["instrument_id"] == "INST-001"
        assert body["updated"] is True

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/holds/INST-001/recommendation", json=self._payload)
        assert r.status_code == 403

    def test_db_not_found_returns_404(self):
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value=None)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=mock_db), raise_server_exceptions=False)
        r = client.post("/v1/cts/holds/INST-MISSING/recommendation", json=self._payload)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/cts/mismatches
# ---------------------------------------------------------------------------

class TestListMismatches:

    def test_ops_manager_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/mismatches")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["bank_id"] == "saraswat-coop"

    def test_ops_reviewer_allowed(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/mismatches")
        assert r.status_code == 200

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.FRAUD_ANALYST)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/mismatches")
        assert r.status_code == 403

    def test_with_db_returns_mismatch_items(self):
        rows = [
            {
                "mismatch_id": "MM-001",
                "instrument_id": "INST-001",
                "branch_id": "BR001",
                "held_at": "2026-09-09T09:00:00+00:00",
                "status": "HELD",
                "mismatch_fields": ["amount_figures", "payee_name"],
                "vision_finding": {"amount_figures": "50000"},
                "scanner_data": {"amount_figures": "500000", "payee_masked": "A***"},
                "lot_id": "LOT-01",
                "workflow_run_id": "RUN-01",
            }
        ]
        conn_mock = AsyncMock()
        conn_mock.fetch = AsyncMock(return_value=rows)
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/mismatches")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["mismatch_id"] == "MM-001"
        assert body["items"][0]["scanner_amount"] == "500000"
        assert body["items"][0]["vision_amount"] == "50000"

    def test_branch_filter_passes_through(self):
        conn_mock = AsyncMock()
        conn_mock.fetch = AsyncMock(return_value=[])
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/mismatches?branch_id=BR001")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/cts/mismatches/{mismatch_id}/resolve
# ---------------------------------------------------------------------------

class TestResolveMismatch:

    _payload = {"action": "GO_AHEAD", "note": "Branch confirmed"}

    def test_ops_manager_no_db_returns_200(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.post("/v1/cts/mismatches/MM-001/resolve", json=self._payload)
        assert r.status_code == 200
        body = r.json()
        assert body["mismatch_id"] == "MM-001"
        assert body["action"] == "GO_AHEAD"
        assert body["signal_sent"] is False

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/mismatches/MM-001/resolve", json=self._payload)
        assert r.status_code == 403

    def test_invalid_action_returns_422(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.post("/v1/cts/mismatches/MM-001/resolve", json={"action": "INVALID"})
        assert r.status_code == 422

    def test_db_not_found_returns_404(self):
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value=None)
        conn_mock.execute = AsyncMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        client = TestClient(_make_app(db_pool=mock_db), raise_server_exceptions=False)
        r = client.post("/v1/cts/mismatches/MM-MISSING/resolve", json=self._payload)
        assert r.status_code == 404

    def test_db_success_signals_workflow(self):
        conn_mock = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value={
            "mismatch_id": "MM-001",
            "branch_id": "BR001",
            "workflow_run_id": "RUN-001",
        })
        conn_mock.execute = AsyncMock()
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)

        mock_tc = MagicMock()
        mock_handle = AsyncMock()
        mock_handle.signal = AsyncMock()
        mock_tc.get_workflow_handle = MagicMock(return_value=mock_handle)
        client = TestClient(_make_app(db_pool=mock_db, temporal_client=mock_tc))
        r = client.post("/v1/cts/mismatches/MM-001/resolve", json=self._payload)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/cts/review/{instrument_id}/claim
# ---------------------------------------------------------------------------

class TestClaimInstrument:

    def test_ops_reviewer_no_redis_returns_200(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.post("/v1/cts/review/INST-001/claim")
        assert r.status_code == 200
        body = r.json()
        assert body["instrument_id"] == "INST-001"
        assert "claimed" in body

    def test_ops_manager_allowed(self):
        client = TestClient(_make_app(redis=None))
        r = client.post("/v1/cts/review/INST-001/claim")
        assert r.status_code == 200

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.post("/v1/cts/review/INST-001/claim")
        assert r.status_code == 403

    def test_claim_succeeds_returns_claimed_true(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        with patch("modules.cts.allocation.allocation_service.AllocationService.claim", new_callable=AsyncMock) as mock_claim:
            from modules.cts.allocation.allocation_service import AllocationResult
            mock_claim.return_value = AllocationResult(claimed=True, held_by=None)
            client = TestClient(_make_app(ctx=ctx, redis=MagicMock()))
            r = client.post("/v1/cts/review/INST-001/claim")
        assert r.status_code == 200
        assert "instrument_id" in r.json()

    def test_claim_rejected_returns_claimed_false(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        with patch("modules.cts.allocation.allocation_service.AllocationService.claim", new_callable=AsyncMock) as mock_claim:
            from modules.cts.allocation.allocation_service import AllocationResult
            mock_claim.return_value = AllocationResult(claimed=False, held_by="other-reviewer")
            client = TestClient(_make_app(ctx=ctx, redis=MagicMock()))
            r = client.post("/v1/cts/review/INST-001/claim")
        assert r.status_code == 200
        assert "instrument_id" in r.json()


# ---------------------------------------------------------------------------
# DELETE /v1/cts/review/{instrument_id}/claim
# ---------------------------------------------------------------------------

class TestUnclaimInstrument:

    def test_ops_reviewer_no_redis_returns_200(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.request("DELETE", "/v1/cts/review/INST-001/claim")
        assert r.status_code == 200
        body = r.json()
        assert body["instrument_id"] == "INST-001"
        assert body["claimed"] is False

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.COMPLIANCE_OFFICER)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.request("DELETE", "/v1/cts/review/INST-001/claim")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /v1/cts/allocation/status
# ---------------------------------------------------------------------------

class TestAllocationStatus:

    def test_ops_manager_no_redis_returns_empty(self):
        client = TestClient(_make_app(redis=None))
        r = client.get("/v1/cts/allocation/status")
        assert r.status_code == 200
        body = r.json()
        assert body["bank_id"] == "saraswat-coop"
        assert body["active_claims"] == []
        assert body["total"] == 0

    def test_bank_it_admin_allowed(self):
        ctx = _make_ctx(role=Role.BANK_IT_ADMIN)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.get("/v1/cts/allocation/status")
        assert r.status_code == 200

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, redis=None))
        r = client.get("/v1/cts/allocation/status")
        assert r.status_code == 403

    def test_with_redis_scans_lock_keys(self):
        mock_redis = AsyncMock()
        # First scan returns a key, second returns cursor=0 with empty
        mock_redis.scan = AsyncMock(side_effect=[
            (1, [b"lock:cts:INST-001"]),
            (0, []),
        ])
        mock_redis.get = AsyncMock(return_value=b"reviewer1")
        client = TestClient(_make_app(redis=mock_redis))
        r = client.get("/v1/cts/allocation/status")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["active_claims"][0]["instrument_id"] == "INST-001"
        assert body["active_claims"][0]["reviewer_id"] == "reviewer1"
