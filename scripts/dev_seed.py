"""Seed the dev YugabyteDB after the Alembic chains have run (idempotent).

Run: python scripts/dev_seed.py [--bank-id kbl]
Creates the bank row (every cts/platform table has a foreign key to it), one processing unit, one branch and the three
dev operator accounts that scripts/dev-init.py documents. Safe to re-run.
"""
import argparse
import asyncio

import asyncpg
from argon2 import PasswordHasher

DSN = "postgresql://yugabyte:yugabyte@localhost:15433/yugabyte"


async def seed(bank_id: str) -> None:
    ph = PasswordHasher()
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(
            """INSERT INTO platform.banks (bank_id, bank_name, bank_code, ifsc_prefix, bank_type)
               VALUES ($1, $2, $3, $4, 'SB') ON CONFLICT (bank_id) DO NOTHING""",
            bank_id, f"{bank_id.upper()} (dev)", bank_id.upper(), bank_id.upper()[:4].ljust(4, "X"))
        await conn.execute(
            """INSERT INTO cts.processing_units (pu_id, bank_id, pu_name, temporal_task_queue, kafka_inward_topic)
               VALUES ('PU1', $1, 'Processing Unit 1', $2, $3) ON CONFLICT (pu_id) DO NOTHING""",
            bank_id, f"cts-processing-{bank_id}", f"cts.inward.{bank_id}")
        await conn.execute(
            """INSERT INTO cts.branches (branch_id, bank_id, branch_name, branch_ifsc, pu_id)
               VALUES ('B1', $1, 'Dev Branch 1', $2, 'PU1') ON CONFLICT (branch_id) DO NOTHING""",
            bank_id, bank_id.upper()[:4].ljust(4, "X") + "0000001")
        for username, display, role, perm in (
            ("admin", "Bank IT Admin", "bank_it_admin", "ADMIN"),
            ("ops", "Ops Manager", "ops_manager", "EDIT"),
            ("reviewer", "Ops Reviewer", "ops_reviewer", "EDIT"),
        ):
            await conn.execute(
                """INSERT INTO platform.local_auth_accounts
                   (user_id, bank_id, entity_type, entity_id, username, display_name, password_hash, role,
                    permission_level, bank_type, pu_ids, email, is_active)
                   VALUES ($1,$2,'sb',$2,$3,$4,$5,$6,$7,'SB',$8,$9,true) ON CONFLICT (user_id) DO NOTHING""",
                f"usr-{username}-{bank_id}", bank_id, username, display, ph.hash("Astra@1212"), role, perm,
                ["PU1"] if role == "ops_reviewer" else [], f"{username}@{bank_id}.internal")
        print({t: await conn.fetchval(f"select count(*) from {t} where bank_id=$1", bank_id)
               for t in ("platform.banks", "cts.processing_units", "cts.branches", "platform.local_auth_accounts")})
    finally:
        await conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bank-id", default="kbl")
    asyncio.run(seed(p.parse_args().bank_id))
