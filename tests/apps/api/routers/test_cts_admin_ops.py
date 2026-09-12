"""
Tests for cts_admin_ops.py — 15 admin/ops routes.

Routes tested:
  GET  /v1/cts/instruments/{id}/digest
  POST /v1/cts/admin/workflows/cleanup
  GET  /v1/cts/schedules
  PATCH /v1/cts/schedules/{id}
  POST /v1/cts/schedules/{id}/pause
  POST /v1/cts/schedules/{id}/resume
  GET  /v1/cts/ifsc-registry
  GET  /v1/cts/ifsc-registry/{entry_id}
  POST /v1/cts/ifsc-registry
  PUT  /v1/cts/ifsc-registry/{entry_id}/approve
  DELETE /v1/cts/ifsc-registry/{entry_id}
  GET  /v1/cts/admin/login-log
  GET  /v1/cts/admin/ngch-routing
  GET  /v1/cts/admin/micr-prefixes
  GET  /v1/cts/rpc/zones
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import Role, UserContext


def _ctx(role: str = "ops_manager", bank_id: str = "testbank") -> UserContext:
    ctx = MagicMock(spec=UserContext)
    ctx.role = Role[role.upper()]
    ctx.bank_id = bank_id
    ctx.user_id = "u-test"
    return ctx


def _make_app(ctx: Optional[UserContext] = None, bank_id: str = "testbank"):
    from apps.api.routers import cts_admin_ops
    from apps.api.routers.cts_deps import (
        get_current_user_context,
        get_current_bank_id,
    )

    app = FastAPI()
    app.include_router(cts_admin_ops.router_v1)

    if ctx is None:
        ctx = _ctx()

    app.dependency_overrides[get_current_user_context] = lambda: ctx
    app.dependency_overrides[get_current_bank_id] = lambda: bank_id
    return app


# ── 1. GET /instruments/{instrument_id}/digest ───────────────────────────────

class TestInstrumentDigest:
    def test_no_db_returns_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/INST-001/digest")
        assert resp.status_code == 503

    def test_instrument_not_found_returns_404(self):
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        app = _make_app()
        app.state.db_pool = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/INST-MISSING/digest")
        assert resp.status_code == 404

    def test_found_returns_digest(self):
        row = {
            "instrument_id": "INST-001",
            "bank_id": "testbank",
            "workflow_id": "cts-testbank-INST-001",
            "decision": "STP_CONFIRM",
            "started_at": 1000.0,
            "decided_at": 1001.5,
            "steps_digest": {"pipeline": "INWARD", "steps": []},
            "registry_version": "v1.2",
        }
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        app = _make_app()
        app.state.db_pool = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/INST-001/digest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["instrument_id"] == "INST-001"
        assert body["final_decision"] == "STP_CONFIRM"
        assert body["registry_version"] == "v1.2"

    def test_shap_values_empty_in_response(self):
        row = {
            "instrument_id": "INST-001",
            "bank_id": "testbank",
            "workflow_id": "cts-testbank-INST-001",
            "decision": "HUMAN_REVIEW",
            "started_at": 1000.0,
            "decided_at": 1001.5,
            "steps_digest": {"pipeline": "INWARD", "steps": []},
            "registry_version": "v1.0",
        }
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)

        app = _make_app()
        app.state.db_pool = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/instruments/INST-001/digest")
        assert resp.json()["shap_values"] == {}


# ── 2. POST /admin/workflows/cleanup ─────────────────────────────────────────

class TestWorkflowCleanup:
    def test_temporal_connect_fails_returns_degraded(self):
        """When Temporal is unreachable, returns degraded=True without crashing."""
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/admin/workflows/cleanup", json={"max_age_minutes": 60, "dry_run": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is True
        assert body["found"] == 0

    def test_dry_run_flag_propagated(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/admin/workflows/cleanup", json={"max_age_minutes": 60, "dry_run": True})
        assert resp.json()["dry_run"] is True

    def test_default_max_age_accepted(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.post("/v1/cts/admin/workflows/cleanup", json={})
        assert resp.status_code == 200


# ── 3. GET /schedules ─────────────────────────────────────────────────────────

class TestListSchedules:
    def test_no_temporal_returns_registry_defaults(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.get("/v1/cts/schedules")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "mybank"
        assert len(body["schedules"]) >= 1
        assert "mybank" in body["schedules"][0]["schedule_id"]

    def test_schedule_status_defaults_to_running(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/schedules")
        assert resp.json()["schedules"][0]["status"] == "RUNNING"

    def test_temporal_error_falls_back_gracefully(self):
        mock_handle = MagicMock()
        mock_handle.describe = AsyncMock(side_effect=Exception("not found"))
        mock_tc = MagicMock()
        mock_tc.get_schedule_handle = MagicMock(return_value=mock_handle)

        app = _make_app()
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.get("/v1/cts/schedules")
        assert resp.status_code == 200


# ── 4. PATCH /schedules/{schedule_id} ────────────────────────────────────────

class TestUpdateSchedule:
    def test_cross_bank_idor_returns_404(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.patch(
                "/v1/cts/schedules/cts-otherbank-vaultsync",
                json={"cron": "0 8 * * *"},
            )
        assert resp.status_code == 404

    def test_no_temporal_returns_updated(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.patch(
                "/v1/cts/schedules/cts-mybank-vaultsync",
                json={"cron": "0 8 * * *"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "UPDATED"
        assert resp.json()["cron"] == "0 8 * * *"

    def test_temporal_error_returns_503(self):
        mock_handle = MagicMock()
        mock_handle.update = AsyncMock(side_effect=Exception("Temporal error"))
        mock_tc = MagicMock()
        mock_tc.get_schedule_handle = MagicMock(return_value=mock_handle)

        app = _make_app(bank_id="mybank")
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.patch(
                "/v1/cts/schedules/cts-mybank-vaultsync",
                json={"cron": "0 8 * * *"},
            )
        assert resp.status_code == 503


# ── 5. POST /schedules/{schedule_id}/pause ───────────────────────────────────

class TestPauseSchedule:
    def test_cross_bank_idor_returns_404(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/schedules/cts-otherbank-vaultsync/pause")
        assert resp.status_code == 404

    def test_no_temporal_returns_updated(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/schedules/cts-mybank-vaultsync/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "UPDATED"

    def test_temporal_error_returns_503(self):
        mock_handle = MagicMock()
        mock_handle.pause = AsyncMock(side_effect=Exception("Temporal error"))
        mock_tc = MagicMock()
        mock_tc.get_schedule_handle = MagicMock(return_value=mock_handle)

        app = _make_app(bank_id="mybank")
        app.state.temporal_client = mock_tc
        with TestClient(app) as c:
            resp = c.post("/v1/cts/schedules/cts-mybank-vaultsync/pause")
        assert resp.status_code == 503


# ── 6. POST /schedules/{schedule_id}/resume ──────────────────────────────────

class TestResumeSchedule:
    def test_cross_bank_idor_returns_404(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/schedules/cts-otherbank-vaultsync/resume")
        assert resp.status_code == 404

    def test_no_temporal_returns_updated(self):
        app = _make_app(bank_id="mybank")
        with TestClient(app) as c:
            resp = c.post("/v1/cts/schedules/cts-mybank-vaultsync/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "UPDATED"


# ── 7. GET /ifsc-registry ─────────────────────────────────────────────────────

class TestListIFSCRegistry:
    def test_no_repo_returns_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry")
        assert resp.status_code == 503

    def test_with_repo_returns_list(self):
        from modules.cts.ifsc.models import IFSCListResponse
        mock_repo = MagicMock()
        mock_repo.list_ifsc = AsyncMock(return_value=[])

        app = _make_app()
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["total"] == 0

    def test_limit_capped_at_100(self):
        mock_repo = MagicMock()
        mock_repo.list_ifsc = AsyncMock(return_value=[])

        app = _make_app()
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry?limit=999")
        assert resp.status_code == 200
        # Ensure list_ifsc was called with capped limit
        call_kwargs = mock_repo.list_ifsc.call_args
        assert call_kwargs.kwargs.get("limit", 100) <= 100


# ── 8. GET /ifsc-registry/{entry_id} ─────────────────────────────────────────

class TestGetIFSCByID:
    def test_no_repo_returns_503(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry/entry-001")
        assert resp.status_code == 503

    def test_entry_not_found_returns_404(self):
        mock_repo = MagicMock()
        mock_repo.get_ifsc_by_id = AsyncMock(return_value=None)

        app = _make_app()
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry/entry-999")
        assert resp.status_code == 404

    def test_wrong_bank_returns_404(self):
        entry = MagicMock()
        entry.bank_id = "otherbank"
        mock_repo = MagicMock()
        mock_repo.get_ifsc_by_id = AsyncMock(return_value=entry)

        app = _make_app(bank_id="testbank")
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.get("/v1/cts/ifsc-registry/entry-001")
        assert resp.status_code == 404


# ── 9. POST /ifsc-registry ────────────────────────────────────────────────────

class TestCreateIFSC:
    _body = {
        "ifsc_code": "SBIN0001234",
        "bank_type": "SB",
        "branch_name": "Mumbai Main",
        "branch_city": "Mumbai",
    }

    def test_non_ops_manager_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/ifsc-registry", json=self._body)
        assert resp.status_code == 403

    def test_no_repo_returns_503(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.post("/v1/cts/ifsc-registry", json=self._body)
        assert resp.status_code == 503

    def test_duplicate_returns_409(self):
        from modules.cts.ifsc.repository import IFSCDuplicateError
        mock_repo = MagicMock()
        mock_repo.create_ifsc = AsyncMock(side_effect=IFSCDuplicateError("duplicate"))

        app = _make_app(ctx=_ctx("ops_manager"))
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.post("/v1/cts/ifsc-registry", json=self._body)
        assert resp.status_code == 409

    def test_bank_it_admin_can_create(self):
        from datetime import date
        from modules.cts.ifsc.models import IFSCEntry
        mock_entry = IFSCEntry(
            id="e-001",
            bank_id="testbank",
            bank_type="SB",
            ifsc_code="SBIN0001234",
            branch_name="Mumbai Main",
            is_active=False,
            effective_from=date(2026, 9, 9),
            status="PENDING",
            created_by="u-test",
        )
        mock_repo = MagicMock()
        mock_repo.create_ifsc = AsyncMock(return_value=mock_entry)

        app = _make_app(ctx=_ctx("bank_it_admin"))
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.post("/v1/cts/ifsc-registry", json=self._body)
        assert resp.status_code == 201


# ── 10. PUT /ifsc-registry/{entry_id}/approve ─────────────────────────────────

class TestApproveIFSC:
    def test_non_bank_it_admin_forbidden(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.put("/v1/cts/ifsc-registry/e-001/approve")
        assert resp.status_code == 403

    def test_no_repo_returns_503(self):
        app = _make_app(ctx=_ctx("bank_it_admin"))
        with TestClient(app) as c:
            resp = c.put("/v1/cts/ifsc-registry/e-001/approve")
        assert resp.status_code == 503

    def test_not_found_returns_404(self):
        mock_repo = MagicMock()
        mock_repo.approve_ifsc = AsyncMock(return_value=None)

        app = _make_app(ctx=_ctx("bank_it_admin"))
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.put("/v1/cts/ifsc-registry/e-999/approve")
        assert resp.status_code == 404


# ── 11. DELETE /ifsc-registry/{entry_id} ─────────────────────────────────────

class TestDeactivateIFSC:
    def test_non_bank_it_admin_forbidden(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.delete("/v1/cts/ifsc-registry/e-001")
        assert resp.status_code == 403

    def test_no_repo_returns_503(self):
        app = _make_app(ctx=_ctx("bank_it_admin"))
        with TestClient(app) as c:
            resp = c.delete("/v1/cts/ifsc-registry/e-001")
        assert resp.status_code == 503

    def test_not_found_returns_404(self):
        mock_repo = MagicMock()
        mock_repo.deactivate_ifsc = AsyncMock(return_value=None)

        app = _make_app(ctx=_ctx("bank_it_admin"))
        app.state.ifsc_repo = mock_repo
        with TestClient(app) as c:
            resp = c.delete("/v1/cts/ifsc-registry/e-999")
        assert resp.status_code == 404


# ── 12. GET /admin/login-log ──────────────────────────────────────────────────

class TestAdminLoginLog:
    def test_ops_reviewer_forbidden(self):
        app = _make_app(ctx=_ctx("ops_reviewer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 403

    def test_fraud_analyst_forbidden(self):
        app = _make_app(ctx=_ctx("fraud_analyst"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 403

    def test_ops_manager_allowed_no_db(self):
        app = _make_app(ctx=_ctx("ops_manager"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_compliance_officer_allowed(self):
        app = _make_app(ctx=_ctx("compliance_officer"))
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 200

    def test_with_rows(self):
        row = {
            "event_id": "EVT-001",
            "event_type": "LOGIN_SUCCESS",
            "user_id": "u-001",
            "username": "nilesh",
            "role": "ops_manager",
            "ip_address": "10.0.0.1",
            "user_agent": "Mozilla/5.0",
            "success": True,
            "failure_reason": None,
            "mfa_used": True,
            "occurred_at": "2026-09-09T09:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app(ctx=_ctx("ops_manager"))
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["event_type"] == "LOGIN_SUCCESS"

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))

        app = _make_app(ctx=_ctx("ops_manager"))
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/login-log")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ── 13. GET /admin/ngch-routing ───────────────────────────────────────────────

class TestAdminNGCHRouting:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/ngch-routing")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["rules"] == []
        assert body["total"] == 0

    def test_with_rows(self):
        row = {
            "rule_id": "R-001",
            "micr_prefix": "400002",
            "clearing_zone": "MUMBAI",
            "destination": "NGCH-MUM-1",
            "priority": 1,
            "active": True,
            "updated_at": "2026-09-09T00:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/ngch-routing")
        body = resp.json()
        assert body["total"] == 1
        assert body["rules"][0]["micr_prefix"] == "400002"

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/ngch-routing")
        assert resp.json()["rules"] == []


# ── 14. GET /admin/micr-prefixes ──────────────────────────────────────────────

class TestAdminMICRPrefixes:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/micr-prefixes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["items"] == []

    def test_search_param_accepted(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/micr-prefixes?search=400")
        assert resp.status_code == 200

    def test_with_rows(self):
        row = {
            "prefix_id": "PFX-001",
            "micr_prefix": "400002",
            "bank_name": "SBI Mumbai",
            "bank_ifsc": "SBIN0001234",
            "clearing_zone": "MUMBAI",
            "active": True,
            "updated_at": "2026-09-09T00:00:00",
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/admin/micr-prefixes")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["micr_prefix"] == "400002"


# ── 15. GET /rpc/zones ────────────────────────────────────────────────────────

class TestRPCZones:
    def test_no_db_returns_empty(self):
        app = _make_app()
        with TestClient(app) as c:
            resp = c.get("/v1/cts/rpc/zones")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bank_id"] == "testbank"
        assert body["zones"] == []
        assert body["total"] == 0

    def test_with_rows(self):
        row = {
            "zone_id": "Z-001",
            "zone_name": "MUMBAI",
            "ngch_node": "NGCH-MUM-1",
            "status": "ACTIVE",
            "last_sync_at": "2026-09-09T06:00:00",
            "instrument_count_today": 150,
            "settled_count": 120,
            "pending_count": 30,
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[row])

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/rpc/zones")
        body = resp.json()
        assert body["total"] == 1
        assert body["zones"][0]["zone_name"] == "MUMBAI"
        assert body["zones"][0]["instrument_count_today"] == 150

    def test_db_error_returns_empty(self):
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=Exception("DB error"))

        app = _make_app()
        app.state.db_pool_cts = mock_pool
        with TestClient(app) as c:
            resp = c.get("/v1/cts/rpc/zones")
        assert resp.json()["zones"] == []
