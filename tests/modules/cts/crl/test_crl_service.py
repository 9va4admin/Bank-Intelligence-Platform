"""
Tests for modules/cts/crl/service.py — CRL (Cheque Routing Layer) Service.

CRL resolves IFSC → Branch → PU with a Redis cache. Cache misses fall back to
YugabyteDB. Cache is invalidated via Kafka cts.crl.invalidated events.

TDD: confirm RED before implementation exists.
"""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── 1. Import guard — confirm RED ─────────────────────────────────────────────

def test_crl_service_module_importable():
    from modules.cts.crl.service import CRLService


def test_branch_resolution_importable():
    from modules.cts.crl.service import BranchResolution


def test_crl_not_found_error_importable():
    from modules.cts.crl.service import BranchNotFoundError


def test_crl_cache_key_format():
    from modules.cts.crl.service import crl_cache_key
    key = crl_cache_key("SBIN0001234")
    assert key == "crl:SBIN0001234"


# ── 2. BranchResolution dataclass ─────────────────────────────────────────────

def test_branch_resolution_has_required_fields():
    from modules.cts.crl.service import BranchResolution
    r = BranchResolution(
        branch_id="branch-01",
        bank_id="saraswat",
        pu_id="PU-MUMBAI-01",
        ifsc_code="SBIN0001234",
        micr_code="400002001",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-saraswat-PU-MUMBAI-01",
        kafka_inward_topic="cts.inward.saraswat.PU-MUMBAI-01",
    )
    assert r.branch_id == "branch-01"
    assert r.pu_id == "PU-MUMBAI-01"
    assert r.temporal_task_queue == "cts-processing-saraswat-PU-MUMBAI-01"


def test_branch_resolution_serialises_to_dict():
    from modules.cts.crl.service import BranchResolution
    r = BranchResolution(
        branch_id="b1", bank_id="sb1", pu_id="pu1",
        ifsc_code="SBIN0001", micr_code="400001001",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-sb1-pu1",
        kafka_inward_topic="cts.inward.sb1.pu1",
    )
    d = r.to_dict()
    assert d["branch_id"] == "b1"
    assert d["pu_id"] == "pu1"
    assert isinstance(d, dict)


def test_branch_resolution_from_dict_roundtrip():
    from modules.cts.crl.service import BranchResolution
    original = BranchResolution(
        branch_id="b1", bank_id="sb1", pu_id="pu1",
        ifsc_code="SBIN0001", micr_code="400001001",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-sb1-pu1",
        kafka_inward_topic="cts.inward.sb1.pu1",
    )
    restored = BranchResolution.from_dict(original.to_dict())
    assert restored.branch_id == original.branch_id
    assert restored.pu_id == original.pu_id
    assert restored.clearing_zone == original.clearing_zone


# ── 3. Cache key helpers ──────────────────────────────────────────────────────

def test_cache_key_uppercase_ifsc():
    from modules.cts.crl.service import crl_cache_key
    # IFSC is always 11 chars, uppercase. Key must be exact — no normalisation error.
    assert crl_cache_key("HDFC0000001") == "crl:HDFC0000001"


def test_cache_key_different_ifsc_different_key():
    from modules.cts.crl.service import crl_cache_key
    assert crl_cache_key("SBIN0001234") != crl_cache_key("HDFC0000001")


# ── 4. Cache hit path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_returns_cached_value_without_db_call():
    from modules.cts.crl.service import CRLService, BranchResolution

    cached_resolution = BranchResolution(
        branch_id="b1", bank_id="sb1", pu_id="pu1",
        ifsc_code="SBIN0001234", micr_code="400001001",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-sb1-pu1",
        kafka_inward_topic="cts.inward.sb1.pu1",
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(cached_resolution.to_dict()))
    mock_db = AsyncMock()  # must NOT be called on cache hit

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    result = await svc.resolve_ifsc("SBIN0001234")

    assert result.branch_id == "b1"
    assert result.pu_id == "pu1"
    mock_db.fetchrow.assert_not_called()
    mock_redis.get.assert_awaited_once_with("crl:SBIN0001234")


@pytest.mark.asyncio
async def test_resolve_cache_hit_does_not_call_redis_set():
    from modules.cts.crl.service import CRLService, BranchResolution

    cached = BranchResolution(
        branch_id="b1", bank_id="sb1", pu_id="pu1",
        ifsc_code="SBIN0001234", micr_code="400001001",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-sb1-pu1",
        kafka_inward_topic="cts.inward.sb1.pu1",
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(cached.to_dict()))

    svc = CRLService(redis=mock_redis, db=AsyncMock(), cache_ttl_seconds=300)
    await svc.resolve_ifsc("SBIN0001234")

    mock_redis.set.assert_not_called()


# ── 5. Cache miss → DB fallback ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_cache_miss_queries_db():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # cache miss

    db_row = {
        "branch_id": "b2", "bank_id": "sb2", "pu_id": "pu2",
        "branch_ifsc": "HDFC0000001", "micr_code": "400151001",
        "clearing_zone": "MUMBAI",
        "temporal_task_queue": "cts-processing-sb2-pu2",
        "kafka_inward_topic": "cts.inward.sb2.pu2",
    }
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=db_row)

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    result = await svc.resolve_ifsc("HDFC0000001")

    assert result.branch_id == "b2"
    assert result.pu_id == "pu2"
    mock_db.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_cache_miss_populates_cache():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    db_row = {
        "branch_id": "b3", "bank_id": "sb3", "pu_id": "pu3",
        "branch_ifsc": "KOTAK0000001", "micr_code": "400485001",
        "clearing_zone": "MUMBAI",
        "temporal_task_queue": "cts-processing-sb3-pu3",
        "kafka_inward_topic": "cts.inward.sb3.pu3",
    }
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=db_row)

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    await svc.resolve_ifsc("KOTAK0000001")

    # Redis SET must have been called with the correct key and TTL
    mock_redis.set.assert_awaited_once()
    call_args = mock_redis.set.await_args
    assert call_args[0][0] == "crl:KOTAK0000001"
    assert call_args[1]["ex"] == 300


@pytest.mark.asyncio
async def test_resolve_cache_miss_db_miss_raises_not_found():
    from modules.cts.crl.service import CRLService, BranchNotFoundError

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)  # not in DB

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)

    with pytest.raises(BranchNotFoundError, match="UNKNOWN0001"):
        await svc.resolve_ifsc("UNKNOWN0001")


# ── 6. Cache invalidation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalidate_cache_deletes_redis_key():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    svc = CRLService(redis=mock_redis, db=AsyncMock(), cache_ttl_seconds=300)

    await svc.invalidate("SBIN0001234")

    mock_redis.delete.assert_awaited_once_with("crl:SBIN0001234")


@pytest.mark.asyncio
async def test_invalidate_multiple_ifsc_deletes_all_keys():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    svc = CRLService(redis=mock_redis, db=AsyncMock(), cache_ttl_seconds=300)

    await svc.invalidate_many(["SBIN0001234", "HDFC0000001", "KOTAK0000001"])

    mock_redis.delete.assert_awaited_once_with(
        "crl:SBIN0001234", "crl:HDFC0000001", "crl:KOTAK0000001"
    )


# ── 7. Kafka event handler ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_kafka_invalidation_event_calls_invalidate():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    svc = CRLService(redis=mock_redis, db=AsyncMock(), cache_ttl_seconds=300)

    event_payload = json.dumps({"ifsc_codes": ["SBIN0001234", "SBIN0005678"]})
    await svc.handle_invalidation_event(event_payload)

    # Both keys must be deleted
    mock_redis.delete.assert_awaited_once_with("crl:SBIN0001234", "crl:SBIN0005678")


@pytest.mark.asyncio
async def test_handle_kafka_invalidation_single_ifsc():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    svc = CRLService(redis=mock_redis, db=AsyncMock(), cache_ttl_seconds=300)

    event_payload = json.dumps({"ifsc_codes": ["HDFC0000001"]})
    await svc.handle_invalidation_event(event_payload)

    mock_redis.delete.assert_awaited_once_with("crl:HDFC0000001")


@pytest.mark.asyncio
async def test_handle_kafka_invalidation_malformed_event_does_not_raise():
    from modules.cts.crl.service import CRLService

    svc = CRLService(redis=AsyncMock(), db=AsyncMock(), cache_ttl_seconds=300)
    # Malformed payload must not crash the worker — log and skip
    await svc.handle_invalidation_event("not-valid-json{{{")  # must not raise


# ── 8. DB query correctness ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_query_includes_ifsc_in_where_clause():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    try:
        await svc.resolve_ifsc("SBIN0001234")
    except Exception:
        pass

    # The DB must have been called with the IFSC as a parameter
    mock_db.fetchrow.assert_awaited_once()
    query_args = mock_db.fetchrow.await_args[0]
    assert "SBIN0001234" in query_args


@pytest.mark.asyncio
async def test_db_query_joins_branches_and_processing_units():
    from modules.cts.crl.service import CRLService

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_db = AsyncMock()
    mock_db.fetchrow = AsyncMock(return_value=None)

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    try:
        await svc.resolve_ifsc("SBIN0001234")
    except Exception:
        pass

    # Query must reference both tables (branches and processing_units)
    sql = mock_db.fetchrow.await_args[0][0]
    assert "branches" in sql.lower()
    assert "processing_units" in sql.lower()


# ── 9. resolve_micr convenience method ───────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_micr_falls_back_to_ifsc_resolution():
    from modules.cts.crl.service import CRLService, BranchResolution

    cached = BranchResolution(
        branch_id="b4", bank_id="sb4", pu_id="pu4",
        ifsc_code="AXIS0001234", micr_code="400151002",
        clearing_zone="MUMBAI",
        temporal_task_queue="cts-processing-sb4-pu4",
        kafka_inward_topic="cts.inward.sb4.pu4",
    )

    mock_redis = AsyncMock()
    # IFSC lookup cached; MICR lookup is a secondary index
    mock_redis.get = AsyncMock(side_effect=[
        None,                                   # MICR key miss
        json.dumps(cached.to_dict()),           # IFSC key hit (after MICR lookup)
    ])
    mock_db = AsyncMock()
    # MICR lookup returns the IFSC
    mock_db.fetchval = AsyncMock(return_value="AXIS0001234")
    mock_db.fetchrow = AsyncMock(return_value=None)  # should not be called

    svc = CRLService(redis=mock_redis, db=mock_db, cache_ttl_seconds=300)
    result = await svc.resolve_micr("400151002")

    assert result.branch_id == "b4"
