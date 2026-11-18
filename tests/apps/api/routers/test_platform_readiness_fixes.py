"""The older Go-Live checks answer from the tables and the Redis client the platform really has, on the real dev YugabyteDB. Skipped when it is not reachable."""
import asyncio
import socket
import uuid

import pytest

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class AsyncRedis:
    def __init__(self, keys):
        self.keys = keys

    def scan_iter(self, match=None, count=None):
        prefix = (match or "").rstrip("*")

        async def gen():
            for k in self.keys:
                if k.startswith(prefix):
                    yield k
        return gen()

    async def ping(self):
        return True


def _db(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
        bank = f"fx-{uuid.uuid4().hex[:8]}"
        await pool.execute("INSERT INTO platform.banks (bank_id, bank_name, bank_code, ifsc_prefix) VALUES ($1,'Fixture Bank',$1,'FIXT')", bank)
        await pool.execute("INSERT INTO cts.sub_member_banks (sub_member_id, bank_id, bank_name, sponsor_bank_id, micr_prefix, ifsc_prefix, branch_manager_email_enc, ops_head_email_enc, gm_email_enc) "
                           "VALUES ($1,$2,'Fixture SMB',$2,'999','FIXS',$3,$3,$3)", f"smb-{bank}", bank, b"x")
        try:
            return await fn(pool, bank)
        finally:
            await pool.execute("DELETE FROM cts.micr_prefix_routing WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM cts.signature_embeddings WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.local_auth_accounts WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM cts.sub_member_banks WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.banks WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def test_micr_prefixes_fail_when_none_and_pass_with_the_count_when_present():
    from apps.api.routers.platform import _check_micr_prefixes

    async def fn(pool, bank):
        assert (await _check_micr_prefixes(bank, pool)).status == "FAIL"
        for p in ("400", "401"):
            await pool.execute("INSERT INTO cts.micr_prefix_routing (bank_id, micr_prefix, sub_member_id, created_by) VALUES ($1,$2,$3,'t')", bank, p, f"smb-{bank}")
        item = await _check_micr_prefixes(bank, pool)
        assert item.status == "PASS" and "2" in item.detail
    _db(fn)


def test_reviewers_are_counted_from_the_real_accounts_table():
    from apps.api.routers.platform import _check_ops_users

    async def fn(pool, bank):
        assert (await _check_ops_users(bank, pool)).status == "FAIL"
        for role in ("ops_reviewer", "ops_manager"):
            await pool.execute("INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role) VALUES ($1,$2,'SB',$2,$1,'x',$3)",
                               f"{bank}-{role}", bank, role)
        item = await _check_ops_users(bank, pool)
        assert item.status == "PASS" and "1" in item.detail
    _db(fn)


def test_pps_and_signature_vault_checks_work_with_the_async_redis_client():
    from apps.api.routers.platform import _check_pps_vault, _check_signature_vault

    async def fn(pool, bank):
        redis = AsyncRedis([f"pps:{bank}:a", f"pps:{bank}:b"])
        item = await _check_pps_vault(bank, redis)
        assert item.status == "PASS" and "2" in item.detail
        assert (await _check_pps_vault(bank, AsyncRedis([]))).status == "WARN"
        assert (await _check_signature_vault(bank, pool, AsyncRedis([]))).status == "FAIL"          # nothing in the database yet
        await pool.execute("INSERT INTO cts.signature_embeddings (bank_id, account_hash, specimen_index, embedding, source) VALUES ($1,'h1',0,$2,'CBS')", bank, b"x")
        sig = await _check_signature_vault(bank, pool, AsyncRedis([f"sig:{bank}:h1"]))
        assert sig.status == "PASS" and "1/1" in sig.detail
    _db(fn)


def test_the_smoke_tests_for_the_vaults_work_with_the_async_redis_client():
    from types import SimpleNamespace
    from apps.api.routers.platform import _run_test_pps_vault, _run_test_signature_vault, _run_test_vault_seeded

    async def fn(pool, bank):
        state = SimpleNamespace(redis_cts=AsyncRedis([f"sig:{bank}:h1", f"pps:{bank}:p1"]))
        assert (await _run_test_signature_vault(state, bank)).status == "PASS"
        assert (await _run_test_pps_vault(state, bank)).status == "PASS"
        assert (await _run_test_vault_seeded(state, bank)).status == "PASS"
    _db(fn)
