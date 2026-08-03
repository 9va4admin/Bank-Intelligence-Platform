"""
Real MinIO integration tests for shared/storage/minio_client.py
(MinioObjectStore) — against astra-it-minio (infra/docker-compose.integration.yml),
not a mock.
"""
import uuid

import pytest

from shared.storage.minio_client import MinioObjectStore
from tests.integration.conftest import MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY

pytestmark = pytest.mark.integration


@pytest.fixture
def store(require_minio) -> MinioObjectStore:
    return MinioObjectStore(MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, secure=False)


@pytest.fixture
def bucket_name() -> str:
    # MinIO/S3 bucket names: lowercase, no underscores.
    return f"it-cts-images-{uuid.uuid4().hex[:8]}"


class TestBucketAndObjectLifecycle:
    @pytest.mark.asyncio
    async def test_ensure_bucket_is_idempotent(self, store, bucket_name):
        await store.ensure_bucket(bucket_name)
        await store.ensure_bucket(bucket_name)  # must not raise on second call

    @pytest.mark.asyncio
    async def test_upload_then_download_round_trips_exact_bytes(self, store, bucket_name):
        await store.ensure_bucket(bucket_name)
        original = b"\x89PNG\r\n\x1a\n-fake-cheque-image-bytes-for-integration-test-" + bytes(range(256))

        returned_key = await store.upload_bytes(
            bucket_name, "cheques/2026/07/instr-it-001/front_bw.tiff", original,
            content_type="image/tiff",
        )
        assert returned_key == "cheques/2026/07/instr-it-001/front_bw.tiff"

        downloaded = await store.download_bytes(bucket_name, returned_key)
        assert downloaded == original

    @pytest.mark.asyncio
    async def test_presigned_url_is_a_working_http_url(self, store, bucket_name):
        await store.ensure_bucket(bucket_name)
        await store.upload_bytes(bucket_name, "cheques/it-002/front_grey.jpg", b"jpeg-bytes-here")

        url = await store.presigned_url(bucket_name, "cheques/it-002/front_grey.jpg", expiry_seconds=300)
        assert url.startswith("http://") or url.startswith("https://")

        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
        assert resp.status_code == 200
        assert resp.content == b"jpeg-bytes-here"

    @pytest.mark.asyncio
    async def test_object_lock_bucket_creation_succeeds(self, store):
        """Tier 3 WORM buckets (CLAUDE.md storage tier table) use object_lock=True."""
        worm_bucket = f"it-worm-{uuid.uuid4().hex[:8]}"
        await store.ensure_bucket(worm_bucket, object_lock=True)

    @pytest.mark.asyncio
    async def test_download_nonexistent_object_raises(self, store, bucket_name):
        await store.ensure_bucket(bucket_name)
        with pytest.raises(Exception):
            await store.download_bytes(bucket_name, "no/such/object")
