"""platform.user_directory: who has signed in, with which role, for every user whatever the identity source (local, LDAP, SAML). The bell and other
role-based lookups read it, because the identity provider's users have no row in platform.local_auth_accounts."""
import asyncio
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
REVISION = "20261117_user_directory"
DB = "postgresql+asyncpg://yugabyte:yugabyte@localhost:15433/yugabyte"


def test_migration_exists_chains_from_the_outbox_columns_and_is_reversible():
    src = next((f.read_text(encoding="utf-8") for f in VERSIONS.glob("*.py")
                if re.search(rf"""^revision\s*=\s*["']{REVISION}["']""", f.read_text(encoding="utf-8"), re.M)), None)
    assert src is not None and len(REVISION) <= 32
    assert "20261117_alert_outbox_cols" in src and "DROP TABLE" in src.upper()


def _up():
    try:
        socket.create_connection(("localhost", 15433), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_round_trip_and_one_row_per_bank_and_user():
    env = {**os.environ, "PLATFORM_DB_URL": DB}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", *a], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=300)
    assert run("upgrade", REVISION).returncode == 0
    assert run("downgrade", "20261117_alert_outbox_cols").returncode == 0
    assert run("upgrade", "head").returncode == 0

    async def go():
        import asyncpg
        c = await asyncpg.connect(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte")
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            await c.execute("INSERT INTO platform.user_directory (bank_id, user_id, role) VALUES ($1,'u1','ops_manager')", bank)
            with pytest.raises(asyncpg.UniqueViolationError):
                await c.execute("INSERT INTO platform.user_directory (bank_id, user_id, role) VALUES ($1,'u1','ops_manager')", bank)
        finally:
            await c.execute("DELETE FROM platform.user_directory WHERE bank_id=$1", bank)
            await c.close()
    asyncio.run(go())
