"""Tests for batch operations API — sessions, val/vol dashboard, file downloads."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.batch import router_v1

_AUTH = {"Authorization": "Bearer test-token-hdfc-bank"}


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router_v1)
    return TestClient(app, raise_server_exceptions=False)


class TestSessionList:
    def test_returns_200(self, client):
        resp = client.get("/v1/cts/sessions", headers=_AUTH)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        resp = client.get("/v1/cts/sessions")
        assert resp.status_code == 401

    def test_returns_sessions_list(self, client):
        data = client.get("/v1/cts/sessions", headers=_AUTH).json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
        assert len(data["sessions"]) > 0

    def test_sessions_have_required_fields(self, client):
        sessions = client.get("/v1/cts/sessions", headers=_AUTH).json()["sessions"]
        for s in sessions:
            assert "session_id" in s
            assert "status" in s
            assert "session_slot" in s


class TestTodaySummary:
    def test_returns_200(self, client):
        resp = client.get("/v1/cts/sessions/today", headers=_AUTH)
        assert resp.status_code == 200

    def test_has_inward_outward_net(self, client):
        data = client.get("/v1/cts/sessions/today", headers=_AUTH).json()
        assert "total_inward" in data
        assert "total_outward" in data
        assert "net_settlement_paise" in data

    def test_has_decision_breakdown(self, client):
        data = client.get("/v1/cts/sessions/today", headers=_AUTH).json()
        assert "stp_confirmed" in data
        assert "stp_returned" in data
        assert "manual_confirmed" in data
        assert "manual_returned" in data

    def test_has_rate_metrics(self, client):
        data = client.get("/v1/cts/sessions/today", headers=_AUTH).json()
        assert "overall_stp_rate_pct" in data
        assert "overall_return_rate_pct" in data
        assert 0 <= data["overall_stp_rate_pct"] <= 100
        assert 0 <= data["overall_return_rate_pct"] <= 100

    def test_has_5day_trend(self, client):
        data = client.get("/v1/cts/sessions/today", headers=_AUTH).json()
        assert "trend_5d" in data
        assert isinstance(data["trend_5d"], list)


class TestSessionSummary:
    def test_returns_presenting_and_drawee(self, client):
        sessions = client.get("/v1/cts/sessions", headers=_AUTH).json()["sessions"]
        sid = sessions[0]["session_id"]
        data = client.get(f"/v1/cts/sessions/{sid}/summary", headers=_AUTH).json()
        assert "presenting_bank" in data
        assert "drawee_bank" in data
        assert "net_settlement_paise" in data

    def test_presenting_has_stp_manual_breakdown(self, client):
        sessions = client.get("/v1/cts/sessions", headers=_AUTH).json()["sessions"]
        sid = sessions[0]["session_id"]
        pres = client.get(f"/v1/cts/sessions/{sid}/summary", headers=_AUTH).json()["presenting_bank"]
        assert "stp_confirmed" in pres
        assert "stp_returned" in pres
        assert "manual_confirmed" in pres
        assert "manual_returned" in pres
        assert "stp_rate_pct" in pres
        assert "return_rate_pct" in pres

    def test_drawee_has_return_reasons(self, client):
        sessions = client.get("/v1/cts/sessions", headers=_AUTH).json()["sessions"]
        sid = sessions[0]["session_id"]
        draw = client.get(f"/v1/cts/sessions/{sid}/summary", headers=_AUTH).json()["drawee_bank"]
        assert "return_reasons" in draw
        assert isinstance(draw["return_reasons"], dict)


class TestBankwise:
    def test_returns_rows(self, client):
        resp = client.get("/v1/cts/sessions/ANY-001/bankwise", headers=_AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "rows" in data
        assert len(data["rows"]) > 0

    def test_filter_presenting_only(self, client):
        data = client.get(
            "/v1/cts/sessions/ANY-001/bankwise?perspective=PRESENTING", headers=_AUTH
        ).json()
        for row in data["rows"]:
            assert row["perspective"] == "PRESENTING"

    def test_filter_drawee_only(self, client):
        data = client.get(
            "/v1/cts/sessions/ANY-001/bankwise?perspective=DRAWEE", headers=_AUTH
        ).json()
        for row in data["rows"]:
            assert row["perspective"] == "DRAWEE"


class TestFileDownloads:
    def test_npci_returns_pipe_delimited_file(self, client):
        resp = client.get("/v1/cts/sessions/ANY-001/download/npci", headers=_AUTH)
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert "|" in resp.text

    def test_mis_returns_csv(self, client):
        resp = client.get("/v1/cts/sessions/ANY-001/download/mis", headers=_AUTH)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]

    def test_settlement_returns_csv(self, client):
        resp = client.get("/v1/cts/sessions/ANY-001/download/settlement", headers=_AUTH)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_downloads_require_auth(self, client):
        for path in ["npci", "mis", "settlement"]:
            resp = client.get(f"/v1/cts/sessions/X/download/{path}")
            assert resp.status_code == 401


class TestOpsDashboard:
    def test_returns_today_and_trend(self, client):
        data = client.get("/v1/cts/dashboard/ops", headers=_AUTH).json()
        assert "today" in data
        assert "trend" in data
        assert "sessions" in data["today"]

    def test_trend_length_respects_days_param(self, client):
        data = client.get("/v1/cts/dashboard/ops?days=3", headers=_AUTH).json()
        assert len(data["trend"]) <= 3
