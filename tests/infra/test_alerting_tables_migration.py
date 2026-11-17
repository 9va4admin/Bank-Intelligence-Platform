"""Alerting tables (platform schema): incidents, component state history, deliveries (the outbox and the delivery log in one), and the per-user
notification inbox the bell reads.

Static checks always run. The database checks run against the real dev YugabyteDB when it is reachable (migrate up, exercise the constraints,
migrate down and up again) and are skipped otherwise.
"""
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "infra" / "migrations" / "platform" / "versions"
REVISION = "20261117_alerting_tables"

DB_HOST, DB_PORT = "localhost", 15433
DB_URL = f"postgresql+asyncpg://yugabyte:yugabyte@{DB_HOST}:{DB_PORT}/yugabyte"


def _revisions():
    out = {}
    for f in VERSIONS.glob("*.py"):
        s = f.read_text(encoding="utf-8")
        r = re.search(r"""^revision\s*(?::[^=]+)?=\s*["']([^"']+)["']""", s, re.M)
        d = re.search(r"""^down_revision\s*(?::[^=]+)?=\s*(.+)$""", s, re.M)
        if r:
            out[r.group(1)] = (d.group(1).strip() if d else "", f.name, s)
    return out


def test_the_migration_exists_chains_from_the_current_head_and_leaves_one_head():
    revs = _revisions()
    assert REVISION in revs, "alerting migration missing"
    assert len(REVISION) <= 32
    assert "20261029_drop_clearing_zones" in revs[REVISION][0]
    referenced = set()
    for down, _, _ in revs.values():
        referenced |= set(re.findall(r"""["']([^"']+)["']""", down))
    heads = [r for r in revs if r not in referenced]
    assert len(heads) == 1, heads                      # one head; later alerting migrations build on this one


def test_the_migration_is_reversible():
    src = _revisions()[REVISION][2]
    assert "def downgrade" in src and "DROP TABLE" in src.upper()


def _db_up():
    try:
        socket.create_connection((DB_HOST, DB_PORT), timeout=1).close()
        return True
    except OSError:
        return False


needs_db = pytest.mark.skipif(not _db_up(), reason="dev YugabyteDB not reachable")


def _alembic(*args):
    env = {**os.environ, "PLATFORM_DB_URL": DB_URL}
    return subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


async def _conn():
    import asyncpg
    return await asyncpg.connect(host=DB_HOST, port=DB_PORT, user="yugabyte", password="yugabyte", database="yugabyte")


@needs_db
def test_migrates_up_down_and_up_again_against_the_real_database():
    up = _alembic("upgrade", REVISION)
    assert up.returncode == 0, up.stdout + up.stderr
    down = _alembic("downgrade", "20261029_drop_clearing_zones")
    assert down.returncode == 0, down.stdout + down.stderr
    again = _alembic("upgrade", REVISION)
    assert again.returncode == 0, again.stdout + again.stderr


@needs_db
@pytest.mark.asyncio
async def test_constraints_enforce_the_incident_lifecycle_and_idempotent_delivery():
    import asyncpg
    assert _alembic("upgrade", REVISION).returncode == 0
    c = await _conn()
    bank = f"it-{uuid.uuid4().hex[:8]}"
    try:
        ins = ("INSERT INTO platform.alert_incidents (incident_id, bank_id, dedup_key, alert_id, component, severity, state, scope_level, summary) "
               "VALUES ($1,$2,$3,'COMPONENT_DOWN','redis',$4,$5,'BANK','s')")
        await c.execute(ins, "i1", bank, "k1", "P0", "OPEN")
        # one open incident per dedup key
        with pytest.raises(asyncpg.UniqueViolationError):
            await c.execute(ins, "i2", bank, "k1", "P0", "OPEN")
        # a resolved incident frees the key
        await c.execute("UPDATE platform.alert_incidents SET state='RESOLVED', resolved_at=NOW() WHERE incident_id='i1'")
        await c.execute(ins, "i3", bank, "k1", "P0", "OPEN")
        # fixed vocabularies
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(ins, "i4", bank, "k2", "P9", "OPEN")
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(ins, "i5", bank, "k3", "P0", "BROKEN")

        dl = ("INSERT INTO platform.alert_deliveries (delivery_id, bank_id, incident_id, idempotency_key, channel, recipient_ref, status) "
              "VALUES ($1,$2,'i3',$3,$4,'n***@gmail.com',$5)")
        await c.execute(dl, "d1", bank, "i3:1:u1:email", "email", "PENDING")
        with pytest.raises(asyncpg.UniqueViolationError):           # the same notification can never be queued twice
            await c.execute(dl, "d2", bank, "i3:1:u1:email", "email", "PENDING")
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(dl, "d3", bank, "i3:1:u1:fax", "fax", "PENDING")
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute(dl, "d4", bank, "i3:1:u1:sms", "sms", "MAYBE")

        await c.execute("INSERT INTO platform.user_notifications (notification_id, bank_id, user_id, severity, title, body) VALUES ('n1',$1,'u1','P0','t','b')", bank)
        row = await c.fetchrow("SELECT read_at, acked_at FROM platform.user_notifications WHERE notification_id='n1'")
        assert row["read_at"] is None and row["acked_at"] is None
        await c.execute("INSERT INTO platform.component_state_history (bank_id, component, from_status, to_status) VALUES ($1,'redis','OK','DOWN')", bank)
    finally:
        for t in ("alert_deliveries", "alert_incidents", "user_notifications", "component_state_history"):
            await c.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
        await c.close()
