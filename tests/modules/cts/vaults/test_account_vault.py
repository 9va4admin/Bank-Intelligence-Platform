"""
Tests for modules/cts/vaults/account_vault.py

TDD — two-tier account profile vault (YugabyteDB + Redis).
Stores branch contact details fetched from CBS (branch_manager_email, etc.)
so Hold notifications can be dispatched without CBS call during IET window.

Critical invariant: vault miss MUST route to HUMAN_REVIEW, never AUTO_RETURN.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(bank_id="test-bank", pepper="test-pepper", redis_client=None, db_pool=None):
    from modules.cts.vaults.account_vault import AccountVault
    vault = AccountVault(bank_id=bank_id, pepper=pepper, db_pool=db_pool)
    vault._redis = redis_client or MagicMock()
    vault._ready = True
    return vault


def _expected_key(bank_id, account_number, pepper="test-pepper"):
    digest = hmac.new(
        pepper.encode(),
        f"{bank_id}:{account_number}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"acct:{bank_id}:{digest}"


def _sample_profile_dict():
    return {
        "account_number_last4": "4521",
        "account_type": "SB",
        "branch_code": "SRCB0000034",
        "branch_name": "Andheri West Branch",
        "branch_ifsc": "SRCB0000034",
        "branch_manager_email": "mgr.andheriwest@saraswat.coop",
        "branch_contact_email": "ops.andheriwest@saraswat.coop",
        "branch_contact_phone": "9920012345",
        "last_synced_at": "2026-08-03T06:00:00Z",
    }


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestAccountVaultInit:
    @pytest.mark.asyncio
    async def test_requires_connect_before_lookup(self):
        from modules.cts.vaults.account_vault import AccountVault
        vault = AccountVault(bank_id="b", pepper="p")
        with pytest.raises(RuntimeError, match="connect"):
            await vault.lookup("1234567890", "b")

    def test_connect_sets_ready(self):
        from modules.cts.vaults.account_vault import AccountVault
        vault = AccountVault(bank_id="b", pepper="p")
        vault.connect(redis_client=MagicMock())
        assert vault._ready is True


# ---------------------------------------------------------------------------
# Key format — raw account number must never appear in key
# ---------------------------------------------------------------------------

class TestAccountVaultKeyFormat:
    def test_key_uses_hmac_not_raw_account(self):
        vault = _make_vault()
        account_number = "9876543210"
        key = vault._make_key(account_number)
        assert account_number not in key
        assert key.startswith("acct:test-bank:")

    def test_key_format_matches_expected(self):
        vault = _make_vault()
        account_number = "9876543210"
        assert vault._make_key(account_number) == _expected_key("test-bank", account_number)

    def test_different_accounts_produce_different_keys(self):
        vault = _make_vault()
        assert vault._make_key("1111111111") != vault._make_key("2222222222")

    def test_same_account_different_banks_produce_different_keys(self):
        vault_a = _make_vault(bank_id="bank-a")
        vault_b = _make_vault(bank_id="bank-b")
        assert vault_a._make_key("1234567890") != vault_b._make_key("1234567890")


# ---------------------------------------------------------------------------
# Read path — process cache hit
# ---------------------------------------------------------------------------

class TestAccountVaultProcessCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_redis(self):
        redis = MagicMock()
        vault = _make_vault(redis_client=redis)
        key = vault._make_key("1234567890")
        vault._cache[key] = _sample_profile_dict()

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "FOUND"
        assert result.profile.branch_manager_email == "mgr.andheriwest@saraswat.coop"
        redis.hgetall.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_returns_correct_profile_fields(self):
        vault = _make_vault()
        key = vault._make_key("1234567890")
        vault._cache[key] = _sample_profile_dict()

        result = await vault.lookup("1234567890", "test-bank")

        assert result.profile.account_type == "SB"
        assert result.profile.branch_code == "SRCB0000034"
        assert result.profile.branch_name == "Andheri West Branch"
        assert result.profile.branch_ifsc == "SRCB0000034"
        assert result.profile.branch_contact_email == "ops.andheriwest@saraswat.coop"
        assert result.profile.account_number_last4 == "4521"


# ---------------------------------------------------------------------------
# Read path — Redis hit
# ---------------------------------------------------------------------------

class TestAccountVaultRedisHit:
    @pytest.mark.asyncio
    async def test_redis_hit_returns_found(self):
        redis = MagicMock()
        profile = _sample_profile_dict()
        redis.hgetall.return_value = {
            k.encode(): v.encode() for k, v in profile.items()
        }
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "FOUND"
        assert result.profile.branch_manager_email == "mgr.andheriwest@saraswat.coop"

    @pytest.mark.asyncio
    async def test_redis_hit_populates_process_cache(self):
        redis = MagicMock()
        profile = _sample_profile_dict()
        redis.hgetall.return_value = {
            k.encode(): v.encode() for k, v in profile.items()
        }
        vault = _make_vault(redis_client=redis)
        key = vault._make_key("1234567890")

        await vault.lookup("1234567890", "test-bank")

        assert key in vault._cache

    @pytest.mark.asyncio
    async def test_redis_hit_second_call_uses_cache(self):
        redis = MagicMock()
        profile = _sample_profile_dict()
        redis.hgetall.return_value = {
            k.encode(): v.encode() for k, v in profile.items()
        }
        vault = _make_vault(redis_client=redis)

        await vault.lookup("1234567890", "test-bank")
        await vault.lookup("1234567890", "test-bank")

        redis.hgetall.assert_called_once()


# ---------------------------------------------------------------------------
# Read path — vault miss → HUMAN_REVIEW (the safety invariant)
# ---------------------------------------------------------------------------

class TestAccountVaultMiss:
    @pytest.mark.asyncio
    async def test_redis_miss_no_db_returns_human_review(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_MISS"

    @pytest.mark.asyncio
    async def test_miss_outcome_is_never_auto_return(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_miss_profile_is_none(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.profile is None


# ---------------------------------------------------------------------------
# Read path — Redis error → HUMAN_REVIEW
# ---------------------------------------------------------------------------

class TestAccountVaultRedisError:
    @pytest.mark.asyncio
    async def test_redis_exception_returns_human_review(self):
        redis = MagicMock()
        redis.hgetall.side_effect = ConnectionError("Redis unreachable")
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_ERROR"

    @pytest.mark.asyncio
    async def test_redis_error_outcome_never_auto_return(self):
        redis = MagicMock()
        redis.hgetall.side_effect = RuntimeError("Redis timeout")
        vault = _make_vault(redis_client=redis)

        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome != "AUTO_RETURN"


# ---------------------------------------------------------------------------
# Read path — Redis miss → YugabyteDB hit → backfill Redis
# ---------------------------------------------------------------------------

class TestAccountVaultDbFallback:
    @pytest.mark.asyncio
    async def test_redis_miss_db_hit_returns_found(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}

        profile = _sample_profile_dict()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=profile)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "FOUND"
        assert result.profile.branch_manager_email == "mgr.andheriwest@saraswat.coop"

    @pytest.mark.asyncio
    async def test_redis_miss_db_hit_backfills_redis(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}
        redis.pipeline.return_value = MagicMock(
            hset=MagicMock(), execute=MagicMock()
        )

        profile = _sample_profile_dict()
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=profile)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        await vault.lookup("1234567890", "test-bank")

        redis.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_error_returns_human_review(self):
        redis = MagicMock()
        redis.hgetall.return_value = {}

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(side_effect=Exception("DB unavailable")),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        result = await vault.lookup("1234567890", "test-bank")

        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_ERROR"


# ---------------------------------------------------------------------------
# Write path — store_profile
# ---------------------------------------------------------------------------

class TestAccountVaultStore:
    @pytest.mark.asyncio
    async def test_store_writes_db_then_redis(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe

        mock_conn = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        profile = _sample_profile_dict()

        await vault.store_profile("1234567890", profile)

        mock_conn.execute.assert_called_once()
        redis.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_invalidates_process_cache(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())

        mock_conn = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        key = vault._make_key("1234567890")
        vault._cache[key] = _sample_profile_dict()

        await vault.store_profile("1234567890", _sample_profile_dict())

        assert key not in vault._cache

    @pytest.mark.asyncio
    async def test_store_without_db_pool_still_writes_redis(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe

        vault = _make_vault(redis_client=redis, db_pool=None)
        await vault.store_profile("1234567890", _sample_profile_dict())

        redis.pipeline.assert_called_once()


# ---------------------------------------------------------------------------
# BranchContactProfile model (CBS connector return type)
# ---------------------------------------------------------------------------

class TestBranchContactProfile:
    def test_branch_contact_profile_is_immutable(self):
        from shared.cbs_connector.base import BranchContactProfile
        profile = BranchContactProfile(
            branch_code="SRCB0000034",
            branch_name="Andheri West Branch",
            branch_ifsc="SRCB0000034",
            branch_manager_name="N***",
            branch_manager_email="mgr@saraswat.coop",
            branch_contact_email="ops@saraswat.coop",
            branch_contact_phone="9920012345",
            last_updated_in_cbs="2026-08-03T00:00:00Z",
        )
        with pytest.raises(Exception):
            profile.branch_manager_email = "other@saraswat.coop"

    def test_branch_contact_profile_fields(self):
        from shared.cbs_connector.base import BranchContactProfile
        profile = BranchContactProfile(
            branch_code="SRCB0000034",
            branch_name="Andheri West Branch",
            branch_ifsc="SRCB0000034",
            branch_manager_name="N***",
            branch_manager_email="mgr@saraswat.coop",
            branch_contact_email="ops@saraswat.coop",
            branch_contact_phone="9920012345",
            last_updated_in_cbs="2026-08-03T00:00:00Z",
        )
        assert profile.branch_code == "SRCB0000034"
        assert profile.branch_manager_email == "mgr@saraswat.coop"


# ---------------------------------------------------------------------------
# update_branch_contacts — bulk update all accounts at a branch
# ---------------------------------------------------------------------------

class TestAccountVaultUpdateBranchContacts:
    def _make_contact_profile(self, email="new.mgr@saraswat.coop"):
        from shared.cbs_connector.base import BranchContactProfile
        return BranchContactProfile(
            branch_code="SRCB0000034",
            branch_name="Andheri West Updated",
            branch_ifsc="SRCB0000034",
            branch_manager_name="N***",
            branch_manager_email=email,
            branch_contact_email="ops.new@saraswat.coop",
            branch_contact_phone="9920099999",
            last_updated_in_cbs="2026-08-03T14:30:00Z",
        )

    def _make_pool_with_accounts(self, account_hashes: list[str]):
        """DB pool that returns account_hashes for SELECT and succeeds on UPDATE."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"account_hash": h} for h in account_hashes])
        mock_conn.execute = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        return mock_pool, mock_conn

    @pytest.mark.asyncio
    async def test_update_branch_contacts_returns_count_of_updated_accounts(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())
        mock_pool, _ = self._make_pool_with_accounts(["hash1", "hash2", "hash3"])

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        contact = self._make_contact_profile()

        count = await vault.update_branch_contacts("SRCB0000034", contact)

        assert count == 3

    @pytest.mark.asyncio
    async def test_update_branch_contacts_writes_to_redis_for_each_account(self):
        redis = MagicMock()
        pipe = MagicMock()
        pipe.hset = MagicMock()
        pipe.execute = MagicMock()
        redis.pipeline.return_value = pipe

        mock_pool, _ = self._make_pool_with_accounts(["hash1", "hash2"])

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        contact = self._make_contact_profile()

        await vault.update_branch_contacts("SRCB0000034", contact)

        assert pipe.hset.call_count >= 2

    @pytest.mark.asyncio
    async def test_update_branch_contacts_updates_db(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())
        mock_pool, mock_conn = self._make_pool_with_accounts(["hash1"])

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        contact = self._make_contact_profile(email="new@branch.com")

        await vault.update_branch_contacts("SRCB0000034", contact)

        mock_conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_update_branch_contacts_invalidates_process_cache(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())

        account_hash = "deadbeef1234"
        mock_pool, _ = self._make_pool_with_accounts([account_hash])
        vault = _make_vault(redis_client=redis, db_pool=mock_pool)

        # Pre-populate cache with the stale key
        stale_key = f"acct:test-bank:{account_hash}"
        vault._cache[stale_key] = _sample_profile_dict()

        contact = self._make_contact_profile()
        await vault.update_branch_contacts("SRCB0000034", contact)

        assert stale_key not in vault._cache

    @pytest.mark.asyncio
    async def test_update_branch_contacts_zero_accounts_returns_zero(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())
        mock_pool, _ = self._make_pool_with_accounts([])

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        contact = self._make_contact_profile()

        count = await vault.update_branch_contacts("SRCB0000099", contact)

        assert count == 0

    @pytest.mark.asyncio
    async def test_update_branch_contacts_no_db_pool_returns_zero(self):
        redis = MagicMock()
        vault = _make_vault(redis_client=redis, db_pool=None)
        contact = self._make_contact_profile()

        count = await vault.update_branch_contacts("SRCB0000034", contact)

        assert count == 0

    @pytest.mark.asyncio
    async def test_update_branch_contacts_db_error_raises(self):
        redis = MagicMock()
        redis.pipeline.return_value = MagicMock(hset=MagicMock(), execute=MagicMock())

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("DB unreachable"))
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        vault = _make_vault(redis_client=redis, db_pool=mock_pool)
        contact = self._make_contact_profile()

        with pytest.raises(Exception):
            await vault.update_branch_contacts("SRCB0000034", contact)
