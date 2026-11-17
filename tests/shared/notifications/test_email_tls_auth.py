"""The email channel against a real SMTP server that speaks STARTTLS and requires AUTH (the dev sink in its secure mode), with a real
self-signed certificate: proves the certificate is verified, the login is used, and a wrong password is refused."""
import asyncio
import datetime
import ipaddress
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from shared.notifications.email_channel import EmailChannel

ROOT = Path(__file__).resolve().parents[3]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
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


@pytest.fixture()
def server(cert, tmp_path):
    port, out = _free_port(), tmp_path / "mail.jsonl"
    proc = subprocess.Popen([sys.executable, "scripts/dev_smtp_sink.py", "--port", str(port), "--out", str(out), "--tls-cert", str(cert[0]),
                             "--tls-key", str(cert[1]), "--auth", "astra:s3cret"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield SimpleNamespace(port=port, out=out)
    proc.kill()


def _req():
    return SimpleNamespace(recipient="ops@local.test", template_id="PLATFORM_HEALTH_ALERT", notification_id="n1",
                           context={"bank_id": "kbl", "severity": "CRITICAL", "component": "redis", "event_type": "COMPONENT_DOWN", "message": "redis down"})


def _channel(port, **kw):
    return EmailChannel("127.0.0.1", port, "astra@local.test", "kbl", security="starttls", username=kw.pop("username", "astra"),
                        password=kw.pop("password", "s3cret"), **kw)


def test_mail_is_delivered_over_verified_starttls_with_login(server, cert):
    ch = _channel(server.port, ca_file=str(cert[0]))
    ch.connect()
    asyncio.run(ch.send(_req()))
    rec = json.loads(server.out.read_text().splitlines()[0])
    assert rec["to"] == ["ops@local.test"] and rec["tls"] is True and rec["auth_user"] == "astra" and "redis" in rec["data"]


def test_an_untrusted_certificate_is_refused(server):
    ch = _channel(server.port)                       # no CA file: the self-signed certificate is not trusted
    with pytest.raises(RuntimeError):
        ch.connect()


def test_a_wrong_password_is_refused(server, cert):
    ch = _channel(server.port, ca_file=str(cert[0]), password="wrong")
    with pytest.raises(RuntimeError):
        ch.connect()


def test_the_factory_reads_the_ca_file_setting():
    from shared.notifications.factory import read_smtp_settings

    class Cfg:
        def get_platform(self, key):
            return {"smtp.host": "h", "smtp.ca_file": "/etc/ca.pem"}[key]

        async def get_secret(self, key):
            raise KeyError(key)
    s = asyncio.run(read_smtp_settings(Cfg()))
    assert s.ca_file == "/etc/ca.pem"
