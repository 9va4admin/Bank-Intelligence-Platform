"""Admin configuration: an approved change must actually reach platform.config_values (it never did: approval only
marked the pending row APPROVED and published an event, so no setting changed), the schema must agree with the built-in
defaults, and bad values are refused at submission."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Tx:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self):
        self.conn.tx_open = True
        return self
    async def __aexit__(self, exc_type, *x):
        self.conn.tx_open = False
        if exc_type is not None:
            self.conn.rolled_back = True          # whatever ran inside is undone
        return False


class _Conn:
    def __init__(self, pending, old_value=None):
        self.pending, self.executed, self.released = pending, [], False
        self.old_value, self.tx_open, self.rolled_back = old_value, False, False

    def transaction(self):
        return _Tx(self)

    async def fetchrow(self, sql, *a):
        self._live()
        if "FROM platform.config_values" in sql:                    # the value being replaced
            return {"config_value": self.old_value} if self.old_value is not None else None
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
    def __init__(self, pending=None, old_value=None):
        self.conn = _Conn(pending, old_value)

    def acquire(self):
        return _Acq(self.conn)


def _app(role, pool=None, user_id="user-001", audit=None):
    from apps.api.routers.admin import (get_audit_stream_writer, get_current_user, get_event_publisher,
                                        get_notification_publisher, router_v1)

    async def noop(*a, **k):
        return None

    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user] = lambda: {"bank_id": "kbl", "user_id": user_id, "role": role}
    app.dependency_overrides[get_event_publisher] = lambda: noop
    app.dependency_overrides[get_audit_stream_writer] = lambda: (audit or noop)
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


# --- every change is audited, atomically with the change, and records what it replaced -------------------------------

def test_the_audit_record_of_an_approval_carries_the_old_and_new_value_and_both_people():
    seen = []

    async def audit(**kw):
        seen.append(kw)

    pool = _Pool(_pending("custody_retention_years", "12"), old_value="10")
    r = _app("bank_it_admin", pool, user_id="checker-1", audit=audit).post("/v1/admin/config/thresholds/chg-1/approve")
    assert r.status_code == 200
    approved = [k["payload"] for k in seen if k["payload"].get("action") == "APPROVED"]
    assert len(approved) == 1
    p = approved[0]
    assert p["config_key"] == "custody_retention_years" and p["old_value"] == "10" and p["new_value"] == "12"
    assert p["submitted_by"] == "maker-1" and p["approved_by"] == "checker-1"


def test_the_old_value_is_the_default_in_force_when_nothing_had_been_set_yet():
    seen = []

    async def audit(**kw):
        seen.append(kw)

    pool = _Pool(_pending("custody_retention_years", "12"), old_value=None)       # no row: the built-in default applied
    _app("bank_it_admin", pool, user_id="checker-1", audit=audit).post("/v1/admin/config/thresholds/chg-1/approve")
    assert [k["payload"]["old_value"] for k in seen if k["payload"].get("action") == "APPROVED"] == ["10"]


def test_an_approval_that_cannot_be_audited_is_not_applied():
    from fastapi import HTTPException

    async def broken_audit(**kw):
        raise HTTPException(status_code=503, detail="Audit trail unavailable")

    pool = _Pool(_pending("custody_retention_years", "12"), old_value="10")
    r = _app("bank_it_admin", pool, user_id="checker-1", audit=broken_audit).post("/v1/admin/config/thresholds/chg-1/approve")
    assert r.status_code == 503
    assert pool.conn.rolled_back is True                 # the new value and the APPROVED mark were undone


def test_custody_retention_years_is_an_editable_setting_with_the_same_maker_checker_path():
    from apps.api.routers.admin import _SCHEMA_BY_KEY
    assert _SCHEMA_BY_KEY["custody_retention_years"]["value_type"] == "int"
    assert _SCHEMA_BY_KEY["custody_branch_hold_days"]["value_type"] == "int"


# --- the real writer must match the audit buffer's contract and fail closed --------------------------------------

def _request_with_redis(redis):
    from types import SimpleNamespace
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis_cts=redis)))


def test_the_real_audit_writer_gives_the_buffer_the_entity_and_actor_it_requires(monkeypatch):
    import asyncio
    import shared.audit.stream_buffer as sb
    from apps.api.routers.admin import get_audit_stream_writer
    got = {}

    async def fake_buffer(redis, bank_id, event_type, entity_type, entity_id, actor_id, payload, hsm_signed=False):
        got.update(bank_id=bank_id, event_type=event_type, entity_type=entity_type, entity_id=entity_id,
                   actor_id=actor_id, payload=payload)
        return "1-0"

    monkeypatch.setattr(sb, "buffer_audit_event", fake_buffer)
    writer = get_audit_stream_writer(_request_with_redis(object()))
    asyncio.run(writer(event_type="CONFIG_CHANGE", bank_id="kbl",
                       payload={"action": "APPROVED", "config_key": "custody_retention_years", "change_id": "chg-1",
                                "approved_by": "checker-1", "new_value": "12"}))
    assert got["entity_type"] == "config" and got["entity_id"] == "custody_retention_years" and got["actor_id"] == "checker-1"


@pytest.mark.parametrize("failure", ["raises", "returns_none"])
def test_the_real_audit_writer_raises_503_when_the_event_was_not_buffered(monkeypatch, failure):
    import asyncio
    import shared.audit.stream_buffer as sb
    from fastapi import HTTPException
    from apps.api.routers.admin import get_audit_stream_writer

    async def fake_buffer(**kw):
        if failure == "raises":
            raise RuntimeError("redis down")
        return None

    monkeypatch.setattr(sb, "buffer_audit_event", lambda *a, **kw: fake_buffer(**kw))
    writer = get_audit_stream_writer(_request_with_redis(object()))
    with pytest.raises(HTTPException) as e:
        asyncio.run(writer(event_type="CONFIG_CHANGE", bank_id="kbl", payload={"config_key": "k", "approved_by": "u"}))
    assert e.value.status_code == 503


def test_with_no_audit_buffer_at_all_the_writer_refuses_rather_than_dropping_the_event():
    import asyncio
    from fastapi import HTTPException
    from apps.api.routers.admin import get_audit_stream_writer
    writer = get_audit_stream_writer(_request_with_redis(None))
    with pytest.raises(HTTPException) as e:
        asyncio.run(writer(event_type="CONFIG_CHANGE", bank_id="kbl", payload={}))
    assert e.value.status_code == 503
