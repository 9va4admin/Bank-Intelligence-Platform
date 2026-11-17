"""Outbox columns on platform.alert_deliveries: the recipient kept encrypted (never in the clear), the message payload, the priority and a work lease."""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "infra" / "migrations" / "platform" / "versions"
REVISION = "20261117_alert_outbox_cols"
DB_URL = "postgresql+asyncpg://yugabyte:yugabyte@localhost:15433/yugabyte"


def test_migration_exists_chains_from_the_alerting_tables_and_is_reversible():
    files = {f.stem: f.read_text(encoding="utf-8") for f in VERSIONS.glob("*.py")}
    src = next((s for s in files.values() if re.search(rf"""^revision\s*=\s*["']{REVISION}["']""", s, re.M)), None)
    assert src is not None and len(REVISION) <= 32
    assert "20261117_alerting_tables" in src and "def downgrade" in src and "DROP COLUMN" in src.upper()


def _db_up():
    try:
        socket.create_connection(("localhost", 15433), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _db_up(), reason="dev YugabyteDB not reachable")
def test_columns_exist_after_upgrade_and_migration_round_trips():
    import asyncio
    env = {**os.environ, "PLATFORM_DB_URL": DB_URL}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", *a], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=300)
    assert run("upgrade", REVISION).returncode == 0
    assert run("downgrade", "20261117_alerting_tables").returncode == 0
    assert run("upgrade", REVISION).returncode == 0

    async def cols():
        import asyncpg
        c = await asyncpg.connect(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte")
        try:
            rows = await c.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='platform' AND table_name='alert_deliveries'")
            return {r["column_name"]: r["data_type"] for r in rows}
        finally:
            await c.close()
    got = asyncio.run(cols())
    assert got["recipient_enc"] == "bytea" and got["payload"] == "jsonb" and "priority" in got and "claimed_until" in got
