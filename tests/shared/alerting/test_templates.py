"""The alert email: subject convention, what an on-call person needs in the body (incident, time in the bank's timezone, impact, what to do, links),
HTML that cannot be injected into, and every setting from configuration."""
import asyncio
import re

import pytest

from shared.alerting.templates import AlertContent, TemplateSettings, load_template_settings, render_email, render_short

SETTINGS = TemplateSettings(ui_base_url="https://astra.bank.example", runbook_base_url="https://runbooks.bank.example",
                            timezone="Asia/Kolkata", message_max_chars=500, runbook_map={"COMPONENT_DOWN": "component-down"})


def _content(**kw):
    base = dict(bank_id="kbl", severity="P0", component="redis", event_type="COMPONENT_DOWN", message="redis is not responding (3 failed checks)",
                incident_id="inc-123", occurred_at=0.0, down_for="")
    base.update(kw)
    return AlertContent(**base)


def test_subject_follows_the_convention_so_mail_rules_and_phones_can_sort_it():
    r = render_email(_content(), SETTINGS)
    assert r.subject == "[ASTRA][P0][kbl][redis] redis is not responding (3 failed checks)"


def test_a_recovery_is_labelled_resolved_not_with_its_severity():
    r = render_email(_content(severity="P3", event_type="COMPONENT_RECOVERED", message="redis is responding again after 4m down", down_for="4m"), SETTINGS)
    assert r.subject.startswith("[ASTRA][RESOLVED][kbl][redis]") and "4m" in r.text


def test_the_text_body_has_what_an_on_call_person_needs():
    t = render_email(_content(), SETTINGS).text
    assert "inc-123" in t and "P0" in t and "redis" in t
    assert "05:30" in t and "IST" in t and "00:00" in t and "UTC" in t         # the bank's time and UTC (epoch 0 = 05:30 IST)
    assert "https://astra.bank.example/ops/incidents/inc-123" in t               # dashboard link
    assert "https://runbooks.bank.example/component-down" in t                   # what to do
    assert "acknowledge" in t.lower()
    assert "redis" in t.lower() and "cheque" in t.lower()                        # impact: what stops working (cheque processing for a core dependency)


def test_links_are_left_out_when_the_bank_has_not_configured_them():
    r = render_email(_content(), TemplateSettings(timezone="Asia/Kolkata", message_max_chars=500))
    assert "http" not in r.text and "href" not in r.html and "None" not in r.text


def test_the_html_escapes_everything_dynamic():
    r = render_email(_content(message="<script>alert(1)</script> & <b>x</b>", component="re<dis>"), SETTINGS)
    assert "<script>" not in r.html and "&lt;script&gt;" in r.html and "<b>x</b>" not in r.html
    assert "re&lt;dis&gt;" in r.html


def test_the_html_shows_severity_in_words_not_only_in_colour_and_has_a_text_twin():
    r = render_email(_content(severity="P0"), SETTINGS)
    assert "P0" in r.html and "CRITICAL" in r.html.upper()
    assert r.text and r.html.startswith("<")
    low = render_email(_content(severity="P2"), SETTINGS)
    assert "WARNING" in low.html.upper() and low.html != r.html


def test_control_characters_are_removed_and_a_long_message_is_cut_to_the_configured_length():
    r = render_email(_content(message="line1\r\nSubject: injected\x00\x07" + "x" * 2000), TemplateSettings(message_max_chars=50))
    assert "\r" not in r.subject and "\n" not in r.subject and "\x00" not in r.text
    assert len(re.search(r"line1.*", r.subject).group(0)) <= 120


def test_a_bad_timezone_falls_back_to_utc_and_never_breaks_the_mail():
    r = render_email(_content(), TemplateSettings(timezone="Not/AZone", message_max_chars=500))
    assert "UTC" in r.text


def test_the_short_form_for_the_bell_and_text_messages():
    title, body = render_short(_content(), SETTINGS)
    assert title.startswith("P0") and "redis" in title and "redis is not responding" in body


def test_settings_come_from_configuration_with_safe_defaults():
    class Cfg:
        def __init__(self, **v):
            self.v = v

        async def get(self, key):
            from shared.config.config_service import ConfigKeyNotFoundError
            if key not in self.v:
                raise ConfigKeyNotFoundError(key)
            return self.v[key]
    s = asyncio.run(load_template_settings(Cfg(**{"alerting.ui_base_url": "https://a.example/", "alerting.timezone": "Asia/Kolkata",
                                                  "alerting.message_max_chars": 80, "alerting.runbook_map": '{"COMPONENT_DOWN": "cd"}',
                                                  "alerting.runbook_base_url": "https://r.example"})))
    assert s.ui_base_url == "https://a.example" and s.message_max_chars == 80 and s.runbook_map == {"COMPONENT_DOWN": "cd"}      # trailing slash trimmed
    empty = asyncio.run(load_template_settings(Cfg()))
    assert empty.ui_base_url == "" and empty.message_max_chars > 0 and empty.timezone


def test_every_severity_and_kind_renders():
    for sev in ("P0", "P1", "P2", "P3"):
        for ev in ("COMPONENT_DOWN", "COMPONENT_REMINDER", "COMPONENT_SLOW", "COMPONENT_SLOW_CLEARED", "COMPONENT_RECOVERED", "IET_BREACH_RISK", "UNKNOWN_X"):
            r = render_email(_content(severity=sev, event_type=ev), SETTINGS)
            assert r.subject and r.text and r.html
