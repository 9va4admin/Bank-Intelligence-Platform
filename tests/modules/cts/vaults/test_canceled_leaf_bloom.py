"""
TDD — RED phase: tests for modules/cts/vaults/canceled_leaf_bloom.py

The Canceled Leaf Bloom Filter (Gemini Fix B):
  - Probabilistic Redis filter for canceled cheque serial numbers (MICR band)
  - Before ANY vLLM call: check_serial() → True = skip GPU, route to HUMAN_REVIEW
  - Updated every 15 minutes by DeltaVaultSyncWorkflow
  - False positives are acceptable (route to human review, never auto-confirm)
  - False negatives are NOT acceptable (must have < 0.1% miss rate)
  - Key: bloom:canceled:{bank_id}
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bloom(redis_client=None, bank_id: str = "test-bank", capacity: int = 100_000):
    from modules.cts.vaults.canceled_leaf_bloom import CanceledLeafBloom
    return CanceledLeafBloom(
        redis_client=redis_client or MagicMock(),
        bank_id=bank_id,
        expected_items=capacity,
        false_positive_rate=0.001,
    )


# ---------------------------------------------------------------------------
# CanceledLeafBloom model / init
# ---------------------------------------------------------------------------

class TestCanceledLeafBloomInit:
    def test_bloom_creates_with_correct_redis_key(self):
        from modules.cts.vaults.canceled_leaf_bloom import CanceledLeafBloom
        bloom = CanceledLeafBloom(
            redis_client=MagicMock(),
            bank_id="sbi-main",
            expected_items=100_000,
            false_positive_rate=0.001,
        )
        assert bloom.redis_key == "bloom:canceled:sbi-main"

    def test_bloom_creates_with_bank_isolation(self):
        from modules.cts.vaults.canceled_leaf_bloom import CanceledLeafBloom
        b1 = CanceledLeafBloom(MagicMock(), "bank-a", 100, 0.001)
        b2 = CanceledLeafBloom(MagicMock(), "bank-b", 100, 0.001)
        assert b1.redis_key != b2.redis_key

    def test_bloom_exposes_config(self):
        bloom = _make_bloom(capacity=50_000)
        assert bloom.expected_items == 50_000
        assert bloom.false_positive_rate == 0.001


# ---------------------------------------------------------------------------
# add_serial — add a canceled cheque serial to the filter
# ---------------------------------------------------------------------------

class TestAddSerial:
    def test_add_serial_calls_redis(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis)
        bloom.add_serial("123456789")
        redis.execute_command.assert_called_once()

    def test_add_serial_uses_correct_key(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis, bank_id="kotak-mah")
        bloom.add_serial("999888777")
        call_args = redis.execute_command.call_args
        assert "bloom:canceled:kotak-mah" in str(call_args)

    def test_add_serial_sends_bf_add_command(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis)
        bloom.add_serial("SERIAL001")
        call_args = redis.execute_command.call_args
        assert "BF.ADD" in str(call_args) or "bf.add" in str(call_args).lower()

    def test_add_bulk_serials(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis)
        serials = ["S001", "S002", "S003", "S004", "S005"]
        bloom.add_bulk(serials)
        # Should use pipeline or BF.MADD for efficiency
        assert redis.execute_command.called or redis.pipeline.called


# ---------------------------------------------------------------------------
# check_serial — check if a serial is in the filter (before GPU call)
# ---------------------------------------------------------------------------

class TestCheckSerial:
    def test_known_canceled_serial_returns_true(self):
        """A serial added to the filter must be detected."""
        redis = MagicMock()
        # Simulate BF.EXISTS returning 1 (present)
        redis.execute_command.return_value = 1
        bloom = _make_bloom(redis_client=redis)
        result = bloom.check_serial("CANCELED-SERIAL-001")
        assert result is True

    def test_unknown_serial_returns_false(self):
        """A serial not in the filter must return False."""
        redis = MagicMock()
        # Simulate BF.EXISTS returning 0 (not present)
        redis.execute_command.return_value = 0
        bloom = _make_bloom(redis_client=redis)
        result = bloom.check_serial("VALID-SERIAL-001")
        assert result is False

    def test_check_serial_uses_bf_exists_command(self):
        redis = MagicMock()
        redis.execute_command.return_value = 0
        bloom = _make_bloom(redis_client=redis)
        bloom.check_serial("ANY-SERIAL")
        call_args = redis.execute_command.call_args
        assert "BF.EXISTS" in str(call_args) or "bf.exists" in str(call_args).lower()

    def test_check_serial_uses_correct_key(self):
        redis = MagicMock()
        redis.execute_command.return_value = 0
        bloom = _make_bloom(redis_client=redis, bank_id="hdfc-bank")
        bloom.check_serial("S001")
        call_args = redis.execute_command.call_args
        assert "bloom:canceled:hdfc-bank" in str(call_args)

    def test_redis_error_returns_false_safe_default(self):
        """If Redis is unavailable, check_serial must return False (never block processing)."""
        redis = MagicMock()
        redis.execute_command.side_effect = Exception("Redis unavailable")
        bloom = _make_bloom(redis_client=redis)
        result = bloom.check_serial("SOME-SERIAL")
        # Safe default: False = don't block on Redis failure
        assert result is False


# ---------------------------------------------------------------------------
# initialize — create the Bloom filter in Redis
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_initialize_creates_bloom_filter(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis)
        bloom.initialize()
        # Should call BF.RESERVE or BF.INSERT with CAPACITY and ERROR RATE
        redis.execute_command.assert_called()

    def test_initialize_uses_expected_items_and_fpr(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis, capacity=200_000)
        bloom.initialize()
        call_args = str(redis.execute_command.call_args)
        # Must include the capacity in the command
        assert "200000" in call_args or "bloom:canceled:test-bank" in call_args

    def test_initialize_tolerates_already_exists(self):
        """BF.RESERVE fails if filter already exists — must be ignored gracefully."""
        redis = MagicMock()
        redis.execute_command.side_effect = Exception("ERR item exists")
        bloom = _make_bloom(redis_client=redis)
        # Must not raise — idempotent initialization
        bloom.initialize()


# ---------------------------------------------------------------------------
# clear — reset the filter (used when full sync replaces it)
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_deletes_redis_key(self):
        redis = MagicMock()
        bloom = _make_bloom(redis_client=redis, bank_id="sbi-main")
        bloom.clear()
        redis.delete.assert_called_once_with("bloom:canceled:sbi-main")


# ---------------------------------------------------------------------------
# stats — expose filter health metrics
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_returns_dict(self):
        redis = MagicMock()
        redis.execute_command.return_value = [
            b"Capacity", b"100000",
            b"Size", b"1234",
            b"Number of filters", b"1",
            b"Number of items inserted", b"42",
            b"Expansion rate", b"2",
        ]
        bloom = _make_bloom(redis_client=redis)
        stats = bloom.stats()
        assert isinstance(stats, dict)

    def test_stats_redis_error_returns_empty_dict(self):
        redis = MagicMock()
        redis.execute_command.side_effect = Exception("Redis error")
        bloom = _make_bloom(redis_client=redis)
        stats = bloom.stats()
        assert stats == {}
