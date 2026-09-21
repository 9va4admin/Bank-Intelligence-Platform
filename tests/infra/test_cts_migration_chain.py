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
    assert "20260921_021" in revs, "consolidation migration missing"
    referenced = set()
    for _, (down, _, _) in revs.items():
        referenced |= _down_ids(down)
    assert "20260921_021" not in referenced          # nothing builds on it yet -> it is the head
    src = revs["20260921_021"][2]
    for needle in ("cts.account_vault", "holder_names", "account_status", "cheque_books", "cheque_leaves"):
        assert needle in src, needle
    assert "IF NOT EXISTS" in src                    # safe on DBs where tables were created by hand


def test_consolidation_has_a_downgrade():
    assert "def downgrade" in _revs()["20260921_021"][2]
