"""Registry of every MinIO bucket the platform references, and an idempotent bootstrap.

Nothing in the repo or infra created these, so the first real upload failed with NoSuchBucket.
ensure_required_buckets is a no-op wherever infra (Helm/mc) already created them; production
WORM/ILM policy stays an infra concern. Bucket creation failure is reported, never raised: a
missing bucket must degrade the feature that needs it, not stop the service.
"""
import asyncio
from typing import Any

import structlog

log = structlog.get_logger()

REQUIRED_BUCKETS: tuple[str, ...] = (
    "cts-images",          # outward scan images (API upload URLs)
    "cts-cheques",         # scanner drop-folder / EEH uploads
    "astra-cts",           # lot store packages
    "astra-cts-reports",   # session reports
    "astra-vault-errors",  # vault upload error files
    "astra-vault-drops",   # vault file-drop staging
    "astra-vault-archive", # vault file-drop archive
    "astra-sig-staging",   # CBS signature image staging
    "cts-ocr-corpus",      # OCR feedback corpus
)


async def ensure_required_buckets(store: Any, per_bucket_timeout: float = 5.0) -> list[str]:
    """Create any missing bucket, concurrently and time-bounded. Returns the names not ensured."""
    if store is None:
        return list(REQUIRED_BUCKETS)

    async def _one(name: str) -> bool:
        try:
            await asyncio.wait_for(store.ensure_bucket(name), timeout=per_bucket_timeout)
            return True
        except Exception as exc:  # noqa: BLE001  (includes TimeoutError)
            log.warning("storage.bucket_ensure_failed", bucket=name, error=str(exc)[:160])
            return False

    results = await asyncio.gather(*[_one(n) for n in REQUIRED_BUCKETS])
    return [n for n, ok in zip(REQUIRED_BUCKETS, results) if not ok]
