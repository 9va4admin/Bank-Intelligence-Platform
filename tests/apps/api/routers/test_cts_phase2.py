"""
Phase 2 TDD tests — Session & Clearing Data endpoints:
  GET /v1/cts/smb/ledgers
  GET /v1/cts/outward/reconciliation
  GET /v1/cts/outward/lots

RED phase: all tests expected to FAIL before implementation.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext


def _make_app():
    from apps.api.routers.cts import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


def _sb_ctx(bank_id="saraswat-coop"):
    return UserContext(
        user_id="ops-001",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


def _smb_ctx(bank_id="vasavi-001"):
    return UserContext(
        user_id="ops-smb-001",
        bank_id=bank_id,
        bank_type=BankType.SMB,
        role=Role.OPS_MANAGER,
        permission_level=PermissionLevel.EDIT,
    )


def _it_admin_ctx(bank_id="saraswat-coop"):
    return UserContext(
        user_id="admin-001",
        bank_id=bank_id,
        bank_type=BankType.SB,
        role=Role.BANK_IT_ADMIN,
        permission_level=PermissionLevel.ADMIN,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/smb/ledgers
# ─────────────────────────────────────────────────────────────────────────────

class TestSMBLedgersEndpoint:
    """All sub-member ledgers for an SB bank on a given date."""

    def test_smb_ledgers_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 401

    def test_smb_ledgers_wrong_role_returns_403(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        fraud_ctx = UserContext(
            user_id="fa-001", bank_id="saraswat-coop", bank_type=BankType.SB,
            role=Role.FRAUD_ANALYST, permission_level=PermissionLevel.READ_ONLY,
        )
        app.dependency_overrides[get_current_user_context] = lambda: fraud_ctx
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 403

    def test_smb_ledgers_no_db_returns_empty_list(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        # No db_pool_cts on app.state → graceful empty response
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 200
        body = r.json()
        assert "ledgers" in body
        assert isinstance(body["ledgers"], list)
        assert "bank_id" in body
        assert "session_date" in body

    def test_smb_ledgers_with_db_returns_correct_shape(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()

        fake_row = {
            "sub_member_id": "SMB-MH-001",
            "bank_name": "Vasavi Co-op Bank",
            "total_received": 42,
            "stp_pass": 28,
            "stp_return": 12,
            "eyeball": 2,
            "fraud_hold": 0,
            "iet_emergency": 0,
            "soft_hold_active": True,
            "tier2_notification_sent": False,
        }
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[fake_row])
        app.state.db_pool_cts = mock_pool

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/ledgers?session_date=2026-09-02")
        assert r.status_code == 200
        body = r.json()
        assert len(body["ledgers"]) == 1
        ledger = body["ledgers"][0]
        assert ledger["sub_member_id"] == "SMB-MH-001"
        assert ledger["bank_name"] == "Vasavi Co-op Bank"
        assert ledger["total_received"] == 42
        assert ledger["stp_pass"] == 28
        assert "return_rate_pct" in ledger
        assert "shield_status" in ledger

    def test_smb_user_cannot_call_all_ledgers(self):
        """SMB users should get 403 — they see only their own ledger via /smb/{id}/ledger."""
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _smb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/outward/reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TestOutwardReconciliationEndpoint:
    """Reconciliation sessions + discrepancies for a bank/date."""

    def test_reconciliation_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/reconciliation")
        assert r.status_code == 401

    def test_reconciliation_wrong_role_returns_403(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        reviewer_ctx = UserContext(
            user_id="rev-001", bank_id="saraswat-coop", bank_type=BankType.SB,
            role=Role.OPS_REVIEWER, permission_level=PermissionLevel.READ_ONLY,
        )
        app.dependency_overrides[get_current_user_context] = lambda: reviewer_ctx
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/reconciliation")
        assert r.status_code == 403

    def test_reconciliation_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/reconciliation")
        assert r.status_code == 200
        body = r.json()
        assert "sessions" in body
        assert "discrepancies" in body
        assert isinstance(body["sessions"], list)
        assert isinstance(body["discrepancies"], list)
        assert "bank_id" in body
        assert "recon_date" in body

    def test_reconciliation_with_db_returns_sessions_and_discrepancies(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        import uuid
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()

        recon_id = str(uuid.uuid4())
        disc_id = str(uuid.uuid4())
        inst_id = str(uuid.uuid4())

        fake_sessions = [{
            "recon_session_id": recon_id,
            "status": "RECONCILED",
            "astra_instrument_count": 150,
            "ngch_instrument_count": 150,
            "discrepancy_count": 2,
            "started_at": "2026-09-02T10:00:00+05:30",
            "completed_at": "2026-09-02T10:05:00+05:30",
            "recon_type": "DAILY_CLEARING",
        }]
        fake_discs = [{
            "discrepancy_id": disc_id,
            "recon_session_id": recon_id,
            "instrument_id": inst_id,
            "cheque_number": "100006",
            "discrepancy_type": "AMOUNT_MISMATCH",
            "astra_value": {"amount_range": "₹[<1L]"},
            "ngch_value": {"amount_range": "₹[1L-5L]"},
            "status": "OPEN",
            "created_at": "2026-09-02T10:03:00+05:30",
        }]

        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(side_effect=[fake_sessions, fake_discs])
        app.state.db_pool_cts = mock_pool

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/reconciliation?recon_date=2026-09-02")
        assert r.status_code == 200
        body = r.json()
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["status"] == "RECONCILED"
        assert body["sessions"][0]["discrepancy_count"] == 2
        assert len(body["discrepancies"]) == 1
        assert body["discrepancies"][0]["discrepancy_type"] == "AMOUNT_MISMATCH"
        assert body["discrepancies"][0]["cheque_number"] == "100006"

    def test_reconciliation_date_defaults_to_today(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = mock_pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/reconciliation")
        assert r.status_code == 200
        body = r.json()
        from datetime import date
        assert body["recon_date"] == date.today().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/cts/outward/lots
# ─────────────────────────────────────────────────────────────────────────────

class TestOutwardLotsListEndpoint:
    """List of scanning lots for the bank today."""

    def test_lots_list_requires_auth(self):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots")
        assert r.status_code == 401

    def test_lots_list_wrong_role_returns_403(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        fraud_ctx = UserContext(
            user_id="fa-001", bank_id="saraswat-coop", bank_type=BankType.SB,
            role=Role.FRAUD_ANALYST, permission_level=PermissionLevel.READ_ONLY,
        )
        app.dependency_overrides[get_current_user_context] = lambda: fraud_ctx
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots")
        assert r.status_code == 403

    def test_lots_list_no_db_returns_empty(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots")
        assert r.status_code == 200
        body = r.json()
        assert "lots" in body
        assert isinstance(body["lots"], list)
        assert "bank_id" in body
        assert "clearing_date" in body

    def test_lots_list_with_db_returns_correct_shape(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()

        fake_rows = [
            {
                "lot_id": "LOT_SVCB0000001_20260902",
                "branch_id": "BRANCH-ANW",
                "branch_name": "Andheri (W)",
                "session_id": "SES-SVCB-20260902-001",
                "sequence_number": 1,
                "status": "SEALED",
                "instrument_count": 18,
                "max_instruments": 25,
                "created_at": "2026-09-02T09:15:00+05:30",
                "sealed_at": "2026-09-02T10:30:00+05:30",
            },
            {
                "lot_id": "LOT_SVCB0000002_20260902",
                "branch_id": "BRANCH-ANW",
                "branch_name": "Andheri (W)",
                "session_id": "SES-SVCB-20260902-001",
                "sequence_number": 2,
                "status": "OPEN",
                "instrument_count": 7,
                "max_instruments": 25,
                "created_at": "2026-09-02T10:35:00+05:30",
                "sealed_at": None,
            },
        ]
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)
        app.state.db_pool_cts = mock_pool

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots?clearing_date=2026-09-02")
        assert r.status_code == 200
        body = r.json()
        assert len(body["lots"]) == 2
        lot = body["lots"][0]
        assert lot["lot_id"] == "LOT_SVCB0000001_20260902"
        assert lot["branch_name"] == "Andheri (W)"
        assert lot["status"] == "SEALED"
        assert lot["instrument_count"] == 18
        assert "sequence_number" in lot
        assert "created_at" in lot
        assert "sealed_at" in lot

    def test_lots_list_scoped_to_bank_id(self):
        """Only lots belonging to the authenticated bank are returned."""
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx(bank_id="bank-A")

        captured_args = []
        async def fake_fetch(sql, *args):
            captured_args.extend(args)
            return []

        mock_pool = MagicMock()
        mock_pool.fetch = fake_fetch
        app.state.db_pool_cts = mock_pool

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots")
        assert r.status_code == 200
        # bank_id must appear in the query arguments
        assert "bank-A" in captured_args

    def test_lots_list_accepts_clearing_date_param(self):
        from apps.api.routers.cts import router_v1, get_current_user_context
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user_context] = lambda: _sb_ctx()
        mock_pool = MagicMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        app.state.db_pool_cts = mock_pool
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/v1/cts/outward/lots?clearing_date=2026-08-01")
        assert r.status_code == 200
        body = r.json()
        assert body["clearing_date"] == "2026-08-01"
