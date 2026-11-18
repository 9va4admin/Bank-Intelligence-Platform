"""Live: a real event on the real Kafka topic is consumed by the real notification service, delivered through the delivery engine, and the result is in the
one delivery log and the user's bell (real YugabyteDB). Skipped when Kafka or the database is not reachable.

The service runs here exactly as deployed (its lifespan, its consumer, its engine) with test-only encryption key and pepper in the environment.
"""
import asyncio
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


def _up(host, port):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def _kafka_port():
    for p in (19092, 9092, 9093):
        if _up("localhost", p):
            return p
    return None


needs = pytest.mark.skipif(not (_up("localhost", 15433) and _kafka_port()), reason="dev YugabyteDB / Kafka not reachable")


def _dev_env():
    env = dict(os.environ)
    for line in (ROOT / "scripts" / ".env.dev").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export ") and "=" in line:
            k, v = line[7:].split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    env.update(ASTRA_SECRET_BANKS_KBL_PII_ENC_KEY="live-test-key-not-a-secret", ASTRA_SECRET_BANKS_KBL_PII_HASH_PEPPER="live-test-pepper-not-a-secret")
    return env


@needs
def test_an_event_on_the_topic_reaches_the_users_bell_and_the_one_delivery_log():
    async def scenario():
        import asyncpg
        from aiokafka import AIOKafkaProducer
        env = _dev_env()
        bank = env.get("BANK_ID", "kbl")
        notification_id = f"live-{uuid.uuid4().hex[:8]}"
        pool = await asyncpg.create_pool(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        user = f"live-user-{uuid.uuid4().hex[:6]}"
        await pool.execute("INSERT INTO platform.user_directory (bank_id, user_id, role) VALUES ($1,$2,'bank_it_admin')", bank, user)
        port = 18030
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "apps.notification_service.main:app", "--port", str(port), "--log-level", "warning"],
                                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(120):                                              # wait for the service to be consuming
                try:
                    import urllib.request
                    body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2).read())
                    break
                except Exception as exc:  # noqa: BLE001
                    body = getattr(exc, "read", lambda: b"{}")()
                    try:
                        body = json.loads(body)
                    except Exception:  # noqa: BLE001
                        body = {}
                    if body.get("checks", {}).get("consumer_running") and body["checks"].get("engine"):
                        break
                time.sleep(1)
            producer = AIOKafkaProducer(bootstrap_servers=f"localhost:{_kafka_port()}")
            await producer.start()
            try:
                await producer.send_and_wait(_topic(), json.dumps({
                    "notification_id": notification_id, "bank_id": bank, "channel": "bell", "recipient_role": "bank_it_admin", "template_id": "security.violation",
                    "context": {}, "priority": "P1", "module": "PLATFORM", "event_type": "SECURITY_VIOLATION", "message": "Repeated failed sign-ins from one source",
                }).encode())
            finally:
                await producer.stop()
            row = None
            for _ in range(90):
                row = await pool.fetchrow("SELECT title, body, severity FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2", bank, user)
                if row:
                    break
                await asyncio.sleep(1)
            assert row is not None, "the event never reached the bell"
            assert row["severity"] == "P1" and "Repeated failed sign-ins" in row["body"]
            log = await pool.fetch("SELECT channel, status, recipient_ref FROM platform.alert_deliveries WHERE bank_id=$1 AND incident_id=$2", bank, notification_id)
            assert [(r["channel"], r["status"], r["recipient_ref"]) for r in log] == [("bell", "SENT", user)] or any(r["recipient_ref"] == user and r["status"] == "SENT" for r in log)
        finally:
            proc.kill()
            await pool.execute("DELETE FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2", bank, user)
            await pool.execute("DELETE FROM platform.alert_deliveries WHERE bank_id=$1 AND incident_id=$2", bank, notification_id)
            await pool.execute("DELETE FROM platform.user_directory WHERE bank_id=$1 AND user_id=$2", bank, user)
            await pool.close()
    asyncio.run(scenario())


def _topic():
    from shared.event_bus.topics import PLATFORM_NOTIFICATIONS
    return PLATFORM_NOTIFICATIONS
