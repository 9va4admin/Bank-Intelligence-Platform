"""P0 platform alerts also go to WhatsApp when the bank has configured it. The channel is exercised against a real local HTTP server standing
in for Meta's API (the real service needs the bank's approved templates and token)."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput, dispatch_platform_alert
from shared.notifications.whatsapp_channel import WhatsAppChannel


class _Meta(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Meta.received.append({"path": self.path, "auth": self.headers.get("Authorization"), "json": json.loads(body)})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"messages":[{"id":"wamid.1"}]}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def meta():
    _Meta.received = []
    srv = HTTPServer(("127.0.0.1", 0), _Meta)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v19.0", _Meta
    srv.shutdown()


def _req(template="PLATFORM_HEALTH_ALERT"):
    return SimpleNamespace(recipient="+91 98765 43210", template_id=template, notification_id="n1",
                           context={"bank_id": "kbl", "event_type": "COMPONENT_DOWN", "severity": "CRITICAL", "component": "redis",
                                    "message": "redis is down", "down_for": ""})


def test_a_platform_alert_is_sent_to_the_phone_with_the_template_parameters_in_a_fixed_order(meta):
    url, server = meta
    ch = WhatsAppChannel(url, "PHONE1", "kbl")
    ch.connect("tok123")
    asyncio.run(ch.send(_req()))
    sent = server.received[0]
    assert sent["path"] == "/v19.0/PHONE1/messages" and sent["auth"] == "Bearer tok123"
    tpl = sent["json"]["template"]
    assert sent["json"]["to"] == "919876543210" and tpl["name"] == "astra_platform_health_alert"
    assert [p["text"] for p in tpl["components"][0]["parameters"]] == ["CRITICAL", "redis", "redis is down"]


def test_a_recovery_uses_its_own_template(meta):
    url, server = meta
    ch = WhatsAppChannel(url, "P", "kbl")
    ch.connect("t")
    asyncio.run(ch.send(_req("PLATFORM_HEALTH_RECOVERED")))
    assert server.received[0]["json"]["template"]["name"] == "astra_platform_health_recovered"


# ---------------- routing: who gets WhatsApp -----------------

class _Disp:
    def __init__(self, fail_email=False):
        self.sent, self.fail_email = [], fail_email

    async def send(self, request):
        if request.channel == "email" and self.fail_email:
            raise RuntimeError("smtp down")
        self.sent.append((request.channel, request.recipient))


class _Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _alert(priority):
    return DispatchAlertInput(bank_id="kbl", event_type="COMPONENT_DOWN", component="redis", message="m", severity="CRITICAL", priority=priority)


def _run(disp, cfg, priority):
    return asyncio.run(dispatch_platform_alert(_alert(priority), dispatcher=disp, config_service=cfg))


def test_p0_goes_to_email_and_whatsapp():
    d = _Disp()
    _run(d, _Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001, +919800000002"}), "P0")
    assert ("email", "ops@x.in") in d.sent and ("whatsapp", "+919800000001") in d.sent and ("whatsapp", "+919800000002") in d.sent


def test_lower_priorities_stay_on_email_by_default_and_the_floor_is_configurable():
    d = _Disp()
    cfg = _Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001"})
    _run(d, cfg, "P1")
    assert [c for c, _ in d.sent] == ["email"]
    d2 = _Disp()
    _run(d2, _Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001", "alerts.whatsapp_min_priority": "P1"}), "P1")
    assert "whatsapp" in [c for c, _ in d2.sent]


def test_whatsapp_still_goes_when_email_is_down_and_vice_versa():
    d = _Disp(fail_email=True)
    r = _run(d, _Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001"}), "P0")
    assert ("whatsapp", "+919800000001") in d.sent and r.sent is True


def test_whatsapp_only_setup_works_without_email_recipients():
    d = _Disp()
    r = _run(d, _Cfg(**{"alerts.whatsapp_recipients": "+919800000001"}), "P0")
    assert d.sent == [("whatsapp", "+919800000001")] and r.sent


def test_factory_builds_the_channel_from_settings():
    from shared.notifications.factory import read_whatsapp_settings

    class Cfg:
        def get_platform(self, key):
            return {"whatsapp.api_url": "https://graph.facebook.com/v19.0", "whatsapp.phone_number_id": "123"}[key]

        async def get_secret(self, key):
            assert key == "whatsapp.access_token"
            return "tok"
    s = asyncio.run(read_whatsapp_settings(Cfg()))
    assert (s.api_url, s.phone_number_id, s.access_token) == ("https://graph.facebook.com/v19.0", "123", "tok")

    class Empty:
        def get_platform(self, key):
            raise KeyError(key)
    assert asyncio.run(read_whatsapp_settings(Empty())) is None
