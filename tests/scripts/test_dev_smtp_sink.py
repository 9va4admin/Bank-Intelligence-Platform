"""scripts/dev_smtp_sink.py: a local mail server for development that stores every message it receives as one JSON line, so an alert email can be
seen arriving without a real provider. Plain SMTP only (no TLS, no auth)."""
import json
import smtplib
import socket
import subprocess
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_stores_each_received_message_as_a_json_line(tmp_path):
    port, out = _free_port(), tmp_path / "mail.jsonl"
    proc = subprocess.Popen([sys.executable, "scripts/dev_smtp_sink.py", "--port", str(port), "--out", str(out)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        msg = MIMEText("redis is not responding")
        msg["Subject"], msg["From"], msg["To"] = "ASTRA P0 - redis (kbl)", "astra@local.test", "ops@local.test"
        with smtplib.SMTP("127.0.0.1", port, timeout=5) as smtp:
            smtp.sendmail("astra@local.test", ["ops@local.test"], msg.as_string())
        for _ in range(50):
            if out.exists() and out.read_text().strip():
                break
            time.sleep(0.1)
        rec = json.loads(out.read_text().splitlines()[0])
        assert rec["from"] == "astra@local.test" and rec["to"] == ["ops@local.test"]
        assert "ASTRA P0 - redis (kbl)" in rec["data"] and "redis is not responding" in rec["data"]
    finally:
        proc.kill()
