"""GET /v1/ops/components: what the health monitor knows about each dependency, read from the running PlatformHealthCheckWorkflow.

The monitor is also reported on: RUNNING, STALE (it has stopped ticking), NOT_RUNNING (no such workflow), UNAVAILABLE (cannot reach Temporal).
Roles as the other ops endpoints (ops_manager, bank_it_admin); unauthenticated is 401.
"""
import time
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(role="ops_manager", snapshot=None, query_error=None, temporal=True):
    from apps.api.routers.observability import get_current_user, router_v1
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {"bank_id": "kbl", "user_id": "u1", "role": role}
    if not temporal:
        app.state.temporal_client = None
        return app
    handle = MagicMock()
    if query_error is not None:
        handle.query = AsyncMock(side_effect=query_error)
    else:
        handle.query = AsyncMock(return_value=snapshot)
    client = MagicMock()
    client.get_workflow_handle = MagicMock(return_value=handle)
    app.state.temporal_client = client
    app.state.health_handle = handle
    return app


def _snap(age=30.0, **states):
    now = time.time()
    return {"tick": 7, "last_tick_at": now - age, "states": states}


def _state(status="OK", **kw):
    base = dict(status=status, since=time.time() - 600, consecutive_failures=0, last_checked=time.time() - 20, last_latency_ms=4.2,
                last_error=None, critical=True)
    base.update(kw)
    return base


def _get(app):
    return TestClient(app, raise_server_exceptions=False).get("/v1/ops/components")


def test_lists_each_component_with_state_latency_and_error():
    app = _app(snapshot=_snap(yugabyte=_state("OK", last_latency_ms=12.5),
                              redis=_state("DOWN", last_error="ConnectionError: refused", consecutive_failures=5, last_latency_ms=None)))
    r = _get(app)
    assert r.status_code == 200
    body = r.json()
    assert body["monitor"] == "RUNNING" and body["bank_id"] == "kbl"
    by = {c["component"]: c for c in body["components"]}
    assert by["yugabyte"]["status"] == "OK" and by["yugabyte"]["latency_ms"] == 12.5
    assert by["redis"]["status"] == "DOWN" and "refused" in by["redis"]["last_error"] and by["redis"]["consecutive_failures"] == 5


def test_the_query_goes_to_this_banks_monitor():
    app = _app(snapshot=_snap())
    _get(app)
    app.state.temporal_client.get_workflow_handle.assert_called_once_with("cts-platform-health-kbl")
    assert app.state.health_handle.query.await_args.args[0] == "component_states"


def test_down_components_sort_first_then_slow_then_ok():
    app = _app(snapshot=_snap(a_ok=_state("OK"), b_down=_state("DOWN"), c_slow=_state("SLOW")))
    assert [c["component"] for c in _get(app).json()["components"]] == ["b_down", "c_slow", "a_ok"]


def test_a_monitor_that_stopped_ticking_is_reported_stale_not_healthy():
    app = _app(snapshot=_snap(age=900.0, yugabyte=_state("OK")))
    body = _get(app).json()
    assert body["monitor"] == "STALE" and body["last_tick_age_seconds"] >= 900


def test_no_such_workflow_means_the_monitor_is_not_running():
    app = _app(query_error=RuntimeError("workflow not found"))
    body = _get(app).json()
    assert body["monitor"] == "NOT_RUNNING" and body["components"] == []


def test_without_a_temporal_client_the_monitor_is_unavailable_and_it_is_still_a_200():
    r = _get(_app(temporal=False))
    assert r.status_code == 200 and r.json()["monitor"] == "UNAVAILABLE"


def test_roles_and_authentication():
    assert _get(_app(role="fraud_analyst", snapshot=_snap())).status_code == 403
    assert _get(_app(role="bank_it_admin", snapshot=_snap())).status_code == 200
    from apps.api.routers.observability import router_v1
    bare = FastAPI()
    bare.include_router(router_v1)
    assert TestClient(bare, raise_server_exceptions=False).get("/v1/ops/components").status_code == 401


def test_no_credentials_in_the_response():
    app = _app(snapshot=_snap(yugabyte=_state("DOWN", last_error="could not connect to postgresql://yugabyte:***@db:5433/x")))
    text = _get(app).text
    assert "hunter2" not in text and "password" not in text.lower()
