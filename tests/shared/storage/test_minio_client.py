"""
Tests for shared/storage/minio_client.py — MinioObjectStore.

The real minio.Minio client is entirely synchronous; MinioObjectStore wraps
every blocking call in asyncio.to_thread(), matching the established pattern
from modules/cts/dem/sftp_client.py's paramiko wrapper (Phase 4, same session).
"""
import io
import pytest
from unittest.mock import MagicMock, patch


def _make_store(mock_minio_client):
    from shared.storage.minio_client import MinioObjectStore
    store = MinioObjectStore.__new__(MinioObjectStore)
    store._client = mock_minio_client
    return store


class TestMinioObjectStoreConstruction:
    def test_constructs_real_minio_client(self):
        from shared.storage.minio_client import MinioObjectStore
        with patch("minio.Minio") as mock_minio_cls:
            MinioObjectStore(endpoint="minio.internal:9000", access_key="ak", secret_key="sk")
        mock_minio_cls.assert_called_once_with(
            "minio.internal:9000", access_key="ak", secret_key="sk", secure=True,
        )

    def test_secure_flag_forwarded(self):
        from shared.storage.minio_client import MinioObjectStore
        with patch("minio.Minio") as mock_minio_cls:
            MinioObjectStore(endpoint="minio.internal:9000", access_key="ak", secret_key="sk", secure=False)
        mock_minio_cls.assert_called_once_with(
            "minio.internal:9000", access_key="ak", secret_key="sk", secure=False,
        )


class TestEnsureBucket:
    @pytest.mark.asyncio
    async def test_creates_bucket_when_missing(self):
        mock_client = MagicMock()
        mock_client.bucket_exists = MagicMock(return_value=False)
        mock_client.make_bucket = MagicMock()
        store = _make_store(mock_client)

        await store.ensure_bucket("cts-images")

        mock_client.bucket_exists.assert_called_once_with("cts-images")
        mock_client.make_bucket.assert_called_once_with("cts-images", object_lock=False)

    @pytest.mark.asyncio
    async def test_skips_creation_when_bucket_exists(self):
        mock_client = MagicMock()
        mock_client.bucket_exists = MagicMock(return_value=True)
        mock_client.make_bucket = MagicMock()
        store = _make_store(mock_client)

        await store.ensure_bucket("cts-images")

        mock_client.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_object_lock_forwarded_for_worm_buckets(self):
        mock_client = MagicMock()
        mock_client.bucket_exists = MagicMock(return_value=False)
        mock_client.make_bucket = MagicMock()
        store = _make_store(mock_client)

        await store.ensure_bucket("cts-images-worm", object_lock=True)

        mock_client.make_bucket.assert_called_once_with("cts-images-worm", object_lock=True)


class TestUploadBytes:
    @pytest.mark.asyncio
    async def test_uploads_and_returns_object_key(self):
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()
        store = _make_store(mock_client)

        data = b"fake jpeg bytes"
        result = await store.upload_bytes("cts-images", "bank1/scan1/front.jpg", data, content_type="image/jpeg")

        assert result == "bank1/scan1/front.jpg"
        mock_client.put_object.assert_called_once()
        args = mock_client.put_object.call_args.args
        assert args[0] == "cts-images"
        assert args[1] == "bank1/scan1/front.jpg"
        assert isinstance(args[2], io.BytesIO)
        assert args[3] == len(data)
        assert args[4] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_default_content_type_is_octet_stream(self):
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()
        store = _make_store(mock_client)

        await store.upload_bytes("cts-images", "bank1/scan1/front.jpg", b"data")

        args = mock_client.put_object.call_args.args
        assert args[4] == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_upload_failure_propagates(self):
        """Upload failures must propagate — the caller (ingestion service)
        decides whether to retry/quarantine; silently swallowing an upload
        failure would leave cheque_image_metadata pointing at a non-existent
        object."""
        mock_client = MagicMock()
        mock_client.put_object = MagicMock(side_effect=Exception("MinIO unreachable"))
        store = _make_store(mock_client)

        with pytest.raises(Exception, match="MinIO unreachable"):
            await store.upload_bytes("cts-images", "bank1/scan1/front.jpg", b"data")


class TestDownloadBytes:
    @pytest.mark.asyncio
    async def test_returns_response_bytes_and_closes_connection(self):
        mock_response = MagicMock()
        mock_response.read = MagicMock(return_value=b"downloaded bytes")
        mock_client = MagicMock()
        mock_client.get_object = MagicMock(return_value=mock_response)
        store = _make_store(mock_client)

        result = await store.download_bytes("cts-images", "bank1/scan1/front.jpg")

        assert result == b"downloaded bytes"
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_connection_even_on_read_failure(self):
        mock_response = MagicMock()
        mock_response.read = MagicMock(side_effect=Exception("stream error"))
        mock_client = MagicMock()
        mock_client.get_object = MagicMock(return_value=mock_response)
        store = _make_store(mock_client)

        with pytest.raises(Exception, match="stream error"):
            await store.download_bytes("cts-images", "bank1/scan1/front.jpg")

        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()


class TestPresignedUrl:
    @pytest.mark.asyncio
    async def test_returns_presigned_url_with_default_expiry(self):
        from datetime import timedelta
        mock_client = MagicMock()
        mock_client.presigned_get_object = MagicMock(return_value="https://minio.internal/presigned")
        store = _make_store(mock_client)

        result = await store.presigned_url("cts-images", "bank1/scan1/front.jpg")

        assert result == "https://minio.internal/presigned"
        args = mock_client.presigned_get_object.call_args.args
        assert args[0] == "cts-images"
        assert args[1] == "bank1/scan1/front.jpg"
        assert args[2] == timedelta(seconds=3600)

    @pytest.mark.asyncio
    async def test_custom_expiry_forwarded(self):
        from datetime import timedelta
        mock_client = MagicMock()
        mock_client.presigned_get_object = MagicMock(return_value="https://minio.internal/presigned")
        store = _make_store(mock_client)

        await store.presigned_url("cts-images", "bank1/scan1/front.jpg", expiry_seconds=600)

        args = mock_client.presigned_get_object.call_args.args
        assert args[2] == timedelta(seconds=600)
