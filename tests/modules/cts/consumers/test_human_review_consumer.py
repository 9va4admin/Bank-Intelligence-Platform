"""
Tests for modules/cts/consumers/human_review_consumer.py

Consumes cts.human.review.{bank_id} events and:
  - Writes CTS_REVIEW_ASSIGNED audit record to Immudb
  - Updates cts.cheque_instruments status to IN_HUMAN_REVIEW in YugabyteDB

Critical invariants:
  - Every routing-to-human-review is an auditable event (RBI requirement)
  - Wrong bank_id → skipped
  - Immudb unavailable → logs warning, no crash
  - DB unavailable → logs warning, no crash
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.event_bus.schemas import KafkaEventEnvelope


def _make_envelope(
    bank_id="saraswat-coop",
    event_type="CTS_HUMAN_REVIEW_REQUIRED",
    instrument_id="INST-002",
    workflow_id="cts-saraswat-coop-INST-002",
    iet_deadline=9999999999.0,
):
    return KafkaEventEnvelope(
        event_id="evt-002",
        event_type=event_type,
        bank_id=bank_id,
        schema_version="1.0",
        payload={
            "instrument_id": instrument_id,
            "workflow_id": workflow_id,
            "context_bundle": {"fraud_score": 0.74, "ocr_confidence": 0.91},
            "iet_deadline": iet_deadline,
        },
    )


class TestHandleHumanReviewEvent:

    @pytest.mark.asyncio
    async def test_writes_immudb_review_assigned(self):
        """CTS_HUMAN_REVIEW_REQUIRED → Immudb write with CTS_REVIEW_ASSIGNED type."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        immudb.write.assert_awaited_once()
        call_kwargs = immudb.write.call_args[1]
        assert call_kwargs["collection"] == "cts_saraswat-coop"   # AsyncImmudbWriter.write contract
        assert call_kwargs["instrument_id"] == "INST-002"
        assert call_kwargs["event_type"] == "CTS_REVIEW_ASSIGNED"
        assert call_kwargs["bank_id"] == "saraswat-coop"
        assert "INST-002" in str(call_kwargs["payload"])

    @pytest.mark.asyncio
    async def test_updates_instrument_status_in_db(self):
        """CTS_HUMAN_REVIEW_REQUIRED → updates cheque_instruments status to IN_HUMAN_REVIEW."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        conn = AsyncMock()
        # real asyncpg shape: pool.acquire() is a sync call returning an async context manager
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock()
        db.acquire = MagicMock(return_value=ctx)
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        conn.execute.assert_awaited_once()
        sql = conn.execute.call_args[0][0]
        assert "IN_HUMAN_REVIEW" in sql or "status" in sql.lower()

    @pytest.mark.asyncio
    async def test_wrong_bank_id_skipped(self):
        """Envelope bank_id != consumer's bank_id → no writes."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(bank_id="wrong-bank")

        await handle_human_review_event(
            envelope, immudb=immudb, db=db, consumer_bank_id="saraswat-coop"
        )

        immudb.write.assert_not_awaited()
        db.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_immudb_unavailable_does_not_crash(self):
        """Immudb=None → logs warning, returns cleanly."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=None, db=db)

    @pytest.mark.asyncio
    async def test_db_unavailable_does_not_crash(self):
        """DB=None → logs warning, returns cleanly."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=None)

    @pytest.mark.asyncio
    async def test_immudb_error_does_not_crash(self):
        """Immudb write failure → logs error, does not crash consumer."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        immudb.write.side_effect = RuntimeError("immudb timeout")
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

    @pytest.mark.asyncio
    async def test_iet_deadline_included_in_audit_payload(self):
        """IET deadline is captured in the Immudb payload — reviewers need to know urgency."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(iet_deadline=1750000000.0)

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        payload = immudb.write.call_args[1]["payload"]
        assert payload.get("iet_deadline") == 1750000000.0


# ---------------------------------------------------------------------------
# Helpers for allocation path tests
# ---------------------------------------------------------------------------

def _make_full_redis():
    """Fake Redis with sorted set support (heartbeat pool + HYBRID pending queue)."""
    redis = AsyncMock()
    redis._store: dict = {}
    redis._zsets: dict = {}

    async def set_nx(key, value, ex=None):
        if key in redis._store:
            return False
        redis._store[key] = value
        return True

    async def delete(key):
        redis._store.pop(key, None)

    async def get(key):
        return redis._store.get(key)

    async def expire(key, seconds):
        pass

    async def zadd(key, mapping):
        if key not in redis._zsets:
            redis._zsets[key] = {}
        redis._zsets[key].update(mapping)

    async def zremrangebyscore(key, min_s, max_s):
        if key not in redis._zsets:
            return
        min_f = float("-inf") if min_s == "-inf" else float(min_s)
        max_f = float("inf") if max_s == "+inf" else float(max_s)
        stale = [m for m, s in redis._zsets[key].items() if min_f <= s <= max_f]
        for m in stale:
            del redis._zsets[key][m]

    async def zrange(key, start, stop):
        if key not in redis._zsets:
            return []
        items = sorted(redis._zsets[key].items(), key=lambda x: x[1])
        members = [m for m, _ in items]
        return members[start:] if stop == -1 else members[start : stop + 1]

    async def zrangebyscore(key, min_s, max_s, start=0, num=None):
        if key not in redis._zsets:
            return []
        min_f = float("-inf") if min_s == "-inf" else float(min_s)
        max_f = float("inf") if max_s == "+inf" else float(max_s)
        items = sorted(redis._zsets[key].items(), key=lambda x: x[1])
        members = [m for m, s in items if min_f <= s <= max_f]
        result = members[start:]
        return result[:num] if num is not None else result

    async def zrem(key, *members):
        if key not in redis._zsets:
            return
        for m in members:
            redis._zsets[key].pop(m, None)

    redis.set = AsyncMock(side_effect=set_nx)
    redis.delete = AsyncMock(side_effect=delete)
    redis.get = AsyncMock(side_effect=get)
    redis.expire = AsyncMock(side_effect=expire)
    redis.zadd = AsyncMock(side_effect=zadd)
    redis.zremrangebyscore = AsyncMock(side_effect=zremrangebyscore)
    redis.zrange = AsyncMock(side_effect=zrange)
    redis.zrangebyscore = AsyncMock(side_effect=zrangebyscore)
    redis.zrem = AsyncMock(side_effect=zrem)
    return redis


def _make_config_svc(allocation_mode="SELF", hybrid_timeout_minutes=5):
    config_svc = AsyncMock()
    config_svc.get_cts_config.return_value = {
        "allocation_mode": allocation_mode,
        "allocation_lock_ttl_minutes": 10,
        "hybrid_auto_assign_timeout_minutes": hybrid_timeout_minutes,
    }
    return config_svc


# ---------------------------------------------------------------------------
# AUTO mode allocation
# ---------------------------------------------------------------------------

class TestAutoModeAllocation:
    @pytest.mark.asyncio
    async def test_auto_mode_calls_auto_assign_with_active_reviewers(self):
        """AUTO mode triggers AllocationService.auto_assign immediately on arrival."""
        import time
        from unittest.mock import patch, MagicMock
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        redis._zsets["active-reviewers:saraswat-coop"] = {
            "ananya.krishnan": time.time() + 300
        }
        config_svc = _make_config_svc(allocation_mode="AUTO")
        envelope = _make_envelope()

        with patch("modules.cts.allocation.allocation_service.AllocationService") as MockAlloc:
            mock_instance = MagicMock()
            mock_instance.auto_assign = AsyncMock(
                return_value=MagicMock(claimed=True, reviewer_id="ananya.krishnan")
            )
            MockAlloc.return_value = mock_instance

            await handle_human_review_event(
                envelope,
                immudb=AsyncMock(),
                db=AsyncMock(),
                redis=redis,
                config_svc=config_svc,
            )

            mock_instance.auto_assign.assert_awaited_once()
            call_args = mock_instance.auto_assign.call_args
            # First positional arg = instrument_id
            assert call_args[0][0] == "INST-002"

    @pytest.mark.asyncio
    async def test_auto_mode_empty_reviewer_pool_does_not_crash(self):
        """AUTO mode with no active reviewers logs warning and does not raise."""
        from unittest.mock import patch, MagicMock
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = _make_config_svc(allocation_mode="AUTO")
        envelope = _make_envelope()

        with patch("modules.cts.allocation.allocation_service.AllocationService") as MockAlloc:
            mock_instance = MagicMock()
            mock_instance.auto_assign = AsyncMock(
                return_value=MagicMock(claimed=False, reviewer_id=None)
            )
            MockAlloc.return_value = mock_instance

            await handle_human_review_event(
                envelope,
                immudb=AsyncMock(),
                db=AsyncMock(),
                redis=redis,
                config_svc=config_svc,
            )
            # Called with empty pool — auto_assign still fires, returns unclaimed
            mock_instance.auto_assign.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_none_skips_allocation_gracefully(self):
        """redis=None → allocation is skipped entirely without error."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        config_svc = _make_config_svc(allocation_mode="AUTO")
        envelope = _make_envelope()

        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=None,
            config_svc=config_svc,
        )

    @pytest.mark.asyncio
    async def test_auto_mode_auto_assign_error_does_not_crash_consumer(self):
        """auto_assign raising must not crash the consumer — it is fire-and-continue."""
        from unittest.mock import patch, MagicMock
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = _make_config_svc(allocation_mode="AUTO")
        envelope = _make_envelope()

        with patch("modules.cts.allocation.allocation_service.AllocationService") as MockAlloc:
            mock_instance = MagicMock()
            mock_instance.auto_assign = AsyncMock(side_effect=RuntimeError("Redis timeout"))
            MockAlloc.return_value = mock_instance

            await handle_human_review_event(
                envelope,
                immudb=AsyncMock(),
                db=AsyncMock(),
                redis=redis,
                config_svc=config_svc,
            )


# ---------------------------------------------------------------------------
# HYBRID mode allocation
# ---------------------------------------------------------------------------

class TestHybridModeAllocation:
    @pytest.mark.asyncio
    async def test_hybrid_mode_adds_to_pending_queue_with_correct_score(self):
        """HYBRID mode writes to hybrid-pending sorted set; score = now + timeout_minutes * 60."""
        import time
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = _make_config_svc(allocation_mode="HYBRID", hybrid_timeout_minutes=5)
        envelope = _make_envelope()

        before = time.time()
        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=redis,
            config_svc=config_svc,
        )
        after = time.time()

        key = "hybrid-pending:saraswat-coop"
        assert key in redis._zsets
        assert "INST-002" in redis._zsets[key]
        score = redis._zsets[key]["INST-002"]
        # Score must be ~5 minutes (300 seconds) in the future
        assert before + 299 <= score <= after + 301

    @pytest.mark.asyncio
    async def test_hybrid_mode_config_fetch_failure_defaults_to_self_mode(self):
        """config_svc.get_cts_config() failure → mode defaults to SELF → no allocation, no crash."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = AsyncMock()
        config_svc.get_cts_config.side_effect = RuntimeError("config service unreachable")
        envelope = _make_envelope()

        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=redis,
            config_svc=config_svc,
        )
        # No pending entry added (fell back to SELF)
        assert "hybrid-pending:saraswat-coop" not in redis._zsets

    @pytest.mark.asyncio
    async def test_hybrid_mode_redis_failure_does_not_crash_consumer(self):
        """Redis failure in add_hybrid_pending must not propagate — consumer loop must survive."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        redis.zadd = AsyncMock(side_effect=RuntimeError("Redis connection lost"))
        config_svc = _make_config_svc(allocation_mode="HYBRID", hybrid_timeout_minutes=5)
        envelope = _make_envelope()

        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=redis,
            config_svc=config_svc,
        )


# ---------------------------------------------------------------------------
# SELF mode allocation
# ---------------------------------------------------------------------------

class TestSelfModeAllocation:
    @pytest.mark.asyncio
    async def test_self_mode_does_not_call_auto_assign(self):
        """SELF mode: allocation is a no-op — reviewers self-claim from the queue."""
        from unittest.mock import patch, MagicMock
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = _make_config_svc(allocation_mode="SELF")
        envelope = _make_envelope()

        with patch("modules.cts.allocation.allocation_service.AllocationService") as MockAlloc:
            mock_instance = MagicMock()
            mock_instance.auto_assign = AsyncMock()
            MockAlloc.return_value = mock_instance

            await handle_human_review_event(
                envelope,
                immudb=AsyncMock(),
                db=AsyncMock(),
                redis=redis,
                config_svc=config_svc,
            )
            mock_instance.auto_assign.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_mode_does_not_add_hybrid_pending(self):
        """SELF mode: no hybrid-pending entry written to Redis."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        config_svc = _make_config_svc(allocation_mode="SELF")
        envelope = _make_envelope()

        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=redis,
            config_svc=config_svc,
        )
        assert "hybrid-pending:saraswat-coop" not in redis._zsets

    @pytest.mark.asyncio
    async def test_config_svc_none_defaults_to_self_mode(self):
        """config_svc=None → no config fetch → allocation_mode defaults to SELF → no crash."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        redis = _make_full_redis()
        envelope = _make_envelope()

        await handle_human_review_event(
            envelope,
            immudb=AsyncMock(),
            db=AsyncMock(),
            redis=redis,
            config_svc=None,
        )
        assert "hybrid-pending:saraswat-coop" not in redis._zsets


class TestConsumerOpensDurableReviewItem:
    """The review queue lived only in Redis/Kafka. The consumer now also records an INWARD item
    (with tier and level 1) in cts.human_review_items so it survives a Redis flush and is queryable."""

    @pytest.mark.asyncio
    async def test_open_item_called_with_inward_direction_and_review_workflow_id(self, monkeypatch):
        from modules.cts.consumers.human_review_consumer import handle_human_review_event
        seen = {}

        async def fake_open(conn, **kw):
            seen.update(kw)
        monkeypatch.setattr("modules.cts.consumers.human_review_consumer.open_item", fake_open)
        conn = AsyncMock()
        ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock(); db.acquire = MagicMock(return_value=ctx)
        await handle_human_review_event(_make_envelope(), immudb=AsyncMock(), db=db)
        assert seen["direction"] == "INWARD"
        assert seen["bank_id"] == "saraswat-coop"
        assert seen["instrument_id"] == "INST-002"
        assert seen["workflow_id"] == "cts-humanreview-saraswat-coop-INST-002"
        assert seen["queue_tier"] in ("standard", "high_value", "very_high")

    @pytest.mark.asyncio
    async def test_open_item_failure_does_not_crash_the_consumer(self, monkeypatch):
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        async def boom(conn, **kw):
            raise RuntimeError("db down")
        monkeypatch.setattr("modules.cts.consumers.human_review_consumer.open_item", boom)
        conn = AsyncMock()
        ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock(); db.acquire = MagicMock(return_value=ctx)
        await handle_human_review_event(_make_envelope(), immudb=AsyncMock(), db=db)   # must not raise
