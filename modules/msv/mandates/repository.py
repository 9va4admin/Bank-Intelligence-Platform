"""load_account_mandate_meta — builds AccountMandateMeta from msv.mandate_rules + SignatoryRegistry.

Nothing in this codebase constructed AccountMandateMeta from real data before today — confirmed by a
full-repo search finding only its own model definition. MandateRule's docstring says mandate rules
"originate from CBS and are stored in msv.mandate_rules"; that table did not exist until migration
20260922_mandate_rules.

Vault-miss philosophy (CLAUDE.md: vault_miss_action is always HUMAN_REVIEW, never AUTO_RETURN, and is
Layer-1 non-overridable): a missing mandate row does not get a fabricated permissive default — it raises
MandateNotFoundError so the caller routes to human review, exactly like a signature/PPS vault miss.
"""
from __future__ import annotations

from typing import Any

from modules.msv.mandates.models import AccountMandateMeta, MandateRule, MandateRuleType


class MandateNotFoundError(LookupError):
    """No msv.mandate_rules row for this (bank_id, account) — route to human review, never a default rule."""


async def load_account_mandate_meta(
    bank_id: str,
    account_number: str,
    db_pool: Any,
    registry: Any,
) -> AccountMandateMeta:
    """
    Args:
        bank_id:        tenant scope
        account_number: raw — hashed via registry._hash_account before any query or return value
        db_pool:        asyncpg pool for the msv schema
        registry:       SignatoryRegistry — used both to hash the account number (so the hashing key
                        derivation lives in exactly one place) and to load enrolled signatories
    """
    account_hash = await registry._hash_account(account_number, bank_id)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT operation_type, rule_type, mandatory_ids, required_count, required_roles, min_score
              FROM msv.mandate_rules
             WHERE bank_id = $1 AND account_hash = $2
            """,
            bank_id, account_hash,
        )

    if row is None:
        raise MandateNotFoundError(f"no mandate_rules row for bank_id={bank_id!r} account_hash={account_hash!r}")

    mandate = MandateRule(
        rule_type=MandateRuleType(row["rule_type"]),
        mandatory_ids=list(row["mandatory_ids"] or []),
        required_count=row["required_count"],
        required_roles=list(row["required_roles"] or []),
        min_score=float(row["min_score"]),
    )

    signatories = await registry.load_all_signatories(bank_id, account_hash)

    return AccountMandateMeta(
        account_hash=account_hash,
        bank_id=bank_id,
        operation_type=row["operation_type"],
        mandate=mandate,
        signatories=signatories,
    )
