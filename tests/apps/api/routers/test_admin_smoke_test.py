"""Tests for admin smoke-test router — entity-scoped pre-live validation."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_app(entity_type: str = "sb", role: str = "bank_it_admin"):
    """Build a minimal FastAPI app with the smoke-test router wired in."""
    from fastapi import FastAPI
    from apps.api.routers.admin_smoke_test import router, SmokeTestStatus

    app = FastAPI()
    app.include_router(router)

    # Inject a mock current_user dependency
    from apps.api.routers.admin_smoke_test import get_current_entity_context
    from shared.auth.connectors.base import ASTRAIdentity
    import time

    mock_identity = ASTRAIdentity(
        user_id="u-001",
        username="test.admin",
        display_name="Test Admin",
        entity_type=entity_type,
        entity_id="saraswat-coop",
        bank_id="saraswat-coop",
        role=role,
        connector_used="local",
        authenticated_at=time.time(),
    )

    app.dependency_overrides[get_current_entity_context] = lambda: mock_identity
    return app


# ── SB tests ─────────────────────────────────────────────────────────────────

def test_sb_smoke_test_returns_sb_tests():
    app = _make_app(entity_type="sb")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="test_cbs", name="CBS Connectivity", entity_scope="sb",
                            status=SmokeTestStatus.PASS, latency_ms=12, message="Finacle OK"),
            SmokeTestResult(test_id="test_ngch", name="NGCH Adapter", entity_scope="sb",
                            status=SmokeTestStatus.PASS, latency_ms=45, message="SFTP connected"),
            SmokeTestResult(test_id="test_iet_watchdog", name="IET Watchdog", entity_scope="sb",
                            status=SmokeTestStatus.PASS, latency_ms=480, message="Synthetic cheque OK"),
        ]
        response = client.get("/v1/admin/smoke-test")

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 3
    test_ids = [r["test_id"] for r in data["results"]]
    assert "test_cbs" in test_ids
    assert "test_iet_watchdog" in test_ids


def test_sb_smoke_test_does_not_include_branch_tests():
    app = _make_app(entity_type="sb")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        response = client.get("/v1/admin/smoke-test")

    # Verify run_all_tests was called with entity_type="sb"
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("entity_type") == "sb" or call_kwargs.args[0] == "sb"


# ── SMB tests ─────────────────────────────────────────────────────────────────

def test_smb_smoke_test_returns_smb_scoped_tests():
    app = _make_app(entity_type="smb", role="smb_admin")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="test_auth_smb", name="SMB Auth Connector", entity_scope="smb",
                            status=SmokeTestStatus.PASS, latency_ms=8, message="Local DB reachable"),
            SmokeTestResult(test_id="test_sftp_push", name="Agency SFTP Push", entity_scope="smb",
                            status=SmokeTestStatus.PASS, latency_ms=120, message="SFTP writable"),
            SmokeTestResult(test_id="test_vault_seeded", name="Vault Seeded", entity_scope="smb",
                            status=SmokeTestStatus.WARN, latency_ms=5,
                            message="Only 2 signatures seeded — seed all accounts before go-live"),
        ]
        response = client.get("/v1/admin/smoke-test")

    assert response.status_code == 200
    data = response.json()
    test_ids = [r["test_id"] for r in data["results"]]
    assert "test_auth_smb" in test_ids
    assert "test_vault_seeded" in test_ids
    # CBS should NOT be in SMB tests if no SMB_CBS connection configured
    # (test_cbs is SB-only)
    assert "test_cbs" not in test_ids


# ── Branch tests ─────────────────────────────────────────────────────────────

def test_branch_smoke_test_returns_branch_scoped_tests():
    app = _make_app(entity_type="branch", role="ops_reviewer")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="test_scanner_folder", name="Scanner Drop Folder", entity_scope="branch",
                            status=SmokeTestStatus.PASS, latency_ms=2, message="/opt/astra/scanner writable"),
            SmokeTestResult(test_id="test_auth_branch", name="Branch Auth Connector", entity_scope="branch",
                            status=SmokeTestStatus.PASS, latency_ms=15, message="LDAP bind OK"),
            SmokeTestResult(test_id="test_eeh_connectivity", name="EEH Session", entity_scope="branch",
                            status=SmokeTestStatus.PASS, latency_ms=5, message="gRPC ping OK"),
        ]
        response = client.get("/v1/admin/smoke-test")

    assert response.status_code == 200
    data = response.json()
    test_ids = [r["test_id"] for r in data["results"]]
    assert "test_scanner_folder" in test_ids
    assert "test_eeh_connectivity" in test_ids
    assert "test_cbs" not in test_ids
    assert "test_iet_watchdog" not in test_ids


# ── PU / Agency CC tests ──────────────────────────────────────────────────────

def test_pu_smoke_test_returns_pu_scoped_tests():
    app = _make_app(entity_type="pu", role="ops_manager")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="test_sb_connector", name="SB Connector", entity_scope="pu",
                            status=SmokeTestStatus.PASS, latency_ms=65, message="SFTP connected to SB"),
            SmokeTestResult(test_id="test_auth_pu", name="PU Auth Connector", entity_scope="pu",
                            status=SmokeTestStatus.PASS, latency_ms=14, message="LDAP bind OK"),
            SmokeTestResult(test_id="test_eeh_connectivity", name="EEH Session", entity_scope="pu",
                            status=SmokeTestStatus.PASS, latency_ms=4, message="gRPC ping OK"),
            SmokeTestResult(test_id="test_scanner_folder", name="Scanner Drop Folder", entity_scope="pu",
                            status=SmokeTestStatus.FAIL, latency_ms=1,
                            message="/opt/astra/scanner not found — create directory and set permissions"),
        ]
        response = client.get("/v1/admin/smoke-test")

    assert response.status_code == 200
    data = response.json()
    test_ids = [r["test_id"] for r in data["results"]]
    assert "test_sb_connector" in test_ids
    assert "test_scanner_folder" in test_ids
    assert "test_cbs" not in test_ids
    assert "test_iet_watchdog" not in test_ids


# ── Individual test endpoint ──────────────────────────────────────────────────

def test_run_single_test_endpoint():
    app = _make_app(entity_type="sb")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_single_test", new_callable=AsyncMock) as mock_single:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_single.return_value = SmokeTestResult(
            test_id="test_cbs", name="CBS Connectivity", entity_scope="sb",
            status=SmokeTestStatus.PASS, latency_ms=12, message="Finacle OK"
        )
        response = client.get("/v1/admin/smoke-test/test_cbs")

    assert response.status_code == 200
    data = response.json()
    assert data["test_id"] == "test_cbs"
    assert data["status"] == "PASS"


def test_run_single_test_wrong_entity_scope_returns_403():
    """SMB user cannot run SB-only test like test_cbs."""
    app = _make_app(entity_type="smb", role="smb_admin")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_single_test", new_callable=AsyncMock) as mock_single:
        from apps.api.routers.admin_smoke_test import EntityScopeMismatchError
        mock_single.side_effect = EntityScopeMismatchError("test_cbs is for entity_type=sb, not smb")
        response = client.get("/v1/admin/smoke-test/test_cbs")

    assert response.status_code == 403


# ── Result model ──────────────────────────────────────────────────────────────

def test_smoke_test_result_model():
    from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
    result = SmokeTestResult(
        test_id="test_kafka",
        name="Kafka Connectivity",
        entity_scope="sb",
        status=SmokeTestStatus.FAIL,
        latency_ms=None,
        message="Broker unreachable at kafka:9092",
    )
    assert result.status == SmokeTestStatus.FAIL
    assert result.latency_ms is None


def test_smoke_test_summary_fields():
    """Response must include a summary: total / pass / fail / warn counts."""
    app = _make_app(entity_type="sb")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="t1", name="T1", entity_scope="sb", status=SmokeTestStatus.PASS, latency_ms=10, message="ok"),
            SmokeTestResult(test_id="t2", name="T2", entity_scope="sb", status=SmokeTestStatus.FAIL, latency_ms=None, message="fail"),
            SmokeTestResult(test_id="t3", name="T3", entity_scope="sb", status=SmokeTestStatus.WARN, latency_ms=50, message="slow"),
        ]
        response = client.get("/v1/admin/smoke-test")

    data = response.json()
    assert data["summary"]["total"] == 3
    assert data["summary"]["pass"] == 1
    assert data["summary"]["fail"] == 1
    assert data["summary"]["warn"] == 1
    assert data["summary"]["all_clear"] is False


def test_smoke_test_all_clear_true_when_no_failures():
    app = _make_app(entity_type="sb")
    client = TestClient(app)

    with patch("apps.api.routers.admin_smoke_test.run_all_tests", new_callable=AsyncMock) as mock_run:
        from apps.api.routers.admin_smoke_test import SmokeTestResult, SmokeTestStatus
        mock_run.return_value = [
            SmokeTestResult(test_id="t1", name="T1", entity_scope="sb", status=SmokeTestStatus.PASS, latency_ms=10, message="ok"),
            SmokeTestResult(test_id="t2", name="T2", entity_scope="sb", status=SmokeTestStatus.WARN, latency_ms=50, message="warn"),
        ]
        response = client.get("/v1/admin/smoke-test")

    data = response.json()
    # WARN does not block go-live — only FAIL blocks
    assert data["summary"]["all_clear"] is True
    assert data["summary"]["fail"] == 0
