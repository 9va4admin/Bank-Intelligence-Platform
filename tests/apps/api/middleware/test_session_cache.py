"""Tests for JWT session cache helpers."""
import pytest
import hashlib
from unittest.mock import AsyncMock, MagicMock


from apps.api.middleware.session_cache import (
    _session_key,
    _extract_token,
    get_cached_session,
    cache_session,
    invalidate_session,
)


class TestSessionKey:
    def test_key_includes_bank_id(self):
        key = _session_key("hdfc", "sometoken")
        assert "hdfc" in key

    def test_key_includes_token_hash_not_raw_token(self):
        token = "raw-secret-token"
        key = _session_key("hdfc", token)
        assert token not in key
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        assert token_hash in key

    def test_different_banks_different_keys(self):
        k1 = _session_key("hdfc", "tok")
        k2 = _session_key("kotak", "tok")
        assert k1 != k2

    def test_same_inputs_same_key(self):
        assert _session_key("hdfc", "tok") == _session_key("hdfc", "tok")


class TestExtractToken:
    def test_extracts_bearer_token(self):
        request = MagicMock()
        request.headers = {"Authorization": "Bearer my-jwt-token"}
        assert _extract_token(request) == "my-jwt-token"

    def test_returns_none_when_no_auth_header(self):
        request = MagicMock()
        request.headers = {}
        assert _extract_token(request) is None

    def test_returns_none_for_non_bearer(self):
        request = MagicMock()
        request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        assert _extract_token(request) is None


class TestGetCachedSession:
    @pytest.mark.asyncio
    async def test_returns_claims_on_cache_hit(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value='{"bank_id": "hdfc", "sub": "user1"}')
        redis.expire = AsyncMock()
        result = await get_cached_session(redis, "test-token-hdfc")
        assert result["bank_id"] == "hdfc"

    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        result = await get_cached_session(redis, "test-token-hdfc")
        assert result is None

    @pytest.mark.asyncio
    async def test_refreshes_sliding_ttl_on_hit(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value='{"bank_id": "hdfc"}')
        redis.expire = AsyncMock()
        await get_cached_session(redis, "test-token-hdfc")
        redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_is_none(self):
        result = await get_cached_session(None, "test-token-hdfc")
        assert result is None


class TestCacheSession:
    @pytest.mark.asyncio
    async def test_stores_claims_as_json(self):
        redis = AsyncMock()
        redis.setex = AsyncMock()
        claims = {"bank_id": "hdfc", "sub": "user1"}
        await cache_session(redis, "test-token-hdfc", claims)
        redis.setex.assert_called_once()
        args = redis.setex.call_args
        assert "hdfc" in args[0][2] or "hdfc" in str(args)

    @pytest.mark.asyncio
    async def test_skips_when_redis_is_none(self):
        # Should not raise
        await cache_session(None, "test-token-hdfc", {"bank_id": "hdfc"})


class TestInvalidateSession:
    @pytest.mark.asyncio
    async def test_deletes_session_key(self):
        redis = AsyncMock()
        redis.delete = AsyncMock()
        await invalidate_session(redis, "test-token-hdfc")
        redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_redis_is_none(self):
        await invalidate_session(None, "test-token-hdfc")
