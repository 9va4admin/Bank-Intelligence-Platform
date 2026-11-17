"""dispatch_platform_alert with the audit trail: intent BEFORE each send, outcome AFTER, and an audit problem never stops the alert."""
import asyncio

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.alerting.audit import AlertAuditor


class _Log:
    def __init__(self):
        self.entries = []


class _Disp:
    def __init__(self, log, fail_channels=()):
        self.log, self.fail_channels = log, fail_channels

    async def send(self, request):
        self.log.entries.append(("send", request.channel, request.recipient))
        if request.channel in self.fail_channels:
            raise RuntimeError("535 authentication failed for ops@x.in password=hunter2")


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _sink(log, fail=False):
    async def sink(event_type, bank_id, entity_id, actor_id, payload):
        if fail:
            raise ConnectionError("immudb down")
        log.entries.append(("audit", event_type, entity_id, payload))
        return f"tx-{len(log.entries)}"
    return sink


def _alert(**kw):
    base = dict(bank_id="kbl", event_type="COMPONENT_DOWN", component="redis", message="m", severity="CRITICAL", priority="P0", incident_id="inc-7")
    base.update(kw)
    return DispatchAlertInput(**base)


def _cfg():
    return _Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001"})


def _run(log, *, fail_channels=(), audit_fails=False, auditor="default"):
    a = AlertAuditor(_sink(log, fail=audit_fails)) if auditor == "default" else auditor
    return asyncio.run(dispatch_platform_alert(_alert(), dispatcher=_Disp(log, fail_channels), config_service=_cfg(), alert_auditor=a))


def test_intent_is_written_before_each_send_and_the_outcome_after():
    log = _Log()
    res = _run(log)
    assert res.sent
    kinds = [(e[0], e[1]) for e in log.entries]
    email = [i for i, k in enumerate(kinds) if k == ("send", "email")][0]
    assert kinds[email - 1] == ("audit", "ALERT_DISPATCH_INTENDED")
    assert kinds[email + 1] == ("audit", "ALERT_DELIVERY_SUCCEEDED")
    wa = [i for i, k in enumerate(kinds) if k == ("send", "whatsapp")][0]
    assert kinds[wa - 1] == ("audit", "ALERT_DISPATCH_INTENDED") and kinds[wa + 1] == ("audit", "ALERT_DELIVERY_SUCCEEDED")


def test_every_record_belongs_to_the_incident_and_the_outcome_points_back_at_the_intent():
    log = _Log()
    _run(log)
    audits = [e for e in log.entries if e[0] == "audit"]
    assert {e[2] for e in audits} == {"inc-7"}
    intent, outcome = audits[0], audits[1]
    assert outcome[3]["intent_ref"] is not None and outcome[3]["delivery_id"] == intent[3]["delivery_id"]


def test_a_failed_send_is_recorded_as_a_failure_with_a_scrubbed_reason_and_the_other_channel_still_goes():
    log = _Log()
    res = _run(log, fail_channels=("email",))
    failed = [e for e in log.entries if e[0] == "audit" and e[1] == "ALERT_DELIVERY_FAILED"]
    assert len(failed) == 1 and "hunter2" not in str(failed[0]) and "ops@x.in" not in str(failed[0])
    assert ("send", "whatsapp", "+919800000001") in log.entries and res.sent


def test_an_audit_outage_never_stops_the_alert():
    log = _Log()
    res = _run(log, audit_fails=True)
    assert res.sent and [e[1] for e in log.entries if e[0] == "send"] == ["email", "whatsapp"]


def test_without_an_auditor_the_alert_is_still_sent():
    log = _Log()
    assert _run(log, auditor=None).sent


def test_an_alert_without_an_incident_id_still_gets_a_correlation_id():
    log = _Log()
    a = AlertAuditor(_sink(log))
    asyncio.run(dispatch_platform_alert(_alert(incident_id=""), dispatcher=_Disp(log), config_service=_cfg(), alert_auditor=a))
    assert all(e[2] for e in log.entries if e[0] == "audit")
