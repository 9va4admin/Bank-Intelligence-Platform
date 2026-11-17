"""SMTP sending that a real provider (Gmail now, the bank's Postal later) accepts: STARTTLS or SSL, authentication, a reconnect when the
connection has gone stale, and the whole thing configured from deployment settings, never hardcoded.

Settings (env / Helm, Layer 2): SMTP_HOST, SMTP_PORT, SMTP_SECURITY (starttls | ssl | none), SMTP_USERNAME, SMTP_FROM_ADDRESS.
Secret: smtp.password (ASTRA_SECRET_SMTP_PASSWORD in dev, Vault in production). Gmail: smtp.gmail.com / 587 / starttls / an app password.
"""
import asyncio
import smtplib
import threading
from unittest.mock import MagicMock, patch

import pytest

from shared.notifications.dispatcher import NotificationRequest
from shared.notifications.email_channel import EmailChannel
from shared.notifications.factory import SmtpSettings, build_dispatcher, read_smtp_settings


def _req(template="PLATFORM_HEALTH_ALERT", **ctx):
    return NotificationRequest(channel="email", recipient="ops@bank.example", template_id=template,
                               context={"bank_id": "kbl", "severity": "P0", "component": "yugabyte", "event_type": "COMPONENT_DOWN",
                                        "message": "db down", **ctx})


class _Smtp:
    """Records the order of calls, like the real smtplib object."""
    instances = []

    def __init__(self, host, port, timeout=None, **kw):
        self.calls = [("connect", host, port)]
        self.fail_next_send = False
        _Smtp.instances.append(self)

    def starttls(self, *a, **k): self.calls.append(("starttls",))
    def login(self, u, p): self.calls.append(("login", u, p))
    def sendmail(self, frm, to, body):
        if self.fail_next_send:
            self.fail_next_send = False
            raise smtplib.SMTPServerDisconnected("stale")
        self.calls.append(("sendmail", frm, to))
    def quit(self): self.calls.append(("quit",))


@pytest.fixture(autouse=True)
def _reset():
    _Smtp.instances = []


def test_starttls_then_login_then_send_in_that_order():
    ch = EmailChannel("smtp.gmail.com", 587, "alerts@example.com", "kbl", username="alerts@example.com", password="app-pass", security="starttls")
    with patch("smtplib.SMTP", _Smtp):
        ch.connect()
        asyncio.run(ch.send(_req()))
    assert [c[0] for c in _Smtp.instances[0].calls] == ["connect", "starttls", "login", "sendmail"]
    assert _Smtp.instances[0].calls[2] == ("login", "alerts@example.com", "app-pass")


def test_ssl_security_uses_the_ssl_class_and_no_starttls():
    seen = []

    class _Ssl(_Smtp):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen.append("ssl")
    ch = EmailChannel("smtp.gmail.com", 465, "a@x", "kbl", username="u", password="p", security="ssl")
    with patch("smtplib.SMTP_SSL", _Ssl):
        ch.connect()
    assert seen == ["ssl"] and ("starttls",) not in _Smtp.instances[0].calls


def test_no_username_means_no_login_and_no_security_means_no_starttls():
    ch = EmailChannel("postal.internal", 25, "a@x", "kbl")
    with patch("smtplib.SMTP", _Smtp):
        ch.connect()
    assert [c[0] for c in _Smtp.instances[0].calls] == ["connect"]


def test_a_stale_connection_is_reopened_once_and_the_message_still_goes():
    ch = EmailChannel("smtp.gmail.com", 587, "a@x", "kbl", username="u", password="p", security="starttls")
    with patch("smtplib.SMTP", _Smtp):
        ch.connect()
        _Smtp.instances[0].fail_next_send = True
        asyncio.run(ch.send(_req()))
    assert len(_Smtp.instances) == 2 and _Smtp.instances[1].calls[-1][0] == "sendmail"


def test_sending_does_not_block_the_event_loop():
    """smtplib is blocking; a slow server must not freeze the worker's loop."""
    ch = EmailChannel("h", 25, "a@x", "kbl")
    gate, started = threading.Event(), threading.Event()
    slow = MagicMock()

    def _slow(*a, **k):
        started.set()
        gate.wait(5)
    slow.sendmail.side_effect = _slow
    ch._smtp, ch._ready = slow, True

    async def run():
        task = asyncio.create_task(ch.send(_req()))
        while not started.is_set():
            await asyncio.sleep(0.01)
        ticked = False
        await asyncio.sleep(0.05)               # the loop is still running other work while the send waits
        ticked = True
        gate.set()
        await task
        return ticked
    assert asyncio.run(run()) is True


def test_health_alert_template_renders_severity_component_and_message():
    ch = EmailChannel("h", 25, "a@x", "kbl")
    subject, body = ch._render("PLATFORM_HEALTH_ALERT", {"bank_id": "kbl", "severity": "P0", "component": "yugabyte",
                                                         "event_type": "COMPONENT_DOWN", "message": "db down"})
    assert "P0" in subject and "yugabyte" in subject and "kbl" in subject
    assert "db down" in body and "COMPONENT_DOWN" in body


def test_recovery_template_exists():
    ch = EmailChannel("h", 25, "a@x", "kbl")
    subject, body = ch._render("PLATFORM_HEALTH_RECOVERED", {"bank_id": "kbl", "component": "redis", "down_for": "4m", "message": "back"})
    assert "redis" in subject and "recover" in subject.lower() and "4m" in body


# ---------------- configuration -----------------

class _Cfg:
    def __init__(self, platform=None, secret="s3cret"):
        self._platform, self._secret = platform or {}, secret

    def get_platform(self, key):
        env = key.upper().replace(".", "_")
        if env not in self._platform:
            from shared.config.config_service import ConfigKeyNotFoundError
            raise ConfigKeyNotFoundError(key)
        return self._platform[env]

    async def get_secret(self, key):
        assert key == "smtp.password"
        return self._secret


def test_settings_come_from_deployment_values_and_the_secret():
    cfg = _Cfg({"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_SECURITY": "starttls",
                "SMTP_USERNAME": "alerts@example.com", "SMTP_FROM_ADDRESS": "ASTRA <alerts@example.com>"})
    s = asyncio.run(read_smtp_settings(cfg))
    assert s == SmtpSettings(host="smtp.gmail.com", port=587, security="starttls", username="alerts@example.com",
                             password="s3cret", from_address="ASTRA <alerts@example.com>")


def test_the_from_address_defaults_to_the_username_and_security_to_starttls():
    s = asyncio.run(read_smtp_settings(_Cfg({"SMTP_HOST": "h", "SMTP_USERNAME": "me@example.com"})))
    assert s.from_address == "me@example.com" and s.security == "starttls" and s.port == 587


def test_no_host_means_email_is_not_configured_not_a_default_provider():
    assert asyncio.run(read_smtp_settings(_Cfg({}))) is None
    assert asyncio.run(build_dispatcher(_Cfg({}), "kbl")) is None


def test_an_unknown_security_value_is_refused_rather_than_sending_in_clear():
    with pytest.raises(ValueError):
        asyncio.run(read_smtp_settings(_Cfg({"SMTP_HOST": "h", "SMTP_SECURITY": "tls-ish"})))


def test_a_missing_password_secret_gives_an_unauthenticated_channel_only_when_no_username_is_set():
    s = asyncio.run(read_smtp_settings(_Cfg({"SMTP_HOST": "postal.internal", "SMTP_PORT": "25", "SMTP_SECURITY": "none"}, secret="")))
    assert s.username is None and s.password is None


def test_a_bad_email_setting_never_stops_the_worker_it_just_disables_email():
    """A typo in SMTP_SECURITY must not crash clearing at start-up: build_dispatcher logs it and returns None."""
    cfg = _Cfg({"SMTP_HOST": "h", "SMTP_SECURITY": "mock-value"})
    assert asyncio.run(build_dispatcher(cfg, "kbl")) is None
