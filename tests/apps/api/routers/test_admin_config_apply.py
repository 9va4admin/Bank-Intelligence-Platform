"""Admin configuration: an approved change must actually reach platform.config_values (it never did: approval only
marked the pending row APPROVED and published an event, so no setting changed), the schema must agree with the built-in
defaults, and bad values are refused at submission."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Conn:
    def __init__(self, pending):
        self.pending, self.executed, self.released = pending, [], False

    async def fetchrow(self, sql, *a):
        self._live()
        return self.pending

    async def execute(self, sql, *a):
        self._live()
        self.executed.append((sql, a))

    def _live(self):
        # asyncpg refuses to run anything on a connection that has gone back to the pool; a fake that allows it hid a bug
        if self.released:
            raise RuntimeError("connection has been released back to the pool")


class _Acq:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self):
        self.conn.released = False
        return self.conn
    async def __aexit__(self, *x):
        self.conn.released = True
        return False


class _Pool:
    def __init__(self, pending=None):
        self.conn = _Conn(pending)

    def acquire(self):
        return _Acq(self.conn)


def _app(role, pool=None, user_id="user-001"):
    from apps.api.routers.admin import (get_audit_stream_writer, get_current_user, get_event_publisher,
                                        get_notification_publisher, router_v1)

    async def noop(*a, **k):
        return None

    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {"bank_id": "kbl", "user_id": user_id, "role": role}
    app.dependency_overrides[get_event_publisher] = lambda: noop
    app.dependency_overrides[get_audit_stream_writer] = lambda: noop
    app.dependency_overrides[get_notification_publisher] = lambda: noop
    app.state.db_pool_platform = pool
    return TestClient(app, raise_server_exceptions=False)


def _pending(key, value):
    return {"config_key": key, "new_value": value, "submitted_by": "maker-1", "actioned_at": "now"}


# --- approval applies the value --------------------------------------------------------------------------------

@pytest.mark.parametrize("key,value,vtype", [
    ("allocation_mode", "AUTO", "string"),
    ("bucket_hvc_min_amount", "750000", "int"),
    ("bucket_routing_enabled", "true", "bool"),
    ("bucket_priority", '["CA","HVC","IP","FCC","LVC"]', "json"),
])
def test_approving_a_change_writes_it_to_the_config_table_with_its_type(key, value, vtype):
    pool = _Pool(_pending(key, value))
    r = _app("bank_it_admin", pool, user_id="checker-1").post("/v1/admin/config/thresholds/chg-1/approve")
    assert r.status_code == 200
    writes = [(s, a) for s, a in pool.conn.executed if "platform.config_values" in s]
    assert len(writes) == 1
    sql, args = writes[0]
    assert "ON CONFLICT" in sql
    assert args[0] == "kbl" and args[1] == "cts" and args[2] == key and args[3] == value and args[4] == vtype
    assert args[5] == "checker-1"


def test_a_self_approval_attempt_writes_nothing():
    pool = _Pool(None)                                   # the UPDATE (submitted_by != approver) matched no row
    _app("bank_it_admin", pool, user_id="maker-1").post("/v1/admin/config/thresholds/chg-1/approve")
    assert [s for s, _ in pool.conn.executed if "platform.config_values" in s] == []


# --- the schema agrees with the real defaults ------------------------------------------------------------------

def test_every_schema_default_matches_the_built_in_default():
    from apps.api.routers.admin import _LAYER3_SCHEMA
    from shared.config.config_service import _LAYER3_DEFAULTS
    import json
    wrong = []
    for s in _LAYER3_SCHEMA:
        key = "cts." + s["config_key"]
        if key not in _LAYER3_DEFAULTS:
            continue
        actual = _LAYER3_DEFAULTS[key]
        shown = s["default"]
        ok = (json.loads(shown) == actual) if s.get("value_type") == "json" else (str(actual).lower() == str(shown).lower()
                                                                                  or _num_equal(shown, actual))
        if not ok:
            wrong.append((s["config_key"], shown, actual))
    assert wrong == []


def _num_equal(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def test_the_bucket_and_allocation_settings_are_all_editable_in_the_admin_schema():
    from apps.api.routers.admin import _LAYER3_SCHEMA
    keys = {s["config_key"]: s for s in _LAYER3_SCHEMA}
    for k in ("bucket_routing_enabled", "bucket_priority", "bucket_hvc_min_amount", "bucket_lvc_max_amount",
              "bucket_frequent_min_cheques", "bucket_frequent_window_days", "bucket_corporate_account_types",
              "bucket_institution_account_types", "bucket_overflow_after_minutes", "sip_review_timeout_minutes",
              "sip_iet_guard_minutes", "allocation_strategy", "allocation_max_per_reviewer",
              "allocation_urgent_margin_minutes", "allocation_rebalance_enabled", "allocation_retry_seconds",
              "maker_checker_enabled", "checker_review_timeout_minutes"):
        assert k in keys and keys[k]["layer"] == "LAYER_3", k


# --- bad values are refused at submission ------------------------------------------------------------------------

@pytest.mark.parametrize("key,value", [
    ("allocation_mode", "RANDOMLY"),
    ("allocation_strategy", "FASTEST"),
    ("bucket_hvc_min_amount", "lots"),
    ("bucket_frequent_min_cheques", "-3"),
    ("bucket_routing_enabled", "maybe"),
    ("bucket_priority", "HVC,CA"),
    ("bucket_priority", '["HVC","NOPE"]'),
    ("bucket_corporate_account_types", '"CORPORATE"'),
])
def test_an_invalid_value_is_refused_before_it_can_be_approved(key, value):
    r = _app("ops_manager", _Pool()).post("/v1/admin/config/thresholds", json={"config_key": key, "new_value": value, "reason": "testing config apply"})
    assert r.status_code == 422


@pytest.mark.parametrize("key,value", [
    ("allocation_mode", "AUTO"), ("bucket_hvc_min_amount", "600000"), ("bucket_routing_enabled", "false"),
    ("bucket_priority", '["LVC","FCC","IP","CA","HVC"]'), ("sip_review_timeout_minutes", "20"),
])
def test_a_valid_value_is_accepted_for_approval(key, value):
    r = _app("ops_manager", _Pool()).post("/v1/admin/config/thresholds", json={"config_key": key, "new_value": value, "reason": "testing config apply"})
    assert r.status_code == 202
