"""CTS Alembic chain integrity. The account-vault and cheque-leaf tables lived in
migration files outside versions/, so no environment ever created them and the
vaults silently ran without their tables. A consolidation migration in the chain
must create them, and the chain must have exactly one head."""
import re
from pathlib import Path

VERSIONS = Path("infra/migrations/cts/versions")


def _revs():
    out = {}
    for f in VERSIONS.glob("*.py"):
        s = f.read_text(encoding="utf-8")
        r = re.search(r"""^revision(?::[^=]+)?\s*=\s*["']([^"']+)["']""", s, re.M)
        d = re.search(r'^down_revision(?::[^=]+)?\s*=\s*(.+)$', s, re.M)
        if r:
            out[r.group(1)] = (d.group(1).strip() if d else None, f.name, s)
    return out


def _down_ids(raw):
    return set(re.findall(r"""["']([^"']+)["']""", raw or ""))


def test_exactly_one_head():
    revs = _revs()
    referenced = set()
    for _, (down, _, _) in revs.items():
        referenced |= _down_ids(down)
    heads = [r for r in revs if r not in referenced]
    assert len(heads) == 1, f"multiple heads: {heads}"


def test_consolidation_migration_is_the_head_and_creates_vault_tables():
    revs = _revs()
    assert "20260921_022" in revs, "consolidation migration missing"
    referenced = set()
    for _, (down, _, _) in revs.items():
        referenced |= _down_ids(down)
    assert "20260921_022" not in referenced          # nothing builds on it yet -> it is the head
    assert "20260921_021" in revs and "20260921_021" in revs["20260921_022"][0]   # builds on the vault consolidation
    src = revs["20260921_022"][2]
    assert "begin_nested" in src                     # each legacy migration isolated in a savepoint
    assert "20260902_lots" in src or "orphan" in src.lower()


def test_consolidation_has_a_downgrade():
    assert "def downgrade" in _revs()["20260921_022"][2]


import os
import subprocess
import sys

import pytest

_REQUIRED_TABLES = [
    "lots", "mismatch_queue", "outward_scan_events", "instrument_holds", "postdated_holds", "rrf_sessions",
    "branches", "scanner_configs", "eeh_sessions", "session_reports", "processing_units",
    "account_vault", "cheque_books", "cheque_leaves", "clearing_sessions", "ocr_corpus_events",
    "model_retrain_runs", "scanner_registrations", "outward_scan_session_events",
]


# Columns the code reads/writes that legacy multi-column migrations were silently skipped over
# (found on the dev DB: 9 of 10 columns of 20260909_phantom_columns were missing).
_REQUIRED_COLUMNS = [
    ("cheque_instruments", "review_assigned_at"), ("cheque_instruments", "ngch_acknowledgement_id"),
    ("cheque_instruments", "final_decision"), ("cheque_instruments", "decision_recorded_at"),
    ("clearing_sessions", "failure_reason"), ("lots", "sealed_by"), ("lots", "updated_at"),
    ("mismatch_queue", "scan_id"), ("mismatch_queue", "updated_at"),
    ("agent_decisions", "signature_verdict"), ("agent_decisions", "degraded_mode"),
    ("account_vault", "holder_names"),
]


@pytest.mark.skipif(not os.environ.get("ASTRA_MIGRATION_TEST_ADMIN_DSN"),
                    reason="needs a live Postgres/Yugabyte admin DSN (creates and drops a scratch database)")
def test_fresh_database_gets_every_table_the_pipeline_needs():
    """Integration: an EMPTY database migrated with `alembic upgrade head` must contain every
    table the inward/outward pipelines read or write. The legacy migrations outside versions/
    were never applied, so 12 of these were missing and activities silently no-op'd."""
    import psycopg2
    admin = os.environ["ASTRA_MIGRATION_TEST_ADMIN_DSN"]
    name = "astra_migtest_scratch"
    con = psycopg2.connect(admin); con.autocommit = True
    cur = con.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {name}"); cur.execute(f"CREATE DATABASE {name}")
    base = admin.rsplit("/", 1)[0]
    url = f"{base.replace('postgresql://', 'postgresql+psycopg2://')}/{name}"
    try:
        env = {**os.environ, "CTS_DB_URL": url, "PLATFORM_DB_URL": url}
        # a real deployment migrates the platform schema first, then CTS
        for ini in ("platform", "cts"):
            out = subprocess.run([sys.executable, "-m", "alembic", "-c", f"infra/migrations/{ini}/alembic.ini",
                                  "upgrade", "head"], env=env, capture_output=True, text=True, timeout=600)
            assert out.returncode == 0, f"{ini} chain failed: " + out.stderr[-1500:]
        c2 = psycopg2.connect(f"{base}/{name}"); c2.autocommit = True; k = c2.cursor()
        k.execute("select table_name from information_schema.tables where table_schema='cts'")
        have = {r[0] for r in k.fetchall()}
        missing = [t for t in _REQUIRED_TABLES if t not in have]
        assert not missing, f"tables missing after full migration: {missing}"
        k.execute("select table_name, column_name from information_schema.columns where table_schema='cts'")
        cols = set(k.fetchall())
        missing_cols = [f"{t}.{c}" for t, c in _REQUIRED_COLUMNS if (t, c) not in cols]
        assert not missing_cols, f"columns missing after full migration: {missing_cols}"
        c2.close()
    finally:
        cur.execute(f"DROP DATABASE IF EXISTS {name}"); con.close()
