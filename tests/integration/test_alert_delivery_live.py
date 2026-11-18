"""Live drill: the mail server dies mid-incident. Real pieces end to end: a real SMTP server speaking verified STARTTLS with login (the dev sink in
secure mode, killed and restarted), the real YugabyteDB outbox, the real Immudb audit trail, the real EmailChannel and NotificationDispatcher.

Expected: the alert sent while the server is up is SENT; the one sent while it is down is queued for retry (not lost, not duplicated) with failure audited;
when the server returns the retry is sent, and the whole sequence is in Immudb, verified. Skipped when Yugabyte or Immudb is not reachable.
"""
import asyncio
import datetime
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def _up(port):
    try:
        socket.create_connection(("localhost", port), timeout=1).close()
        return True
    except OSError:
        return False


needs = pytest.mark.skipif(not (_up(15433) and _up(13322)), reason="dev YugabyteDB / Immudb not reachable")


def _cert(d: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    crt = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
           .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
           .sign(key, hashes.SHA256()))
    (d / "c.pem").write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return d / "c.pem", d / "k.pem"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_sink(port, out, cert):
    proc = subprocess.Popen([sys.executable, "scripts/dev_smtp_sink.py", "--port", str(port), "--out", str(out), "--tls-cert", str(cert[0]), "--tls-key",
                             str(cert[1]), "--auth", "astra:s3cret"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if _up(port):
            return proc
        time.sleep(0.1)
    raise RuntimeError("sink did not start")


class _Cfg:
    def __init__(self, bank):
        self.bank = bank

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        v = {"alerts.email_recipients": "ops@bank.example", "alerting.delivery_backoff_seconds": "[3600]", "alerting.delivery_max_attempts": 4,
             "alerting.delivery_fallbacks": "{}"}
        if key not in v:
            raise ConfigKeyNotFoundError(key)
        return v[key]

    async def get_secret(self, key):
        if key.endswith("pii_enc_key"):
            return "live-test-key-not-a-secret"
        if key.endswith("pii_hash_pepper"):
            return "live-test-pepper-not-a-secret"
        raise KeyError(key)


@needs
def test_the_mail_server_dies_mid_incident_and_nothing_is_lost_or_duplicated(tmp_path):
    from modules.cts.workflows.activities.platform_health_activities import (
        DispatchAlertInput, ProcessOutboxInput, dispatch_platform_alert, process_alert_outbox)
    from shared.alerting.factory import build_alert_auditor, build_delivery_engine
    from shared.alerting.templates import TemplateSettings
    from shared.audit.immudb_client import ImmudbClient
    from shared.notifications.dispatcher import NotificationDispatcher
    from shared.notifications.email_channel import EmailChannel

    cert, port, out = _cert(tmp_path), _free_port(), tmp_path / "mail.jsonl"
    bank = f"it-{uuid.uuid4().hex[:8]}"
    sink = _start_sink(port, out, cert)
    keys = []

    class Writer:                                    # the worker's async Immudb writer, remembering each record's key for read-back verification
        def __init__(self, client):
            self.client = client

        async def write(self, *, collection, event_type, bank_id, payload, instrument_id=None):
            def go():
                self.client.set_collection(collection)
                body = {"event_type": event_type, "bank_id": bank_id, "payload": payload}
                if instrument_id is not None:
                    body["instrument_id"] = instrument_id
                return self.client.write_event(body)
            r = await asyncio.to_thread(go)
            keys.append((event_type, r["key"], r["tx_id"]))
            return str(r["tx_id"])

    async def scenario():
        import asyncpg
        pool = await asyncpg.create_pool(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        imm = ImmudbClient()
        imm.connect("localhost", 13322, bank, username=os.environ.get("IMMUDB_DEV_USER", "immudb"), password=os.environ.get("IMMUDB_DEV_PASSWORD", "immudb"))
        cfg = _Cfg(bank)
        channel = EmailChannel("127.0.0.1", port, "astra@local.test", bank, username="astra", password="s3cret", security="starttls", ca_file=str(cert[0]),
                              template_settings=TemplateSettings(ui_base_url="https://astra.bank.example", timezone="Asia/Kolkata"))
        channel.connect()
        dispatcher = NotificationDispatcher(bank)
        dispatcher.connect(email_channel=channel)
        auditor = await build_alert_auditor(cfg, bank, redis=None, immudb_writer=Writer(imm))
        engine = await build_delivery_engine(cfg, bank, db_pool=pool, dispatcher=dispatcher, auditor=auditor)
        assert engine is not None

        def alert(occasion, msg):
            return DispatchAlertInput(bank_id=bank, event_type="COMPONENT_DOWN", component="redis", message=msg, severity="CRITICAL", priority="P0",
                                      incident_id="inc-live", occasion=occasion)
        nonlocal sink
        try:
            r1 = await dispatch_platform_alert(alert("t1", "redis down"), dispatcher=dispatcher, config_service=cfg, alert_auditor=auditor, delivery_engine=engine)
            assert r1.sent and r1.queued_for_retry == 0

            sink.kill()
            sink.wait()                                                     # the mail server dies
            r2 = await dispatch_platform_alert(alert("t2", "redis still down"), dispatcher=dispatcher, config_service=cfg, alert_auditor=auditor,
                                               delivery_engine=engine)
            assert not r2.sent and r2.queued_for_retry == 1                 # not lost: queued
            await dispatch_platform_alert(alert("t2", "redis still down"), dispatcher=dispatcher, config_service=cfg, alert_auditor=auditor,
                                          delivery_engine=engine)           # a Temporal retry of the same activity: nothing new
            rows = await pool.fetch("SELECT status, attempt FROM platform.alert_deliveries WHERE bank_id=$1 ORDER BY created_at", bank)
            assert [(r["status"], r["attempt"]) for r in rows] == [("SENT", 1), ("FAILED", 1)]

            sink = _start_sink(port, out, cert)                             # the server comes back
            await pool.execute("UPDATE platform.alert_deliveries SET next_attempt_at = NOW() - INTERVAL '1 second' WHERE bank_id=$1 AND status='FAILED'", bank)
            res = await process_alert_outbox(ProcessOutboxInput(bank_id=bank), delivery_engine=engine, config_service=cfg)
            assert res.attempted == 1 and res.sent == 1
            rows = await pool.fetch("SELECT status, attempt FROM platform.alert_deliveries WHERE bank_id=$1 ORDER BY created_at", bank)
            assert [(r["status"], r["attempt"]) for r in rows] == [("SENT", 1), ("SENT", 2)]

            mails = [json.loads(line) for line in out.read_text().splitlines()]
            assert len(mails) == 2 and all(m["tls"] and m["auth_user"] == "astra" for m in mails)       # exactly two mails: no loss, no duplicate
            assert any("still down" in m["data"] for m in mails)
            import email as _email
            for m in mails:
                msg = _email.message_from_string(m["data"])
                bodies = {p.get_content_type(): p.get_payload(decode=True).decode() for p in msg.walk() if p.get_content_type().startswith("text/")}
                assert msg["Subject"].startswith("[ASTRA][P0][") and set(bodies) == {"text/plain", "text/html"}          # the full template
                assert "https://astra.bank.example/ops/incidents/inc-live" in bodies["text/html"]

            kinds = [k for k, *_ in keys]
            assert kinds == ["ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED",
                             "ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_FAILED",
                             "ALERT_DISPATCH_INTENDED", "ALERT_DELIVERY_SUCCEEDED"]
            for _, key, _ in keys:
                assert imm.verify_event(key) is True                        # every record cryptographically verified in Immudb
            blob = json.dumps(keys, default=str)
            assert "ops@bank.example" not in blob
        finally:
            await pool.execute("DELETE FROM platform.alert_deliveries WHERE bank_id=$1", bank)
            await pool.close()
    try:
        asyncio.run(scenario())
    finally:
        sink.kill()
