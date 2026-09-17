"""
Tests for cts_smb.py — all 8 SMB routes.

TDD: this file is written BEFORE cts_smb.py exists — first run must be RED.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
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
) -> UserContext:
    return UserContext(
        user_id="u1",
        bank_id=bank_id,
        bank_type=bank_type,
        role=role,
        permission_level=PermissionLevel.EDIT,
        session_id="sess1",
    )


def _make_app(ctx: UserContext = None, db_pool=None, temporal_client=None):
    from apps.api.routers.cts_smb import router_v1
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
    return app


# ---------------------------------------------------------------------------
# GET /v1/cts/smb — list sub-members
# ---------------------------------------------------------------------------

class TestSMBList:

    def test_sb_no_db_returns_empty_list(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb")
        assert r.status_code == 200
        body = r.json()
        assert body["sponsor_bank_id"] == "saraswat-coop"
        assert body["sub_members"] == []
        assert body["total"] == 0

    def test_sb_with_db_returns_members(self):
        rows = [
            {
                "sub_member_id": "nkgsb-coop", "bank_name": "NKGSB Coop",
                "micr_prefix": "400", "ifsc_prefix": "NKGS",
                "is_active": True, "return_rate_threshold": 0.15,
                "soft_hold_threshold": 0.25, "vault_sync_status": "SYNC_OK",
                "last_vault_sync_at": 1725888000.0,
                "signature_count": 120, "pps_entry_count": 45,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb")
        assert r.status_code == 200
        body = r.json()
        assert len(body["sub_members"]) == 1
        assert body["sub_members"][0]["sub_member_id"] == "nkgsb-coop"
        assert body["sub_members"][0]["vault_sync_status"] == "SYNC_OK"

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb")
        assert r.status_code == 403

    def test_db_error_returns_empty_list(self):
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(side_effect=Exception("db down"))
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb")
        assert r.status_code == 200
        assert r.json()["total"] == 0


# ---------------------------------------------------------------------------
# POST /v1/cts/smb — register sub-member
# ---------------------------------------------------------------------------

class TestSMBRegister:

    _payload = {
        "sub_member_id": "nkgsb-coop",
        "bank_name": "NKGSB Coop Bank",
        "sponsor_bank_id": "saraswat-coop",
        "micr_prefix": "400",
        "ifsc_prefix": "NKGS",
        "return_rate_threshold": 0.15,
        "soft_hold_threshold": 0.25,
    }

    def test_sb_no_db_returns_201(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.post("/v1/cts/smb", json=self._payload)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "REGISTERED"
        assert body["sub_member_id"] == "nkgsb-coop"

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/smb", json=self._payload)
        assert r.status_code == 403

    def test_invalid_thresholds_returns_422(self):
        bad = {**self._payload, "return_rate_threshold": 0.30, "soft_hold_threshold": 0.20}
        client = TestClient(_make_app(db_pool=None))
        r = client.post("/v1/cts/smb", json=bad)
        assert r.status_code == 422

    def test_db_error_returns_503(self):
        conn_mock = AsyncMock()
        conn_mock.execute = AsyncMock(side_effect=Exception("db down"))
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=conn_mock)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.acquire = MagicMock(return_value=ctx_mgr)
        client = TestClient(_make_app(db_pool=mock_db), raise_server_exceptions=False)
        r = client.post("/v1/cts/smb", json=self._payload)
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /v1/cts/smb/{id}/ledger
# ---------------------------------------------------------------------------

class TestSMBLedger:

    def test_sb_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/nkgsb-coop/ledger")
        assert r.status_code == 200
        body = r.json()
        assert body["ledgers"] == []
        assert body["bank_id"] == "saraswat-coop"

    def test_smb_user_own_ledger_allowed(self):
        ctx = _make_ctx(bank_id="nkgsb-coop", bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/nkgsb-coop/ledger")
        assert r.status_code == 200

    def test_smb_user_cross_bank_gets_403(self):
        ctx = _make_ctx(bank_id="nkgsb-coop", bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/other-smb/ledger")
        assert r.status_code == 403

    def test_with_db_returns_ledger_rows(self):
        rows = [
            {
                "sub_member_id": "nkgsb-coop", "bank_name": "NKGSB Coop",
                "session_date": "2026-09-09", "clearing_session": "S1",
                "total_received": 100, "stp_pass": 80, "stp_return": 10,
                "eyeball": 5, "fraud_hold": 3, "iet_emergency": 0,
                "soft_hold_active": False, "risk_event_emitted": False,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb/nkgsb-coop/ledger")
        assert r.status_code == 200
        body = r.json()
        assert len(body["ledgers"]) == 1
        assert body["ledgers"][0]["stp_rate_pct"] == 80.0
        assert body["ledgers"][0]["return_rate_pct"] == 10.0


# ---------------------------------------------------------------------------
# GET /v1/cts/smb/{id}/forwarding-log
# ---------------------------------------------------------------------------

class TestSMBForwardingLog:

    def test_sb_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/nkgsb-coop/forwarding-log")
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_smb_own_forwarding_log_allowed(self):
        ctx = _make_ctx(bank_id="nkgsb-coop", bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/nkgsb-coop/forwarding-log")
        assert r.status_code == 200

    def test_smb_cross_bank_gets_403(self):
        ctx = _make_ctx(bank_id="nkgsb-coop", bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/other-smb/forwarding-log")
        assert r.status_code == 403

    def test_limit_capped_at_100(self):
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=[])
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb/nkgsb-coop/forwarding-log?limit=200")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/cts/smb/{id}/vault-sync
# ---------------------------------------------------------------------------

class TestSMBVaultSync:

    def test_sb_no_temporal_returns_202(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.post("/v1/cts/smb/nkgsb-coop/vault-sync")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "TRIGGERED"
        assert body["sub_member_id"] == "nkgsb-coop"
        assert "workflow_id" in body

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.post("/v1/cts/smb/nkgsb-coop/vault-sync")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /v1/cts/smb/ledgers — all SMB ledgers (SB-only)
# ---------------------------------------------------------------------------

class TestAllSMBLedgers:

    def test_sb_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 200
        assert r.json()["ledgers"] == []

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 403

    def test_wrong_role_gets_403(self):
        ctx = _make_ctx(role=Role.OPS_REVIEWER)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 403

    def test_with_db_returns_ledger_entries(self):
        rows = [
            {
                "sub_member_id": "nkgsb-coop", "bank_name": "NKGSB Coop",
                "total_received": 80, "stp_pass": 60, "stp_return": 8,
                "eyeball": 5, "fraud_hold": 2, "iet_emergency": 0,
                "soft_hold_active": False, "tier2_notification_sent": False,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb/ledgers")
        assert r.status_code == 200
        body = r.json()
        assert len(body["ledgers"]) == 1
        assert body["ledgers"][0]["shield_status"] == "SAFE"


# ---------------------------------------------------------------------------
# GET /v1/cts/smb/forwarding-log — SB consolidated all-SMB view
# ---------------------------------------------------------------------------

class TestSBForwardingLogAll:

    def test_sb_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["bank_id"] == "saraswat-coop"

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 403

    def test_limit_capped_at_500(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/forwarding-log?limit=501")
        assert r.status_code == 422

    def test_with_db_returns_items(self):
        rows = [
            {
                "forwarding_id": "FWD-001", "instrument_id": "INST-001",
                "sub_member_id": "nkgsb-coop", "bank_name": "NKGSB Coop",
                "micr_prefix_matched": "400", "forwarding_status": "COMPLETED",
                "terminal_decision": "STP_CONFIRM",
                "iet_deadline_utc": "2026-09-09T12:00:00+00:00",
                "received_at": "2026-09-09T09:00:00+00:00",
                "forwarded_at": "2026-09-09T09:01:00+00:00",
                "completed_at": "2026-09-09T09:02:00+00:00",
                "iet_seconds_remaining": 10800,
                "failure_reason": None,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb/forwarding-log")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["forwarding_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# GET /v1/cts/smb/reports — per-SMB performance aggregates
# ---------------------------------------------------------------------------

class TestSMBReports:

    def test_sb_no_db_returns_empty(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/reports")
        assert r.status_code == 200
        assert r.json()["rows"] == []

    def test_smb_user_gets_403(self):
        ctx = _make_ctx(bank_type=BankType.SMB)
        client = TestClient(_make_app(ctx=ctx, db_pool=None))
        r = client.get("/v1/cts/smb/reports")
        assert r.status_code == 403

    def test_days_param_capped_at_30(self):
        client = TestClient(_make_app(db_pool=None))
        r = client.get("/v1/cts/smb/reports?days=99")
        assert r.status_code == 422

    def test_with_db_returns_report_rows(self):
        rows = [
            {
                "sub_member_id": "nkgsb-coop", "bank_name": "NKGSB Coop",
                "bank_ifsc": "NKGS0000001", "date": "2026-09-09",
                "total_presented": 100, "stp_confirmed": 85,
                "stp_returned": 10, "human_review": 5,
                "return_rate_pct": 10.0, "avg_decision_ms": 320,
                "iet_breach_count": 0,
            }
        ]
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        client = TestClient(_make_app(db_pool=mock_db))
        r = client.get("/v1/cts/smb/reports?days=7")
        assert r.status_code == 200
        body = r.json()
        assert len(body["rows"]) == 1
        assert body["rows"][0]["stp_confirmed"] == 85
