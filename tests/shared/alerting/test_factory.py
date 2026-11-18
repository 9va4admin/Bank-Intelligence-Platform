"""build_alert_auditor: the production sink is the Redis audit stream (durable, fast) with a direct Immudb write as the fallback; every
setting comes from configuration."""
import asyncio
from unittest.mock import AsyncMock, patch

from shared.alerting.factory import build_alert_auditor
from shared.audit.audit_event import AuditEventType


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _event(a):
    return asyncio.run(a.lifecycle(AuditEventType.ALERT_RAISED, bank_id="kbl", incident_id="inc1", actor="system:alert-engine", detail={"k": 1}))


def test_events_go_to_the_audit_stream_first():
    buf = AsyncMock(return_value="1700-0")
    with patch("shared.alerting.factory.buffer_audit_event", buf):
        a = asyncio.run(build_alert_auditor(_Cfg(), "kbl", redis=object(), immudb_writer=None))
        ref = _event(a)
    assert ref == "1700-0"
    kw = buf.await_args.kwargs if buf.await_args.kwargs else {}
    args = buf.await_args.args
    assert "ALERT_RAISED" in args or kw.get("event_type") == "ALERT_RAISED"


def test_when_the_stream_is_unavailable_immudb_is_written_directly_into_the_configured_collection():
    writer = AsyncMock()
    writer.write = AsyncMock(return_value="tx-5")
    cfg = _Cfg(**{"alerting.audit_collection_pattern": "alerts_{bank_id}"})
    with patch("shared.alerting.factory.buffer_audit_event", AsyncMock(return_value=None)):
        a = asyncio.run(build_alert_auditor(cfg, "kbl", redis=object(), immudb_writer=writer))
        ref = _event(a)
    assert ref == "tx-5"
    kw = writer.write.await_args.kwargs
    assert kw["collection"] == "alerts_kbl" and kw["event_type"] == "ALERT_RAISED" and kw["bank_id"] == "kbl"


def test_the_collection_default_follows_the_existing_audit_naming_when_not_configured():
    writer = AsyncMock()
    writer.write = AsyncMock(return_value="tx-1")
    a = asyncio.run(build_alert_auditor(_Cfg(), "kbl", redis=None, immudb_writer=writer))
    _event(a)
    assert writer.write.await_args.kwargs["collection"] == "cts_kbl"


def test_the_error_length_comes_from_configuration():
    writer = AsyncMock()
    writer.write = AsyncMock(return_value="tx-1")
    a = asyncio.run(build_alert_auditor(_Cfg(**{"alerting.audit_max_error_chars": 10}), "kbl", redis=None, immudb_writer=writer))
    asyncio.run(a.outcome(bank_id="kbl", incident_id="i", delivery_id="d", channel="email", succeeded=False, attempt=1, intent_ref=None,
                          error="x" * 100))
    assert len(writer.write.await_args.kwargs["payload"]["error"]) == 10


def test_with_neither_redis_nor_immudb_an_auditor_still_exists_and_reports_failure():
    failures = []
    a = asyncio.run(build_alert_auditor(_Cfg(), "kbl", redis=None, immudb_writer=None, on_failure=lambda **kw: failures.append(kw)))
    assert _event(a) is None and len(failures) == 1
