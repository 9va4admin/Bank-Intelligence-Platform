"""AlertAuditor: the audit trail around every alert. Intent is recorded before sending, the outcome after, lifecycle changes as they happen.
It must never block or break a send, and it must never carry a raw address or message body."""
import asyncio
import json

from shared.alerting.audit import AlertAuditor
from shared.audit.audit_event import AuditEventType
from shared.utils.masking import mask_email


class _Sink:
    def __init__(self, fail=False, none=False):
        self.events, self.fail, self.none = [], fail, none

    async def __call__(self, event_type, bank_id, entity_id, actor_id, payload):
        if self.fail:
            raise ConnectionError("immudb down")
        if self.none:
            return None
        self.events.append(dict(event_type=event_type, bank_id=bank_id, entity_id=entity_id, actor_id=actor_id, payload=payload))
        return f"tx-{len(self.events)}"


def _run(coro):
    return asyncio.run(coro)


def test_mask_email_keeps_the_first_letter_and_the_domain():
    assert mask_email("n.shah12@gmail.com") == "n***@gmail.com"
    assert mask_email("") == "***"
    assert mask_email("not-an-address") == "n***"


def test_the_alert_event_types_exist():
    for name in ("ALERT_RAISED", "ALERT_RESOLVED", "ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED", "ALERT_DELIVERY_FAILED",
                 "ALERT_ACKNOWLEDGED", "ALERT_ESCALATED", "ALERT_SUPPRESSED", "ALERT_ROUTING_POLICY_CHANGED"):
        assert AuditEventType[name].value == name


def test_intent_is_recorded_with_a_masked_recipient_and_no_body():
    sink = _Sink()
    a = AlertAuditor(sink)
    ref = _run(a.intent(bank_id="kbl", incident_id="inc1", delivery_id="d1", channel="email", recipient="n.shah12@gmail.com", level=0,
                        template_id="PLATFORM_HEALTH_ALERT", severity="P0", component="redis"))
    ev = sink.events[0]
    assert ref == "tx-1" and ev["event_type"] == "ALERT_DISPATCH_INTENDED" and ev["bank_id"] == "kbl" and ev["entity_id"] == "inc1"
    assert ev["actor_id"] == "system:alert-engine"
    assert ev["payload"]["recipient_ref"] == "n***@gmail.com" and ev["payload"]["channel"] == "email" and ev["payload"]["delivery_id"] == "d1"
    assert "n.shah12@gmail.com" not in json.dumps(ev)


def test_a_phone_recipient_is_masked_to_the_last_four_digits():
    sink = _Sink()
    _run(AlertAuditor(sink).intent(bank_id="kbl", incident_id="i", delivery_id="d", channel="whatsapp", recipient="+919876543210", level=0,
                                   template_id="t", severity="P0", component="c"))
    assert sink.events[0]["payload"]["recipient_ref"] == "******3210" and "9876543210" not in json.dumps(sink.events[0])


def test_a_user_reference_for_the_bell_is_kept_as_is_because_it_is_not_an_address():
    sink = _Sink()
    _run(AlertAuditor(sink).intent(bank_id="kbl", incident_id="i", delivery_id="d", channel="bell", recipient="user-42", level=0,
                                   template_id="t", severity="P0", component="c"))
    assert sink.events[0]["payload"]["recipient_ref"] == "user-42"


def test_the_outcome_records_success_and_failure_with_the_reason_class():
    sink = _Sink()
    a = AlertAuditor(sink)
    _run(a.outcome(bank_id="kbl", incident_id="i", delivery_id="d1", channel="email", succeeded=True, attempt=1, intent_ref="tx-0"))
    _run(a.outcome(bank_id="kbl", incident_id="i", delivery_id="d2", channel="email", succeeded=False, attempt=2, intent_ref="tx-9",
                   error="535 authentication failed for n.shah12@gmail.com password=hunter2"))
    ok, bad = sink.events
    assert ok["event_type"] == "ALERT_DELIVERY_SUCCEEDED" and ok["payload"]["intent_ref"] == "tx-0" and ok["payload"]["attempt"] == 1
    assert bad["event_type"] == "ALERT_DELIVERY_FAILED" and bad["payload"]["attempt"] == 2
    blob = json.dumps(bad)
    assert "hunter2" not in blob and "n.shah12@gmail.com" not in blob          # the reason is kept, secrets and addresses are not


def test_lifecycle_events_carry_the_actor():
    sink = _Sink()
    a = AlertAuditor(sink)
    _run(a.lifecycle(AuditEventType.ALERT_ACKNOWLEDGED, bank_id="kbl", incident_id="i", actor="user-7", detail={"level": 1}))
    ev = sink.events[0]
    assert ev["event_type"] == "ALERT_ACKNOWLEDGED" and ev["actor_id"] == "user-7" and ev["payload"]["level"] == 1


def test_an_audit_failure_never_raises_and_is_reported_as_a_backlog():
    failures = []
    a = AlertAuditor(_Sink(fail=True), on_failure=lambda **kw: failures.append(kw))
    ref = _run(a.intent(bank_id="kbl", incident_id="i", delivery_id="d", channel="email", recipient="a@b.c", level=0, template_id="t",
                        severity="P0", component="c"))
    assert ref is None and len(failures) == 1 and failures[0]["bank_id"] == "kbl" and failures[0]["event_type"] == "ALERT_DISPATCH_INTENDED"


def test_a_sink_that_returns_nothing_counts_as_a_failure_and_the_fallback_is_tried():
    failures, fallback = [], _Sink()
    a = AlertAuditor(_Sink(none=True), fallback=fallback, on_failure=lambda **kw: failures.append(kw))
    ref = _run(a.lifecycle(AuditEventType.ALERT_RAISED, bank_id="kbl", incident_id="i", actor="system:alert-engine", detail={}))
    assert ref == "tx-1" and fallback.events[0]["event_type"] == "ALERT_RAISED" and failures == []


def test_with_no_sink_at_all_nothing_breaks():
    failures = []
    a = AlertAuditor(None, on_failure=lambda **kw: failures.append(kw))
    assert _run(a.lifecycle(AuditEventType.ALERT_RAISED, bank_id="kbl", incident_id="i", actor="x", detail={})) is None
    assert len(failures) == 1
