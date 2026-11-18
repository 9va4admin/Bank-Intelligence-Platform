"""Readiness proofs table: migration chain and round trip on the real dev database (always left at head)."""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "infra" / "migrations" / "platform" / "versions"
REVISION = "20261119_readiness_proofs"
DB = "postgresql+asyncpg://yugabyte:yugabyte@localhost:15433/yugabyte"


def test_the_migration_exists_chains_from_the_oncall_tables_and_is_reversible():
    src = next((f.read_text(encoding="utf-8") for f in VERSIONS.glob("*.py")
                if re.search(rf"""^revision\s*=\s*["']{REVISION}["']""", f.read_text(encoding="utf-8"), re.M)), None)
    assert src is not None and len(REVISION) <= 32
    assert "20261118_oncall" in src and "DROP TABLE" in src.upper()


def _up():
    try:
        socket.create_connection(("localhost", 15433), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")
def test_round_trip():
    env = {**os.environ, "PLATFORM_DB_URL": DB}
    run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", *a], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=300)
    assert run("upgrade", REVISION).returncode == 0
    assert run("downgrade", "20261118_oncall").returncode == 0
    assert run("upgrade", "head").returncode == 0
