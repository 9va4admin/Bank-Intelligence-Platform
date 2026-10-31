"""Turn an image URL into bytes — the one place activities must use.

Accepted: s3://bucket/key (object URLs the API hands to scanners), minio://bucket/key (the same thing, written by the scanner
drop-folder watcher and the branch EEH upload) and http(s):// (presigned URLs). Anything else raises ValueError - a bare object key
has no bucket, so build the reference with image_ref(). The MinIO store is configured once by the worker
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


def image_ref(bucket: str, key: str) -> str:
    """The bucket-qualified reference every image-reading activity understands."""
    return f"s3://{bucket}/{str(key).lstrip('/')}"


async def fetch_image_bytes(url: str, timeout: float = 15.0) -> bytes:
    scheme = urlparse(url or "").scheme.lower()
    if scheme in ("s3", "minio"):
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


async def model_image_url(url: str) -> str:
    """The form of an image reference a model server can read.

    vLLM fetches http(s) and data: URLs only, so an s3:// or minio:// reference is read here and handed over as a data URI
    (PNG, JPEG as-is). The image stays inside the bank: the model server is on-premises."""
    scheme = urlparse(url or "").scheme.lower()
    if scheme in ("http", "https", "data"):
        return url
    import base64
    import io
    raw = await fetch_image_bytes(url)
    if raw.startswith(bytes.fromhex("ffd8ff")):
        mime = "image/jpeg"
    elif raw.startswith(bytes.fromhex("89504e470d0a1a0a")):
        mime = "image/png"
    else:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(raw)).convert("RGB").save(buf, format="PNG")
        raw, mime = buf.getvalue(), "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
