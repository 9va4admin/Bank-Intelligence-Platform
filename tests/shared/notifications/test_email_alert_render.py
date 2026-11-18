"""The email channel sends platform alerts with the full template (text and HTML, subject convention) when it has template settings."""
import asyncio
import email
from types import SimpleNamespace

from shared.alerting.templates import TemplateSettings
from shared.notifications.email_channel import EmailChannel

SETTINGS = TemplateSettings(ui_base_url="https://astra.bank.example", runbook_base_url="https://rb.example", timezone="Asia/Kolkata",
                            runbook_map={"COMPONENT_DOWN": "component-down"})


class _Smtp:
    def __init__(self):
        self.sent = []

    def sendmail(self, frm, to, text):
        self.sent.append((frm, to, text))


def _channel(settings=SETTINGS):
    ch = EmailChannel("h", 25, "astra@x.in", "kbl", template_settings=settings)
    ch._smtp, ch._ready = _Smtp(), True
    return ch


def _req(template="PLATFORM_HEALTH_ALERT", **ctx):
    context = {"bank_id": "kbl", "event_type": "COMPONENT_DOWN", "severity": "CRITICAL", "component": "redis", "message": "redis is not responding",
               "down_for": "", "incident_id": "inc-1", "occurred_at": 0.0, **ctx}
    return SimpleNamespace(recipient="ops@x.in", template_id=template, notification_id="n1", context=context, priority="P0")


def _sent(ch):
    return email.message_from_string(ch._smtp.sent[0][2])


def test_an_alert_goes_out_as_text_and_html_with_the_subject_convention_and_links():
    ch = _channel()
    asyncio.run(ch.send(_req()))
    msg = _sent(ch)
    assert msg["Subject"] == "[ASTRA][P0][kbl][redis] redis is not responding"
    parts = {p.get_content_type(): p.get_payload(decode=True).decode() for p in msg.walk() if p.get_content_type().startswith("text/")}
    assert set(parts) == {"text/plain", "text/html"}
    assert "inc-1" in parts["text/plain"] and "https://astra.bank.example/ops/incidents/inc-1" in parts["text/html"]


def test_a_recovery_uses_the_resolved_subject():
    ch = _channel()
    asyncio.run(ch.send(_req("PLATFORM_HEALTH_RECOVERED", event_type="COMPONENT_RECOVERED", message="redis is responding again", down_for="4m")))
    assert _sent(ch)["Subject"].startswith("[ASTRA][RESOLVED][kbl][redis]")


def test_without_template_settings_the_original_plain_text_mail_is_unchanged():
    ch = _channel(settings=None)
    asyncio.run(ch.send(_req()))
    msg = _sent(ch)
    assert [p.get_content_type() for p in msg.walk() if p.get_content_type().startswith("text/")] == ["text/plain"]


def test_other_templates_are_not_affected():
    ch = _channel()
    asyncio.run(ch.send(SimpleNamespace(recipient="ops@x.in", template_id="cts.fraud_alert", notification_id="n", context={"bank_id": "kbl"}, priority="P1")))
    assert _sent(ch)["Subject"]
