"""OCR training corpus manager — MinIO storage + Redis counter.

Accumulates validated training candidates automatically. No human trigger
needed. When a bank's corpus crosses the configured threshold, signals
the FeedbackAccumulatorWorkflow to kick off retraining.

Storage layout (MinIO):
  Bucket : cts-ocr-corpus
  Path   : {bank_id}/payee/{year}/{month}/{instrument_id}.json
           {bank_id}/micr/{year}/{month}/{instrument_id}.json

Redis key (corpus size tracking):
  feedback:corpus:{bank_id}:payee:count   (INCR — atomic)
  feedback:corpus:{bank_id}:micr:count    (INCR — atomic)
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


_CORPUS_BUCKET = "cts-ocr-corpus"


@dataclass
class CorpusEntry:
    instrument_id: str
    bank_id: str
    image_path: str          # MinIO path to original cheque TIFF
    ocr_text: str            # what the OCR engine read
    label: str               # "positive" | "negative"
    failure_mode_str: str    # FailureMode.value
    corpus_type: str = "payee"   # "payee" | "micr"
    ts: str = ""             # ISO timestamp — filled by add_entry

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


@dataclass
class CorpusStats:
    bank_id: str
    count: int
    corpus_type: str = "payee"


class CorpusManager:
    """Manages the per-bank OCR training corpus in MinIO and Redis.

    Both `minio_client` and `redis_client` are injected — never constructed
    here, always from app.state (the DI pattern used throughout ASTRA).
    """

    def __init__(self, minio_client: Any, redis_client: Any) -> None:
        self._minio = minio_client
        self._redis = redis_client

    async def add_entry(self, entry: CorpusEntry) -> None:
        """Write a training candidate to MinIO and increment the Redis counter.

        Called automatically from FeedbackAccumulatorWorkflow — never by
        bank staff.
        """
        now = datetime.now(timezone.utc)
        object_path = (
            f"{entry.bank_id}/{entry.corpus_type}/"
            f"{now.year}/{now.month:02d}/{entry.instrument_id}.json"
        )
        payload = json.dumps(asdict(entry), ensure_ascii=False).encode("utf-8")

        await self._minio.put_object(
            bucket_name=_CORPUS_BUCKET,
            object_name=object_path,
            data=io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
        )

        redis_key = self._counter_key(entry.bank_id, entry.corpus_type)
        await self._redis.incr(redis_key)

    async def get_stats(self, bank_id: str, corpus_type: str = "payee") -> CorpusStats:
        """Return current corpus size for a bank from Redis."""
        redis_key = self._counter_key(bank_id, corpus_type)
        raw = await self._redis.get(redis_key)
        count = int(raw) if raw else 0
        return CorpusStats(bank_id=bank_id, count=count, corpus_type=corpus_type)

    async def should_trigger_retrain(
        self,
        bank_id: str,
        threshold: int,
        corpus_type: str = "payee",
    ) -> bool:
        """Return True when accumulated corpus exceeds the configured threshold."""
        stats = await self.get_stats(bank_id, corpus_type)
        return stats.count >= threshold

    async def reset_counter(self, bank_id: str, corpus_type: str = "payee") -> None:
        """Reset the corpus counter after a retraining job has been dispatched."""
        redis_key = self._counter_key(bank_id, corpus_type)
        await self._redis.set(redis_key, 0)

    @staticmethod
    def _counter_key(bank_id: str, corpus_type: str) -> str:
        return f"feedback:corpus:{bank_id}:{corpus_type}:count"
