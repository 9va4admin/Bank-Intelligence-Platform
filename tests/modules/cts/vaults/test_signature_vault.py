"""
Tests for modules/cts/vaults/signature_vault.py

Per-signatory two-tier vault (Redis + YugabyteDB).

Critical invariants (never negotiable):
  - Vault miss / error → HUMAN_REVIEW, NEVER AUTO_RETURN
  - Raw account number never appears in any key
  - Redis key format: sig:{bank_id}:{hmac}:{signatory_id}
  - Multiple specimens per signatory (specimen_index 0..N)
  - Multiple signatories per account — get_specimens_by_signatory groups them
  - Mandate rule: ANY_ONE / ALL_REQUIRED / QUORUM_N — from get_mandate_rule()
"""
import hashlib
import hmac
import struct
from unittest.mock import AsyncMock, MagicMock, call

import pytest

_DIM = 512
_PACK_FMT = f"{_DIM}f"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embedding(seed: int = 1) -> list[float]:
    return [float((i + seed) % 7 + 0.1) for i in range(_DIM)]


def _pack(emb: list[float]) -> bytes:
    return struct.pack(_PACK_FMT, *emb)


def _make_vault(bank_id="test-bank", redis_client=None, pepper="test-pepper", db_pool=None):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=bank_id, pepper=pepper, db_pool=db_pool)
    vault._redis = redis_client or MagicMock()
    vault._ready = True
    return vault


def _account_hash(bank_id, account_number, pepper="test-pepper"):
    return hmac.new(pepper.encode(), f"{bank_id}:{account_number}".encode(), hashlib.sha256).hexdigest()


def _expected_key(bank_id, account_number, signatory_id="PRIMARY", pepper="test-pepper"):
    h = _account_hash(bank_id, account_number, pepper)
    return f"sig:{bank_id}:{h}:{signatory_id}"


def _redis_miss():
    r = MagicMock()
    r.lrange = MagicMock(return_value=[])
    r.pipeline = MagicMock(return_value=MagicMock(delete=MagicMock(), rpush=MagicMock(), execute=MagicMock()))
    return r


def _redis_hit(embeddings: list[list[float]], signatory_id="PRIMARY"):
    r = MagicMock()
    r.lrange = MagicMock(return_value=[_pack(e) for e in embeddings])
    r.pipeline = MagicMock(return_value=MagicMock(delete=MagicMock(), rpush=MagicMock(), execute=MagicMock()))
    return r


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestSignatureVaultInit:
    @pytest.mark.asyncio
    async def test_requires_connect_before_get(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="b", pepper="p")
        with pytest.raises(RuntimeError, match="connect"):
            await vault.get_signatures("1234567890", "b")

    def test_connect_sets_ready(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="b", pepper="p")
        vault.connect(redis_client=MagicMock())
        assert vault._ready is True

    def test_connect_stores_redis_client(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        mock_redis = MagicMock()
        vault = SignatureVault(bank_id="b", pepper="p")
        vault.connect(redis_client=mock_redis)
        assert vault._redis is mock_redis


# ---------------------------------------------------------------------------
# Key format — per-signatory, never raw account number
# ---------------------------------------------------------------------------

class TestVaultKeyFormat:
    def test_key_uses_hmac_hash_not_raw_account(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="pepper123")
        key = vault._make_key("9876543210")
        assert "9876543210" not in key

    def test_key_starts_with_sig_prefix(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("9876543210").startswith("sig:kotak:")

    def test_key_is_deterministic(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC123") == vault._make_key("ACC123")

    def test_key_differs_for_different_accounts(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC111") != vault._make_key("ACC222")

    def test_key_differs_for_different_bank_ids(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        v1 = SignatureVault(bank_id="bank-a", pepper="p")
        v2 = SignatureVault(bank_id="bank-b", pepper="p")
        assert v1._make_key("ACC123") != v2._make_key("ACC123")

    def test_key_differs_for_different_signatory_ids(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC123", "PRIMARY") != vault._make_key("ACC123", "JOINT_1")

    def test_key_includes_signatory_id(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert "PRIMARY" in vault._make_key("ACC123", "PRIMARY")
        assert "JOINT_1" in vault._make_key("ACC123", "JOINT_1")

    def test_key_format_matches_expected(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="test-pepper")
        assert vault._make_key("ACC123", "PRIMARY") == _expected_key("kotak", "ACC123", "PRIMARY", "test-pepper")

    def test_default_signatory_is_primary(self):
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="kotak", pepper="p")
        assert vault._make_key("ACC123") == vault._make_key("ACC123", "PRIMARY")


# ---------------------------------------------------------------------------
# get_specimens_by_signatory — primary new read path
# ---------------------------------------------------------------------------

class TestGetSpecimensBySignatory:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_redis_miss_no_db(self):
        vault = _make_vault(redis_client=_redis_miss())
        result = await vault.get_specimens_by_signatory("ACC001", "test-bank")
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_embeddings_grouped_by_signatory(self):
        emb1, emb2 = _fake_embedding(1), _fake_embedding(2)
        redis = MagicMock()
        # PRIMARY returns emb1; JOINT_1 returns emb2
        def lrange_side(key, start, end):
            if "PRIMARY" in key:
                return [_pack(emb1)]
            if "JOINT_1" in key:
                return [_pack(emb2)]
            return []
        redis.lrange = MagicMock(side_effect=lrange_side)
        vault = _make_vault(redis_client=redis)
        # Inject signatory list via cache bypass: set up DB pool mock
        db_pool = _db_with_signatories(["PRIMARY", "JOINT_1"])
        vault._db_pool = db_pool
        result = await vault.get_specimens_by_signatory("ACC001", "test-bank")
        assert "PRIMARY" in result
        assert "JOINT_1" in result
        assert len(result["PRIMARY"]) == 1
        assert len(result["JOINT_1"]) == 1

    @pytest.mark.asyncio
    async def test_redis_hit_populates_cache(self):
        emb = _fake_embedding()
        redis = _redis_hit([emb])
        vault = _make_vault(redis_client=redis)
        await vault.get_specimens_by_signatory("ACC002", "test-bank")
        key = vault._make_key("ACC002", "PRIMARY")
        assert key in vault._cache

    @pytest.mark.asyncio
    async def test_redis_error_for_signatory_is_skipped(self):
        """Redis error on one signatory → that signatory absent from result, no raise."""
        redis = MagicMock()
        redis.lrange = MagicMock(side_effect=Exception("Redis timeout"))
        vault = _make_vault(redis_client=redis)
        result = await vault.get_specimens_by_signatory("ACC003", "test-bank")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_multiple_specimens_per_signatory(self):
        """A signatory can have 3 specimens — all returned."""
        emb1, emb2, emb3 = _fake_embedding(1), _fake_embedding(2), _fake_embedding(3)
        redis = _redis_hit([emb1, emb2, emb3])
        vault = _make_vault(redis_client=redis)
        result = await vault.get_specimens_by_signatory("ACC004", "test-bank")
        assert len(result["PRIMARY"]) == 3

    @pytest.mark.asyncio
    async def test_cache_hit_skips_redis(self):
        emb = _fake_embedding()
        redis = MagicMock()
        vault = _make_vault(redis_client=redis)
        key = vault._make_key("ACC005", "PRIMARY")
        vault._cache[key] = [emb]
        result = await vault.get_specimens_by_signatory("ACC005", "test-bank")
        redis.lrange.assert_not_called()
        assert result["PRIMARY"] == [emb]


# ---------------------------------------------------------------------------
# get_mandate_rule
# ---------------------------------------------------------------------------

class TestGetMandateRule:
    @pytest.mark.asyncio
    async def test_defaults_to_any_one_with_no_db(self):
        vault = _make_vault()
        rule = await vault.get_mandate_rule("ACC001", "test-bank")
        assert rule == "ANY_ONE"

    @pytest.mark.asyncio
    async def test_returns_all_required_from_db(self):
        db_pool = _db_with_mandate("ALL_REQUIRED", quorum_n=2)
        vault = _make_vault(db_pool=db_pool)
        rule = await vault.get_mandate_rule("ACC001", "test-bank")
        assert rule == "ALL_REQUIRED"

    @pytest.mark.asyncio
    async def test_returns_any_one_from_db(self):
        db_pool = _db_with_mandate("ANY_ONE", quorum_n=1)
        vault = _make_vault(db_pool=db_pool)
        rule = await vault.get_mandate_rule("ACC001", "test-bank")
        assert rule == "ANY_ONE"

    @pytest.mark.asyncio
    async def test_quorum_rule_includes_n(self):
        db_pool = _db_with_mandate("QUORUM_N_OF_M", quorum_n=2)
        vault = _make_vault(db_pool=db_pool)
        rule = await vault.get_mandate_rule("ACC001", "test-bank")
        assert "2" in rule

    @pytest.mark.asyncio
    async def test_db_error_falls_back_to_any_one(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=Exception("DB down"))
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        vault = _make_vault(db_pool=pool)
        rule = await vault.get_mandate_rule("ACC001", "test-bank")
        assert rule == "ANY_ONE"

    @pytest.mark.asyncio
    async def test_mandate_cached_after_first_db_call(self):
        db_pool = _db_with_mandate("ALL_REQUIRED", quorum_n=2)
        vault = _make_vault(db_pool=db_pool)
        await vault.get_mandate_rule("ACC001", "test-bank")
        await vault.get_mandate_rule("ACC001", "test-bank")
        conn = db_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_signatures — backward compat (flat aggregation of all signatories)
# ---------------------------------------------------------------------------

class TestGetSignaturesBackwardCompat:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_embeddings(self):
        vault = _make_vault()
        key = vault._make_key("ACC001", "PRIMARY")
        embs = [_fake_embedding(1), _fake_embedding(2)]
        vault._cache[key] = embs
        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.embeddings == embs

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_redis(self):
        mock_redis = MagicMock()
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC001", "PRIMARY")
        vault._cache[key] = [_fake_embedding()]
        await vault.get_signatures("ACC001", "test-bank")
        mock_redis.lrange.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_outcome_is_found(self):
        vault = _make_vault()
        key = vault._make_key("ACC001", "PRIMARY")
        vault._cache[key] = [_fake_embedding()]
        result = await vault.get_signatures("ACC001", "test-bank")
        assert result.outcome == "FOUND"

    @pytest.mark.asyncio
    async def test_redis_hit_returns_found(self):
        emb = _fake_embedding()
        mock_redis = _redis_hit([emb])
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC002", "test-bank")
        assert result.outcome == "FOUND"
        assert len(result.embeddings) == 1

    @pytest.mark.asyncio
    async def test_redis_hit_uses_correct_key(self):
        emb = _fake_embedding()
        mock_redis = _redis_hit([emb])
        vault = _make_vault(redis_client=mock_redis)
        await vault.get_signatures("ACC002", "test-bank")
        expected_key = vault._make_key("ACC002", "PRIMARY")
        mock_redis.lrange.assert_any_call(expected_key, 0, -1)

    @pytest.mark.asyncio
    async def test_vault_miss_outcome_is_human_review(self):
        vault = _make_vault(redis_client=_redis_miss())
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_embeddings_is_empty(self):
        vault = _make_vault(redis_client=_redis_miss())
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.embeddings == []

    @pytest.mark.asyncio
    async def test_vault_miss_reason_is_set(self):
        vault = _make_vault(redis_client=_redis_miss())
        result = await vault.get_signatures("ACC_UNKNOWN", "test-bank")
        assert result.miss_reason in ("VAULT_MISS", "VAULT_ERROR")

    @pytest.mark.asyncio
    async def test_vault_miss_never_auto_return(self):
        vault = _make_vault(redis_client=_redis_miss())
        result = await vault.get_signatures("ACC_MISSING", "test-bank")
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_redis_error_outcome_is_human_review(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("Redis connection refused"))
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_redis_error_reason_is_vault_error(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("Redis timeout"))
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.miss_reason == "VAULT_ERROR"

    @pytest.mark.asyncio
    async def test_redis_error_never_auto_return(self):
        mock_redis = MagicMock()
        mock_redis.lrange = MagicMock(side_effect=Exception("timeout"))
        vault = _make_vault(redis_client=mock_redis)
        result = await vault.get_signatures("ACC003", "test-bank")
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_multi_signatory_aggregated_as_flat_list(self):
        """Two signatories each with 2 specimens → 4 embeddings total."""
        emb1, emb2, emb3, emb4 = [_fake_embedding(i) for i in range(1, 5)]
        redis = MagicMock()
        def lrange_side(key, start, end):
            if "PRIMARY" in key:
                return [_pack(emb1), _pack(emb2)]
            if "JOINT_1" in key:
                return [_pack(emb3), _pack(emb4)]
            return []
        redis.lrange = MagicMock(side_effect=lrange_side)
        db_pool = _db_with_signatories(["PRIMARY", "JOINT_1"])
        vault = _make_vault(redis_client=redis, db_pool=db_pool)
        result = await vault.get_signatures("ACC010", "test-bank")
        assert result.outcome == "FOUND"
        assert len(result.embeddings) == 4


# ---------------------------------------------------------------------------
# store_embeddings — write path (now takes signatory_id)
# ---------------------------------------------------------------------------

class TestStoreEmbeddings:
    @pytest.mark.asyncio
    async def test_store_uses_correct_redis_key(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        await vault.store_embeddings("ACC004", [_fake_embedding()], signatory_id="PRIMARY")
        expected_key = vault._make_key("ACC004", "PRIMARY")
        pipe_mock.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_store_joint_signatory_uses_joint_key(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        await vault.store_embeddings("ACC004", [_fake_embedding()], signatory_id="JOINT_1")
        expected_key = vault._make_key("ACC004", "JOINT_1")
        pipe_mock.delete.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_store_pushes_all_specimens(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        embs = [_fake_embedding(1), _fake_embedding(2), _fake_embedding(3)]
        await vault.store_embeddings("ACC004", embs)
        assert pipe_mock.rpush.call_count == 3

    @pytest.mark.asyncio
    async def test_store_never_uses_raw_account_as_key(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        await vault.store_embeddings("ACC004", [_fake_embedding()])
        for c in pipe_mock.delete.call_args_list + pipe_mock.rpush.call_args_list:
            for arg in c[0]:
                if isinstance(arg, str):
                    assert "ACC004" not in arg

    @pytest.mark.asyncio
    async def test_store_invalidates_local_cache(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        vault = _make_vault(redis_client=mock_redis)
        key = vault._make_key("ACC004", "PRIMARY")
        vault._cache[key] = [_fake_embedding()]
        await vault.store_embeddings("ACC004", [_fake_embedding(9)], signatory_id="PRIMARY")
        assert key not in vault._cache

    @pytest.mark.asyncio
    async def test_store_upserts_to_db_when_pool_provided(self):
        pipe_mock = MagicMock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe_mock)
        conn = AsyncMock()
        conn.execute = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        vault = _make_vault(redis_client=mock_redis, db_pool=pool)
        await vault.store_embeddings("ACC005", [_fake_embedding()], signatory_id="PRIMARY")
        conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Connect fallback
# ---------------------------------------------------------------------------

class TestSignatureVaultConnectFallback:
    def test_connect_without_redis_client_imports_redis(self, monkeypatch):
        import sys
        fake_redis_mod = MagicMock()
        fake_redis_instance = MagicMock()
        fake_redis_mod.Redis.return_value = fake_redis_instance
        monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id="test-bank", pepper="pepper")
        vault.connect()
        assert vault._ready is True
        assert vault._redis is fake_redis_instance


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

def _db_with_signatories(signatory_ids: list[str]):
    """DB pool mock that returns the given signatory_ids from account_signatories."""
    sig_rows = [{"signatory_id": s} for s in signatory_ids]
    emb_rows = []  # no embeddings in DB — Redis is used

    conn = AsyncMock()
    call_count = {"n": 0}

    async def mock_fetch(query, *args):
        call_count["n"] += 1
        if "account_signatories" in query:
            return sig_rows
        # signature_embeddings query
        return emb_rows

    conn.fetch = AsyncMock(side_effect=mock_fetch)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


def _db_with_mandate(mandate_rule: str, quorum_n: int = 1):
    """DB pool mock that returns a mandate row from account_signatories."""
    row = {"mandate_rule": mandate_rule, "quorum_n": quorum_n}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    conn.fetch = AsyncMock(return_value=[])  # no signatory rows
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool
