"""
Tests for apps/api/routers/processing_units.py — Processing Unit Master CRUD.

Routes under test:
  GET    /v1/processing-units                        — list PUs for bank
  POST   /v1/processing-units                        — create PU
  GET    /v1/processing-units/{pu_id}                — get single PU
  PUT    /v1/processing-units/{pu_id}                — update PU
  DELETE /v1/processing-units/{pu_id}                — soft-deactivate (is_active=false)
  GET    /v1/processing-units/{pu_id}/branches       — list branches mapped to this PU

Access control:
  - bank_it_admin: full CRUD
  - ops_manager:   read-only (GET routes only)
  - others:        403 on all routes

Audit:
  - Every mutating action emits an AuditEvent to ImmuDB (tested via mock)

Branch PU mapping audit (via branches.py):
  - PUT /v1/branches/{ifsc} with pu_id change emits PU_BRANCH_ASSIGNED (first assignment)
  - PUT /v1/branches/{ifsc} with pu_id change emits PU_BRANCH_REASSIGNED (reassignment)
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_pu_store():
    from apps.api.routers.processing_units import _PU_STORE
    _PU_STORE.clear()
    yield
    _PU_STORE.clear()


@pytest.fixture(autouse=True)
def clear_branch_store():
    from apps.api.routers.branches import _BRANCH_STORE
    _BRANCH_STORE.clear()
    yield
    _BRANCH_STORE.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pu_app(role: str = "bank_it_admin"):
    from apps.api.routers.processing_units import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _pu_client(role: str = "bank_it_admin") -> TestClient:
    return TestClient(_make_pu_app(role=role), raise_server_exceptions=False)


def _make_branch_app(role: str = "bank_it_admin"):
    from apps.api.routers.branches import router_v1, get_current_user
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {
        "bank_id": "test-bank",
        "user_id": "user-001",
        "role": role,
    }
    return app


def _branch_client(role: str = "bank_it_admin") -> TestClient:
    return TestClient(_make_branch_app(role=role), raise_server_exceptions=False)


def _sample_pu_payload(pu_id: str = "MUMBAI-PU-01") -> dict:
    return {
        "pu_id": pu_id,
        "pu_name": "Mumbai Processing Unit 01",
        "clearing_zone": "MUMBAI",
        "ngch_participant_code": "MUMBAI-KARB-001",
        "max_agent_swarm_size": 200,
    }


def _sample_branch_payload(ifsc: str = "KARB0000123") -> dict:
    return {
        "branch_name": "Koramangala Branch",
        "branch_ifsc": ifsc,
        "city": "Bengaluru",
        "state": "Karnataka",
    }


# ── CREATE ────────────────────────────────────────────────────────────────────

class TestCreatePU:
    def test_create_pu_success(self):
        client = _pu_client()
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["pu_id"] == "MUMBAI-PU-01"
        assert data["pu_name"] == "Mumbai Processing Unit 01"
        assert data["clearing_zone"] == "MUMBAI"
        assert data["ngch_participant_code"] == "MUMBAI-KARB-001"
        assert data["is_active"] is True
        assert data["bank_id"] == "test-bank"

    def test_create_pu_computes_temporal_queue(self):
        client = _pu_client()
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["temporal_task_queue"] == "cts-processing-test-bank-MUMBAI-PU-01"

    def test_create_pu_computes_kafka_topic(self):
        client = _pu_client()
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["kafka_inward_topic"] == "cts.inward.test-bank.MUMBAI-PU-01"

    def test_create_pu_zone_conflict(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        # Same zone, different pu_id — must be rejected
        payload = _sample_pu_payload(pu_id="MUMBAI-PU-02")
        resp = client.post("/v1/processing-units", json=payload)
        assert resp.status_code == 409

    def test_create_pu_duplicate_pu_id(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 409

    def test_create_pu_two_different_zones_allowed(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload("MUMBAI-PU-01"))
        payload2 = _sample_pu_payload("DELHI-PU-01")
        payload2["clearing_zone"] = "DELHI"
        payload2["ngch_participant_code"] = "DELHI-KARB-001"
        resp = client.post("/v1/processing-units", json=payload2)
        assert resp.status_code == 201

    def test_create_pu_requires_bank_it_admin(self):
        client = _pu_client(role="ops_manager")
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 403

    def test_create_pu_ops_reviewer_forbidden(self):
        client = _pu_client(role="ops_reviewer")
        resp = client.post("/v1/processing-units", json=_sample_pu_payload())
        assert resp.status_code == 403

    def test_create_pu_missing_required_field(self):
        client = _pu_client()
        payload = _sample_pu_payload()
        del payload["ngch_participant_code"]
        resp = client.post("/v1/processing-units", json=payload)
        assert resp.status_code == 422

    def test_create_pu_invalid_clearing_zone(self):
        client = _pu_client()
        payload = _sample_pu_payload()
        payload["clearing_zone"] = "INVALID_ZONE"
        resp = client.post("/v1/processing-units", json=payload)
        assert resp.status_code == 422


# ── LIST ──────────────────────────────────────────────────────────────────────

class TestListPUs:
    def test_list_empty(self):
        client = _pu_client()
        resp = client.get("/v1/processing-units")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processing_units"] == []
        assert data["total"] == 0

    def test_list_returns_created_pu(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.get("/v1/processing-units")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["processing_units"][0]["pu_id"] == "MUMBAI-PU-01"

    def test_list_multiple_pus(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload("MUMBAI-PU-01"))
        p2 = _sample_pu_payload("DELHI-PU-01")
        p2["clearing_zone"] = "DELHI"
        p2["ngch_participant_code"] = "DELHI-KARB-001"
        client.post("/v1/processing-units", json=p2)
        resp = client.get("/v1/processing-units")
        assert resp.json()["total"] == 2

    def test_list_ops_manager_can_read(self):
        admin_client = _pu_client()
        admin_client.post("/v1/processing-units", json=_sample_pu_payload())
        reader = _pu_client(role="ops_manager")
        resp = reader.get("/v1/processing-units")
        assert resp.status_code == 200

    def test_list_ops_reviewer_forbidden(self):
        client = _pu_client(role="ops_reviewer")
        resp = client.get("/v1/processing-units")
        assert resp.status_code == 403

    def test_list_filter_by_is_active(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload("MUMBAI-PU-01"))
        p2 = _sample_pu_payload("DELHI-PU-01")
        p2["clearing_zone"] = "DELHI"
        p2["ngch_participant_code"] = "DELHI-KARB-001"
        client.post("/v1/processing-units", json=p2)
        # Deactivate one
        client.delete("/v1/processing-units/MUMBAI-PU-01")
        resp = client.get("/v1/processing-units?is_active=true")
        data = resp.json()
        assert data["total"] == 1
        assert data["processing_units"][0]["pu_id"] == "DELHI-PU-01"


# ── GET SINGLE ────────────────────────────────────────────────────────────────

class TestGetPU:
    def test_get_existing_pu(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.get("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 200
        assert resp.json()["pu_id"] == "MUMBAI-PU-01"

    def test_get_nonexistent_pu(self):
        client = _pu_client()
        resp = client.get("/v1/processing-units/NONEXISTENT-PU")
        assert resp.status_code == 404

    def test_get_pu_ops_manager_allowed(self):
        admin = _pu_client()
        admin.post("/v1/processing-units", json=_sample_pu_payload())
        reader = _pu_client(role="ops_manager")
        resp = reader.get("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 200

    def test_get_pu_other_bank_not_visible(self):
        # Create PU as test-bank
        from apps.api.routers.processing_units import router_v1, get_current_user
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {
            "bank_id": "other-bank", "user_id": "u2", "role": "bank_it_admin"
        }
        other_client = TestClient(app, raise_server_exceptions=False)
        # Seed via test-bank
        _pu_client().post("/v1/processing-units", json=_sample_pu_payload())
        # other-bank should get 404
        resp = other_client.get("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 404


# ── UPDATE ────────────────────────────────────────────────────────────────────

class TestUpdatePU:
    def test_update_pu_name(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"pu_name": "Mumbai PU Alpha"})
        assert resp.status_code == 200
        assert resp.json()["pu_name"] == "Mumbai PU Alpha"

    def test_update_max_agent_swarm_size(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"max_agent_swarm_size": 500})
        assert resp.status_code == 200
        assert resp.json()["max_agent_swarm_size"] == 500

    def test_update_pu_not_found(self):
        client = _pu_client()
        resp = client.put("/v1/processing-units/NONEXISTENT", json={"pu_name": "X"})
        assert resp.status_code == 404

    def test_update_pu_clearing_zone_immutable(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"clearing_zone": "DELHI"})
        assert resp.status_code == 422

    def test_update_pu_id_immutable(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"pu_id": "NEW-ID"})
        assert resp.status_code == 422

    def test_update_ngch_participant_code_immutable(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"ngch_participant_code": "CHANGED"})
        assert resp.status_code == 422

    def test_update_requires_bank_it_admin(self):
        admin = _pu_client()
        admin.post("/v1/processing-units", json=_sample_pu_payload())
        reader = _pu_client(role="ops_manager")
        resp = reader.put("/v1/processing-units/MUMBAI-PU-01", json={"pu_name": "X"})
        assert resp.status_code == 403

    def test_update_max_agent_swarm_must_be_positive(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.put("/v1/processing-units/MUMBAI-PU-01", json={"max_agent_swarm_size": 0})
        assert resp.status_code == 422


# ── DEACTIVATE (soft-delete) ──────────────────────────────────────────────────

class TestDeactivatePU:
    def test_deactivate_pu(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = client.delete("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_deactivate_nonexistent_pu(self):
        client = _pu_client()
        resp = client.delete("/v1/processing-units/NONEXISTENT")
        assert resp.status_code == 404

    def test_deactivate_requires_bank_it_admin(self):
        admin = _pu_client()
        admin.post("/v1/processing-units", json=_sample_pu_payload())
        reader = _pu_client(role="ops_manager")
        resp = reader.delete("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 403

    def test_deactivated_pu_still_retrievable(self):
        client = _pu_client()
        client.post("/v1/processing-units", json=_sample_pu_payload())
        client.delete("/v1/processing-units/MUMBAI-PU-01")
        resp = client.get("/v1/processing-units/MUMBAI-PU-01")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


# ── LIST BRANCHES FOR PU ──────────────────────────────────────────────────────

class TestListBranchesForPU:
    def test_list_branches_empty_when_no_branches_mapped(self):
        from apps.api.routers.processing_units import _PU_STORE
        from apps.api.routers.branches import _BRANCH_STORE
        pu_client = _pu_client()
        pu_client.post("/v1/processing-units", json=_sample_pu_payload())
        resp = pu_client.get("/v1/processing-units/MUMBAI-PU-01/branches")
        assert resp.status_code == 200
        assert resp.json()["branches"] == []
        assert resp.json()["total"] == 0

    def test_list_branches_returns_mapped_branches(self):
        # Create PU
        pu_client = _pu_client()
        pu_client.post("/v1/processing-units", json=_sample_pu_payload())
        # Create branch and assign to PU
        br_client = _branch_client()
        br_client.post("/v1/branches", json=_sample_branch_payload("KARB0000123"))
        br_client.put("/v1/branches/KARB0000123", json={"pu_id": "MUMBAI-PU-01"})
        # List branches on PU
        resp = pu_client.get("/v1/processing-units/MUMBAI-PU-01/branches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["branches"][0]["branch_ifsc"] == "KARB0000123"

    def test_list_branches_pu_not_found(self):
        client = _pu_client()
        resp = client.get("/v1/processing-units/NONEXISTENT/branches")
        assert resp.status_code == 404

    def test_list_branches_ops_manager_allowed(self):
        pu_client_admin = _pu_client()
        pu_client_admin.post("/v1/processing-units", json=_sample_pu_payload())
        reader = _pu_client(role="ops_manager")
        resp = reader.get("/v1/processing-units/MUMBAI-PU-01/branches")
        assert resp.status_code == 200


# ── BRANCH PU ASSIGNMENT AUDIT ────────────────────────────────────────────────

class TestBranchPUAssignmentAudit:
    def _seed_branch(self, ifsc: str = "KARB0000123") -> None:
        br_client = _branch_client()
        br_client.post("/v1/branches", json=_sample_branch_payload(ifsc))

    def test_assign_pu_to_branch_emits_pu_branch_assigned(self, mocker):
        audit_mock = mocker.patch(
            "apps.api.routers.branches._write_pu_audit"
        )
        self._seed_branch()
        br_client = _branch_client()
        br_client.put("/v1/branches/KARB0000123", json={"pu_id": "MUMBAI-PU-01"})
        audit_mock.assert_called_once()
        call_args = audit_mock.call_args
        assert call_args[0][1].value == "PU_BRANCH_ASSIGNED"

    def test_reassign_pu_emits_pu_branch_reassigned(self, mocker):
        from apps.api.routers.branches import _BRANCH_STORE
        # Seed branch already assigned to one PU
        _BRANCH_STORE["KARB0000123"] = {
            "branch_id": "b1",
            "bank_id": "test-bank",
            "branch_name": "Test Branch",
            "branch_ifsc": "KARB0000123",
            "city": None,
            "district": None,
            "state": None,
            "address": None,
            "pin_code": None,
            "phone_number": None,
            "pu_id": "MUMBAI-PU-01",
            "smb_id": None,
            "is_scanning_enabled": True,
            "is_active": True,
            "created_at": "2026-08-06T00:00:00+00:00",
            "updated_at": None,
            "created_by": "system",
        }
        audit_mock = mocker.patch("apps.api.routers.branches._write_pu_audit")
        br_client = _branch_client()
        br_client.put("/v1/branches/KARB0000123", json={"pu_id": "DELHI-PU-01"})
        audit_mock.assert_called_once()
        call_args = audit_mock.call_args
        assert call_args[0][1].value == "PU_BRANCH_REASSIGNED"

    def test_update_branch_non_pu_field_does_not_emit_pu_audit(self, mocker):
        self._seed_branch()
        audit_mock = mocker.patch("apps.api.routers.branches._write_pu_audit")
        br_client = _branch_client()
        br_client.put("/v1/branches/KARB0000123", json={"branch_name": "New Name"})
        audit_mock.assert_not_called()
