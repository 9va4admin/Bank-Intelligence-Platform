"""scripts/send_test_alert.py: one command to prove the mail settings work, and say plainly what is wrong when they do not.
Run against the dev sink in secure mode so the real protocol is exercised."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sink(tmp_path, *extra):
    port, out = _free_port(), tmp_path / "mail.jsonl"
    proc = subprocess.Popen([sys.executable, "scripts/dev_smtp_sink.py", "--port", str(port), "--out", str(out), *extra], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc, port, out


def _run(port, tmp_path, **env):
    e = {**os.environ, "BANK_ID": "kbl", "ASTRA_SECRETS_BACKEND": "env", "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_SECURITY": "none",
         "SMTP_FROM_ADDRESS": "astra@local.test", **env}
    return subprocess.run([sys.executable, "scripts/send_test_alert.py", "--to", "ops@local.test"], cwd=ROOT, env=e, capture_output=True, text=True, timeout=120)


def test_a_working_setup_sends_a_test_mail_and_says_so(tmp_path):
    proc, port, out = _sink(tmp_path)
    try:
        r = _run(port, tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "sent" in r.stdout.lower()
        assert "ops@local.test" in json.loads(out.read_text().splitlines()[0])["to"]
    finally:
        proc.kill()


def test_an_unreachable_server_is_reported_with_the_reason_and_a_failing_exit(tmp_path):
    r = _run(_free_port(), tmp_path)
    assert r.returncode != 0 and "could not connect" in (r.stdout + r.stderr).lower()


def test_no_mail_server_configured_says_what_to_set(tmp_path):
    e = {k: v for k, v in os.environ.items() if not k.startswith("SMTP_")}
    e.update(BANK_ID="kbl", ASTRA_SECRETS_BACKEND="env")
    r = subprocess.run([sys.executable, "scripts/send_test_alert.py", "--to", "ops@local.test"], cwd=ROOT, env=e, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "SMTP_HOST" in (r.stdout + r.stderr)
