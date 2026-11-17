"""The user directory (who signed in, with which role) on the real dev YugabyteDB, and the bell lookup that now includes identity-provider users."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.bell import resolve_bell_users
from shared.alerting.directory import record_sign_in

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(pool, bank)
        finally:
            await pool.execute("DELETE FROM platform.user_directory WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.local_auth_accounts WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def test_signing_in_records_the_user_and_a_later_sign_in_updates_role_and_last_seen_only():
    async def go(pool, bank):
        await record_sign_in(pool, bank, "idp-user-1", "ops_reviewer")
        first = await pool.fetchrow("SELECT role, first_seen, last_seen FROM platform.user_directory WHERE bank_id=$1 AND user_id='idp-user-1'", bank)
        await asyncio.sleep(0.05)
        await record_sign_in(pool, bank, "idp-user-1", "ops_manager")
        second = await pool.fetchrow("SELECT role, first_seen, last_seen FROM platform.user_directory WHERE bank_id=$1 AND user_id='idp-user-1'", bank)
        assert (first["role"], second["role"]) == ("ops_reviewer", "ops_manager")
        assert second["first_seen"] == first["first_seen"] and second["last_seen"] > first["last_seen"]
        assert await pool.fetchval("SELECT COUNT(*) FROM platform.user_directory WHERE bank_id=$1", bank) == 1
    _run(go)


def test_a_failure_to_record_never_raises():
    async def go(pool, bank):
        class Broken:
            async def execute(self, *a):
                raise ConnectionError("db down")
        await record_sign_in(Broken(), bank, "u", "ops_manager")      # returns quietly: signing in must never fail because of this
    _run(go)


async def _local(pool, bank, user, role):
    await pool.execute("INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role) "
                       "VALUES ($1,$2,'BANK',$2,$1,'x',$3)", user, bank, role)


def test_the_bell_reaches_identity_provider_users_as_well_as_local_ones_without_duplicates():
    async def go(pool, bank):
        await _local(pool, bank, "local-1", "ops_manager")
        await record_sign_in(pool, bank, "idp-1", "ops_manager")
        await record_sign_in(pool, bank, "idp-2", "bank_it_admin")
        await record_sign_in(pool, bank, "local-1", "ops_manager")                      # also signed in: still one entry
        await record_sign_in(pool, bank, "idp-3", "ops_reviewer")                       # not a configured role
        users = await resolve_bell_users(pool, bank, roles=["ops_manager", "bank_it_admin"], limit=50, seen_within_days=90)
        assert users == ["idp-1", "idp-2", "local-1"]
    _run(go)


def test_people_who_have_not_signed_in_for_a_long_time_drop_off_and_zero_means_no_limit():
    async def go(pool, bank):
        await record_sign_in(pool, bank, "recent", "ops_manager")
        await record_sign_in(pool, bank, "stale", "ops_manager")
        await pool.execute("UPDATE platform.user_directory SET last_seen = NOW() - INTERVAL '200 days' WHERE bank_id=$1 AND user_id='stale'", bank)
        assert await resolve_bell_users(pool, bank, roles=["ops_manager"], limit=50, seen_within_days=90) == ["recent"]
        assert await resolve_bell_users(pool, bank, roles=["ops_manager"], limit=50, seen_within_days=0) == ["recent", "stale"]
    _run(go)


def test_an_account_switched_off_in_the_directory_is_not_on_the_bell():
    async def go(pool, bank):
        await record_sign_in(pool, bank, "gone", "ops_manager")
        await pool.execute("UPDATE platform.user_directory SET is_active=FALSE WHERE bank_id=$1 AND user_id='gone'", bank)
        assert await resolve_bell_users(pool, bank, roles=["ops_manager"], limit=50, seen_within_days=90) == []
    _run(go)
