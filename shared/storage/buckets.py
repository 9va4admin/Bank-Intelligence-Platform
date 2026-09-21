"""Registry of every MinIO bucket the platform references, and an idempotent bootstrap.

Nothing in the repo or infra created these, so the first real upload failed with NoSuchBucket.
ensure_required_buckets is a no-op wherever infra (Helm/mc) already created them; production
WORM/ILM policy stays an infra concern. Bucket creation failure is reported, never raised: a
missing bucket must degrade the feature that needs it, not stop the service.
"""
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


async def ensure_required_buckets(store: Any) -> list[str]:
    """Create any missing bucket. Returns the names that could not be ensured."""
    if store is None:
        return list(REQUIRED_BUCKETS)
    failed: list[str] = []
    for name in REQUIRED_BUCKETS:
        try:
            await store.ensure_bucket(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("storage.bucket_ensure_failed", bucket=name, error=str(exc))
            failed.append(name)
    return failed
