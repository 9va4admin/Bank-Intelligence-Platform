"""Bring the legacy migrations that lived outside versions/ into the applied chain.

infra/migrations/cts/*.py (root, ~35 "orphan" files) were never part of any Alembic chain, so no
environment ever created lots, mismatch_queue, outward_scan_events, instrument_holds,
postdated_holds, rrf_sessions, branches, scanner_configs, eeh_sessions, session_reports,
processing_units, ocr_corpus_events, model_retrain_runs ... and activities that write
them silently no-op'd (or failed) in real runs.

Each legacy migration is executed in dependency order inside its OWN SAVEPOINT:
  * already covered by the applied chain (table/column exists) -> that file's changes are
    rolled back and it is reported as skipped, the rest continue;
  * anything else that fails is reported loudly (RuntimeError at the end) so nothing is
    silently dropped.

Revision ID: 20260921_022
Revises: 20260921_021
Create Date: 2026-09-21
"""
import importlib.util
import logging
import re
from pathlib import Path

from alembic import op

revision = "20260921_022"
down_revision = "20260921_021"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")
_ROOT = Path(__file__).resolve().parents[1]

# Already handled elsewhere in the chain / intentionally not re-applied.
_SKIP = {
    "env.py",
    "20260803_add_account_vault.py",                  # -> 20260921_021
    "20260805_account_vault_add_status_and_name.py",   # -> 20260921_021
    "20260811_account_vault_add_holder_names.py",     # -> 20260921_021
    "20260818_cheque_leaf_lifecycle.py",              # -> 20260921_021
    "20260705_add_sb_connections.py",                 # table dropped as dead schema by 20260916_019
    "20260909_phantom_columns.py",                    # multi-column file: a generic skip hides missing
                                                      # columns -> _phantom_columns() adds each idempotently
    "20260908_agent_decisions_extended_columns.py",   # raw-SQL script (not alembic-shaped, invalid
                                                      # ADD CONSTRAINT IF NOT EXISTS) -> _agent_decisions_extended()
}
_ID = r"""["']([^"']+)["']"""


def _meta(path: Path):
    s = path.read_text(encoding="utf-8")
    r = re.search(rf"^revision\s*(?::[^=]+)?=\s*{_ID}", s, re.M)
    d = re.search(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", s, re.M)
    downs = set(re.findall(_ID, d.group(1))) if d else set()
    return (r.group(1) if r else None), downs


def _ordered_legacy_files():
    files = {p.name: p for p in _ROOT.glob("*.py") if p.name not in _SKIP}
    meta = {n: _meta(p) for n, p in files.items()}
    by_rev = {rev: n for n, (rev, _) in meta.items() if rev}
    ordered, seen = [], set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        for dep in meta[name][1]:
            if dep in by_rev:
                visit(by_rev[dep])
        ordered.append(name)

    for name in sorted(files):                      # deterministic; files without a revision sort last
        visit(name)
    return [(n, files[n]) for n in ordered]


def _agent_decisions_extended() -> None:
    """Intent of the legacy 20260908_agent_decisions_extended_columns.py, made valid + idempotent."""
    for ddl in (
        "processing_duration_ms INTEGER",
        "alteration_detected BOOLEAN NOT NULL DEFAULT FALSE",
        "signature_verdict TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "pps_checked BOOLEAN NOT NULL DEFAULT FALSE",
        "pps_verdict TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "cbs_balance_status TEXT NOT NULL DEFAULT 'UNKNOWN'",
        "degraded_mode BOOLEAN NOT NULL DEFAULT FALSE",
        "ocr_engines_used TEXT[]",
        "indic_ocr_kill_switch_active BOOLEAN NOT NULL DEFAULT FALSE",
        "iet_margin_seconds INTEGER NOT NULL DEFAULT 0",
        "registry_version TEXT",
    ):
        op.execute(f"ALTER TABLE cts.agent_decisions ADD COLUMN IF NOT EXISTS {ddl}")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_decisions_workflow_id') THEN
                ALTER TABLE cts.agent_decisions ADD CONSTRAINT uq_agent_decisions_workflow_id UNIQUE (workflow_id);
            END IF;
        END $$;
    """)


def _phantom_columns() -> None:
    """Intent of legacy 20260909_phantom_columns.py — each column added idempotently."""
    for table, ddl in (
        ("cheque_instruments", "queue_tier TEXT NOT NULL DEFAULT 'standard'"),
        ("cheque_instruments", "review_assigned_at TIMESTAMPTZ"),
        ("cheque_instruments", "ngch_acknowledgement_id TEXT"),
        ("cheque_instruments", "final_decision TEXT"),
        ("cheque_instruments", "decision_recorded_at TIMESTAMPTZ"),
        ("clearing_sessions", "failure_reason TEXT"),
        ("lots", "sealed_by TEXT"),
        ("lots", "updated_at TIMESTAMPTZ"),
        ("mismatch_queue", "scan_id TEXT"),
        ("mismatch_queue", "updated_at TIMESTAMPTZ"),
    ):
        op.execute(f"ALTER TABLE cts.{table} ADD COLUMN IF NOT EXISTS {ddl}")


def upgrade() -> None:
    conn = op.get_bind()
    _agent_decisions_extended()
    failed = []
    for name, path in _ordered_legacy_files():
        spec = importlib.util.spec_from_file_location(f"_legacy_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            with conn.begin_nested():               # SAVEPOINT — isolates this legacy file
                mod.upgrade()
            log.info("legacy migration applied: %s", name)
        except Exception as exc:                    # noqa: BLE001
            msg = str(exc).lower()
            if "already exists" in msg or "duplicate" in msg or "does not exist" in msg and "drop" in msg:
                log.info("legacy migration skipped (already covered): %s", name)
            else:
                failed.append((name, str(exc).splitlines()[0][:200]))
    _phantom_columns()
    if failed:
        raise RuntimeError("legacy migrations failed and were NOT applied: " + "; ".join(f"{n}: {e}" for n, e in failed))


def downgrade() -> None:
    # The legacy tables carry production data once populated; dropping them is a deliberate,
    # manual operation, not something a routine downgrade should do.
    pass
