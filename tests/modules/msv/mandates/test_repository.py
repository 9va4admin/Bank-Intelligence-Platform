"""load_account_mandate_meta — builds a real AccountMandateMeta from msv.mandate_rules +
SignatoryRegistry (the missing loader confirmed nowhere else in this codebase before today).

Vault-miss philosophy (matches CLAUDE.md's "vault_miss_action: HUMAN_REVIEW, never AUTO_RETURN"): a
missing mandate row is NOT fabricated into a permissive default — it raises MandateNotFoundError so the
caller routes to human review, exactly like a signature/PPS vault miss elsewhere in this codebase.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.msv.mandates.models import MandateRuleType, SignatoryRecord


def _mandate_row(**over):
    row = {
        "operation_type": "J", "rule_type": "ALL_OF", "mandatory_ids": ["SIG-1", "SIG-2"],
        "required_count": 1, "required_roles": [], "min_score": Decimal("0.82"),
    }
    row.update(over)
    return row


def _conn_returning(row):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
async def test_builds_account_mandate_meta_from_real_rows(monkeypatch):
    from modules.msv.mandates.repository import load_account_mandate_meta

    db_pool = _conn_returning(_mandate_row())
    registry = MagicMock()
    registry._hash_account = AsyncMock(return_value="hash123")
    registry.load_all_signatories = AsyncMock(return_value=[
        SignatoryRecord(signatory_id="SIG-1", role="DIRECTOR", name_masked="A***", specimen_count=3,
                        embeddings=[]),
    ])

    meta = await load_account_mandate_meta(bank_id="kbl", account_number="7001000024",
                                            db_pool=db_pool, registry=registry)

    assert meta.bank_id == "kbl" and meta.account_hash == "hash123" and meta.operation_type == "J"
    assert meta.mandate.rule_type == MandateRuleType.ALL_OF
    assert meta.mandate.mandatory_ids == ["SIG-1", "SIG-2"]
    assert meta.mandate.min_score == pytest.approx(0.82)
    assert len(meta.signatories) == 1 and meta.signatories[0].signatory_id == "SIG-1"


@pytest.mark.asyncio
async def test_missing_mandate_row_raises_not_fabricates_a_default():
    from modules.msv.mandates.repository import MandateNotFoundError, load_account_mandate_meta

    db_pool = _conn_returning(None)
    registry = MagicMock()
    registry._hash_account = AsyncMock(return_value="hash123")
    registry.load_all_signatories = AsyncMock(return_value=[])

    with pytest.raises(MandateNotFoundError):
        await load_account_mandate_meta(bank_id="kbl", account_number="7001000024",
                                        db_pool=db_pool, registry=registry)


@pytest.mark.asyncio
async def test_query_scoped_to_bank_and_account_hash_never_raw_account_number():
    from modules.msv.mandates.repository import load_account_mandate_meta

    db_pool = _conn_returning(_mandate_row())
    registry = MagicMock()
    registry._hash_account = AsyncMock(return_value="hash123")
    registry.load_all_signatories = AsyncMock(return_value=[])

    await load_account_mandate_meta(bank_id="kbl", account_number="7001000024",
                                    db_pool=db_pool, registry=registry)

    conn = await db_pool.acquire().__aenter__()
    sql, args = conn.fetchrow.call_args.args[0], conn.fetchrow.call_args.args[1:]
    assert "mandate_rules" in sql and "kbl" in args and "hash123" in args
    assert "7001000024" not in args and "7001000024" not in sql
