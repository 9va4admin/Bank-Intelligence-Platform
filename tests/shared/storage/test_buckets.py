"""Every MinIO bucket the code uses must exist before first use. Found by the first real API scan
upload: 'NoSuchBucket: cts-images' - nothing in the repo or infra created any of the 9 buckets the
code references. ensure_required_buckets is idempotent (no-op when infra already made them)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.storage.buckets import REQUIRED_BUCKETS, ensure_required_buckets


def test_registry_contains_every_bucket_the_code_references():
    for name in ("cts-images", "cts-cheques", "astra-cts", "astra-cts-reports", "astra-vault-errors",
                 "astra-vault-drops", "astra-vault-archive", "astra-sig-staging", "cts-ocr-corpus"):
        assert name in REQUIRED_BUCKETS, name


@pytest.mark.asyncio
async def test_ensures_every_bucket_and_reports_none_failed():
    store = MagicMock(); store.ensure_bucket = AsyncMock()
    failed = await ensure_required_buckets(store)
    assert failed == []
    assert {c.args[0] for c in store.ensure_bucket.await_args_list} == set(REQUIRED_BUCKETS)


@pytest.mark.asyncio
async def test_one_failing_bucket_does_not_stop_the_rest():
    store = MagicMock()
    async def _ensure(name, **kw):
        if name == "cts-images":
            raise RuntimeError("denied")
    store.ensure_bucket = AsyncMock(side_effect=_ensure)
    failed = await ensure_required_buckets(store)
    assert failed == ["cts-images"]
    assert store.ensure_bucket.await_count == len(REQUIRED_BUCKETS)


@pytest.mark.asyncio
async def test_none_store_returns_all_as_failed_without_raising():
    assert set(await ensure_required_buckets(None)) == set(REQUIRED_BUCKETS)


@pytest.mark.asyncio
async def test_bootstrap_is_bounded_so_a_dead_minio_cannot_hold_startup_hostage():
    """Found live: an unreachable/TLS-mismatched MinIO made each bucket call retry for ~9s, so 9 buckets
    stalled worker startup for over a minute. Buckets are ensured concurrently with a per-bucket timeout."""
    import asyncio, time
    store = MagicMock()

    async def _slow(name, **kw):
        await asyncio.sleep(30)
    store.ensure_bucket = AsyncMock(side_effect=_slow)
    t0 = time.monotonic()
    failed = await ensure_required_buckets(store, per_bucket_timeout=0.3)
    assert time.monotonic() - t0 < 3
    assert set(failed) == set(REQUIRED_BUCKETS)
