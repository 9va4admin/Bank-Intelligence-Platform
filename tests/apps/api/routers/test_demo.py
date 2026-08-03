"""
Demo pipeline API router tests — TDD RED run before implementation exists.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from apps.api.routers.demo import router_v1
    a = FastAPI()
    a.include_router(router_v1)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ── session CRUD ──────────────────────────────────────────────────────────────

def test_create_session_returns_session_id(client):
    resp = client.post("/v1/demo/sessions", json={"bank_id": "test-bank"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["bank_id"] == "test-bank"
    assert data["item_count"] == 0


def test_create_session_with_filenames(client):
    resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg", "chq002.jpg"],
    })
    assert resp.status_code == 200
    assert resp.json()["item_count"] == 2


def test_get_session_returns_404_for_unknown(client):
    resp = client.get("/v1/demo/sessions/not-a-real-id")
    assert resp.status_code == 404


def test_get_session_after_create(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg", "chq002.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.get(f"/v1/demo/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["session_id"] == session_id
    assert data["phase"] == "idle"


# ── upload endpoint ───────────────────────────────────────────────────────────

def test_upload_endpoint_adds_items(client):
    sess_resp = client.post("/v1/demo/sessions", json={"bank_id": "test-bank"})
    session_id = sess_resp.json()["session_id"]

    resp = client.post(
        f"/v1/demo/sessions/{session_id}/upload",
        files=[
            ("files", ("chq001.jpg", b"fake-image-data", "image/jpeg")),
            ("files", ("chq002.jpg", b"fake-image-data", "image/jpeg")),
        ],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["uploaded"] == 2
    assert "chq001.jpg" in data["filenames"]


def test_upload_to_unknown_session_returns_404(client):
    resp = client.post(
        "/v1/demo/sessions/bad-id/upload",
        files=[("files", ("x.jpg", b"data", "image/jpeg"))],
    )
    assert resp.status_code == 404


# ── run endpoints ─────────────────────────────────────────────────────────────

def test_run_presentment_starts_processing(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.post(f"/v1/demo/sessions/{session_id}/run-presentment")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["items"] == 1


def test_run_presentment_fails_on_empty_session(client):
    sess_resp = client.post("/v1/demo/sessions", json={"bank_id": "test-bank"})
    session_id = sess_resp.json()["session_id"]

    resp = client.post(f"/v1/demo/sessions/{session_id}/run-presentment")
    assert resp.status_code == 400


def test_run_presentment_404_for_unknown_session(client):
    resp = client.post("/v1/demo/sessions/bad-id/run-presentment")
    assert resp.status_code == 404


# ── CSV download ──────────────────────────────────────────────────────────────

def test_csv_download_404_for_unknown_session(client):
    resp = client.get("/v1/demo/sessions/unknown/csv/presentment-success")
    assert resp.status_code == 404


def test_csv_download_returns_csv_content_type(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.get(f"/v1/demo/sessions/{session_id}/csv/presentment-success")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


def test_csv_header_row_present_before_processing(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.get(f"/v1/demo/sessions/{session_id}/csv/presentment-success")
    assert "Filename" in resp.text


def test_failure_csv_endpoint_exists(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["chq001.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.get(f"/v1/demo/sessions/{session_id}/csv/presentment-failure")
    assert resp.status_code == 200
    assert "Reject_Reason" in resp.text


def test_drawee_csv_endpoints_exist(client):
    sess_resp = client.post("/v1/demo/sessions", json={"bank_id": "test-bank"})
    session_id = sess_resp.json()["session_id"]

    for ep in ("drawee-success", "drawee-failure"):
        resp = client.get(f"/v1/demo/sessions/{session_id}/csv/{ep}")
        assert resp.status_code == 200


# ── session state reflects items ──────────────────────────────────────────────

def test_session_items_listed_with_correct_status(client):
    sess_resp = client.post("/v1/demo/sessions", json={
        "bank_id": "test-bank",
        "filenames": ["a.jpg", "b.jpg", "c.jpg"],
    })
    session_id = sess_resp.json()["session_id"]

    resp = client.get(f"/v1/demo/sessions/{session_id}")
    data = resp.json()
    assert len(data["items"]) == 3
    for item in data["items"]:
        assert item["status"] == "queued"
        assert "filename" in item
        assert "item_id" in item
