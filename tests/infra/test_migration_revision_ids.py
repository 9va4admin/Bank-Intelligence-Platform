"""Alembic stores the current revision in alembic_version.version_num VARCHAR(32).
A longer revision id makes `alembic upgrade head` fail on any fresh database (found by
the real fresh-database migration run: 20260916_platform_local_auth_cols was 33 chars)."""
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("chain", ["platform", "cts", "msv"])
def test_revision_ids_fit_alembic_version_column(chain):
    too_long = []
    for f in Path(f"infra/migrations/{chain}/versions").glob("*.py"):
        m = re.search(r"""^revision\s*(?::[^=]+)?=\s*["']([^"']+)["']""", f.read_text(encoding="utf-8"), re.M)
        if m and len(m.group(1)) > 32:
            too_long.append((f.name, m.group(1), len(m.group(1))))
    assert not too_long, too_long
