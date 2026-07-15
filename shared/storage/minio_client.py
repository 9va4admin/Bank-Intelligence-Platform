"""
MinioObjectStore — thin async wrapper around the official minio.Minio SDK.

minio.Minio is entirely synchronous (built on urllib3, not aiohttp/httpx) —
every blocking call is wrapped in asyncio.to_thread(), matching the pattern
already established in modules/cts/dem/sftp_client.py for paramiko (Phase 4,
same session): a sync-only SDK wrapped at the boundary, never blocking the
event loop.

SSE-KMS (Vault Transit) is a bucket-level MinIO server default per
.claude/rules/pii-data-protection.md, provisioned at Helm/infra deploy time —
not something this client sets per upload call.
"""
from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from typing import Any

import structlog

log = structlog.get_logger()


class MinioObjectStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = True) -> None:
        from minio import Minio
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    async def ensure_bucket(self, bucket_name: str, *, object_lock: bool = False) -> None:
        """
        Idempotent bucket creation. object_lock=True enables MinIO Object
        Lock (WORM) for Tier 3 regulatory-retention buckets — see CLAUDE.md
        storage tier table. Safe to call on every startup.
        """
        exists = await asyncio.to_thread(self._client.bucket_exists, bucket_name)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, bucket_name, object_lock=object_lock)
            log.info("minio.bucket_created", bucket=bucket_name, object_lock=object_lock)

    async def upload_bytes(
        self,
        bucket_name: str,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Uploads raw bytes and returns the object_key on success.
        Raises on failure — never silently swallowed; the caller decides
        whether to retry or quarantine (matching DropFolderWatcher's
        existing quarantine-on-failure pattern).
        """
        await asyncio.to_thread(
            self._client.put_object,
            bucket_name, object_key, io.BytesIO(data), len(data), content_type,
        )
        log.info("minio.object_uploaded", bucket=bucket_name, object_key=object_key, size_bytes=len(data))
        return object_key

    async def download_bytes(self, bucket_name: str, object_key: str) -> bytes:
        response = await asyncio.to_thread(self._client.get_object, bucket_name, object_key)
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def presigned_url(self, bucket_name: str, object_key: str, expiry_seconds: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.presigned_get_object,
            bucket_name, object_key, timedelta(seconds=expiry_seconds),
        )
