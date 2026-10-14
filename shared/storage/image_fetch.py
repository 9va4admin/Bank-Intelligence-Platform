"""Turn an image URL into bytes — the one place activities must use.

Accepted: s3://bucket/key (object URLs the API hands to scanners) and http(s):// (presigned URLs).
Anything else raises ValueError. The MinIO store is configured once by the worker
(configure_default_store) or built lazily from config_service.
"""
from typing import Any, Optional
from urllib.parse import urlparse

_default_store: Optional[Any] = None


def configure_default_store(store: Any) -> None:
    global _default_store
    _default_store = store


async def _store() -> Any:
    global _default_store
    if _default_store is None:
        from shared.config.config_service import config_service
        from shared.config.exceptions import ConfigKeyNotFoundError
        from shared.storage.minio_client import MinioObjectStore
        try:
            secure = str(config_service.get_platform("minio.secure")).lower() in ("true", "1")
        except ConfigKeyNotFoundError:
            secure = True
        _default_store = MinioObjectStore(
            endpoint=await config_service.get_secret("minio.endpoint"),
            access_key=await config_service.get_secret("minio.access_key"),
            secret_key=await config_service.get_secret("minio.secret_key"),
            secure=secure,
        )
    return _default_store


async def fetch_image_bytes(url: str, timeout: float = 15.0) -> bytes:
    scheme = urlparse(url or "").scheme.lower()
    if scheme == "s3":
        parsed = urlparse(url)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"malformed s3 URL (need s3://bucket/key): {url!r}")
        return await (await _store()).download_bytes(bucket, key)
    if scheme in ("http", "https"):
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    raise ValueError(f"unsupported image URL scheme: {url!r}")
