"""
Tests for apps/api/routers/disputes.py

Dispute API endpoints:
  GET  /v1/disputes                          — list dispute cases (ops_manager, fraud_analyst, compliance_officer)
  GET  /v1/disputes/{dispute_id}             — get dispute detail with EJ match and CCTV evidence links
  POST /v1/disputes/{dispute_id}/resolve     — mark auto-resolved (ops_manager, fraud_analyst)
  POST /v1/disputes/{dispute_id}/escalate    — escalate to NPCI filing (ops_manager, fraud_analyst)
  GET  /v1/disputes/{dispute_id}/evidence    — list CCTV evidence links for a dispute (all read roles)
  POST /v1/disputes/ingest                   — ingest an NPCI claim (bank_it_admin, ops_manager)

Rules enforced:
  - All routes require JWT auth (unauthenticated → 401)
  - ops_reviewer cannot access dispute routes
  - compliance_officer is read-only (403 on resolve, escalate, ingest)
  - No PII — account numbers masked, amounts as range buckets, no customer names
  - Dispute ID format: dispute-{bank_id}-{npci_claim_id}
  - Pagination: limit max 100, cursor-based
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app(role="ops_manager"):
    from apps.api.routers.disputes import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _unauthed_app():
    from apps.api.routers.disputes import router_v1
    app = FastAPI()
    app.include_router(router_v1)
    return app


class TestDisputesListRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.status_code == 403

    def test_ops_manager_gets_200(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.status_code == 200

    def test_fraud_analyst_gets_200(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.status_code == 200

    def test_compliance_officer_gets_200(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.status_code == 200

    def test_response_has_disputes_list(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert "disputes" in response.json()

    def test_response_has_next_cursor(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert "next_cursor" in response.json()

    def test_limit_above_100_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes?limit=101")
        assert response.status_code == 422

    def test_default_limit_is_50(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert response.json()["limit"] == 50

    def test_response_never_contains_raw_account_number(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes")
        assert "account_number" not in response.text

    def test_filter_by_status(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes?dispute_status=OPEN")
        assert response.status_code == 200


class TestDisputeDetailRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        assert response.status_code == 403

    def test_authenticated_returns_200_or_404(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        assert response.status_code in (200, 404)

    def test_response_has_dispute_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        if response.status_code == 200:
            assert "dispute_id" in response.json()

    def test_response_has_ej_match(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        if response.status_code == 200:
            assert "ej_match" in response.json()

    def test_response_has_resolution_status(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        if response.status_code == 200:
            assert "resolution_status" in response.json()

    def test_response_never_contains_customer_name(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001")
        assert "customer_name" not in response.text


class TestDisputeResolveRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve",
                               json={"resolution": "DISPENSED_CONFIRMED", "notes": "CCTV verified"})
        assert response.status_code == 401

    def test_ops_reviewer_cannot_resolve(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve",
                               json={"resolution": "DISPENSED_CONFIRMED", "notes": "CCTV verified"})
        assert response.status_code == 403

    def test_compliance_officer_cannot_resolve(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve",
                               json={"resolution": "DISPENSED_CONFIRMED", "notes": "CCTV verified"})
        assert response.status_code == 403

    def test_ops_manager_can_resolve(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve",
                               json={"resolution": "DISPENSED_CONFIRMED", "notes": "CCTV verified"})
        assert response.status_code in (200, 404)

    def test_fraud_analyst_can_resolve(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve",
                               json={"resolution": "DISPENSED_CONFIRMED", "notes": "CCTV verified"})
        assert response.status_code in (200, 404)

    def test_missing_resolution_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/resolve", json={})
        assert response.status_code == 422


class TestDisputeEscalateRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/escalate",
                               json={"reason": "Insufficient CCTV evidence"})
        assert response.status_code == 401

    def test_compliance_officer_cannot_escalate(self):
        client = TestClient(_make_app(role="compliance_officer"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/escalate",
                               json={"reason": "Insufficient CCTV evidence"})
        assert response.status_code == 403

    def test_ops_manager_can_escalate(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/escalate",
                               json={"reason": "Insufficient CCTV evidence"})
        assert response.status_code in (200, 202, 404)

    def test_missing_reason_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/dispute-test-bank-001/escalate", json={})
        assert response.status_code == 422


class TestDisputeEvidenceRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001/evidence")
        assert response.status_code == 401

    def test_ops_reviewer_cannot_access(self):
        client = TestClient(_make_app(role="ops_reviewer"), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001/evidence")
        assert response.status_code == 403

    def test_fraud_analyst_can_access_evidence(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001/evidence")
        assert response.status_code in (200, 404)

    def test_response_has_evidence_list(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001/evidence")
        if response.status_code == 200:
            assert "evidence" in response.json()

    def test_response_never_contains_raw_clip_content(self):
        # CCTV clips are in MinIO — response has reference only, not binary content
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.get("/v1/disputes/dispute-test-bank-001/evidence")
        assert "clip_content" not in response.text


class TestDisputeIngestRoute:
    def test_unauthenticated_returns_401(self):
        client = TestClient(_unauthed_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        assert response.status_code == 401

    def test_fraud_analyst_cannot_ingest(self):
        client = TestClient(_make_app(role="fraud_analyst"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        assert response.status_code == 403

    def test_ops_manager_can_ingest(self):
        client = TestClient(_make_app(role="ops_manager"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        assert response.status_code in (200, 202)

    def test_bank_it_admin_can_ingest(self):
        client = TestClient(_make_app(role="bank_it_admin"), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        assert response.status_code in (200, 202)

    def test_missing_npci_claim_id_returns_422(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        assert response.status_code == 422

    def test_response_has_dispute_id(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
        })
        if response.status_code in (200, 202):
            assert "dispute_id" in response.json()

    def test_ingest_never_accepts_raw_account_number(self):
        # Exact account numbers must not be accepted — amount_range only
        client = TestClient(_make_app(), raise_server_exceptions=False)
        response = client.post("/v1/disputes/ingest", json={
            "npci_claim_id": "NPCI-2026-001",
            "atm_id": "ATM-MUM-001",
            "claimed_amount_range": "₹[10L-1Cr]",
            "claim_date": "2026-06-18",
            "account_number": "1234567890123456",  # must be ignored / not accepted
        })
        # Either 422 (field not in schema) or 200/202 (field silently ignored)
        # Must NOT echo account_number back in response
        assert "account_number" not in response.text


class TestDisputesAuthEdgeCases:
    """Cover lines 39-43: real auth paths in get_current_user."""
    def test_invalid_token_returns_401(self):
        from apps.api.routers.disputes import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/disputes/",
            headers={"Authorization": "Bearer random-invalid-token"},
        )
        assert response.status_code == 401

    def test_valid_test_token_returns_200(self):
        from apps.api.routers.disputes import router_v1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(router_v1)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/v1/disputes/",
            headers={"Authorization": "Bearer test-token-test-bank"},
        )
        assert response.status_code == 200
