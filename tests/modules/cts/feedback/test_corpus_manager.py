"""Tests for corpus accumulation manager.

Manages the training corpus in MinIO and tracks corpus size in Redis.
Fully automated — no human triggers required.

Triggers retraining when per-bank corpus crosses the configured threshold.
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


from modules.cts.feedback.corpus_manager import (
    CorpusManager,
    CorpusEntry,
    CorpusStats,
)


@dataclass
class _FakeSignal:
    instrument_id: str
    bank_id: str
    ocr_payee: str
    image_path: str
    add_to_corpus: bool
    corpus_label: str = "negative"
    failure_mode: object = None


class TestCorpusManager:
    def _make_manager(self):
        minio = MagicMock()
        redis = MagicMock()
        redis.incr = AsyncMock(return_value=1)
        redis.get = AsyncMock(return_value=b"0")
        redis.set = AsyncMock()
        minio.put_object = AsyncMock()
        return CorpusManager(minio_client=minio, redis_client=redis)

    @pytest.mark.asyncio
    async def test_add_entry_calls_minio_put(self):
        mgr = self._make_manager()
        entry = CorpusEntry(
            instrument_id="CHQ-001",
            bank_id="saraswat-coop",
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-001.tiff",
            ocr_text="रामश्वर",
            label="negative",
            failure_mode_str="OCR_CHAR_ERROR",
        )
        await mgr.add_entry(entry)
        mgr._minio.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_entry_increments_redis_counter(self):
        mgr = self._make_manager()
        entry = CorpusEntry(
            instrument_id="CHQ-002",
            bank_id="saraswat-coop",
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-002.tiff",
            ocr_text="रामश्वर",
            label="negative",
            failure_mode_str="OCR_CHAR_ERROR",
        )
        await mgr.add_entry(entry)
        mgr._redis.incr.assert_called_once()

    @pytest.mark.asyncio
    async def test_corpus_key_is_bank_scoped(self):
        mgr = self._make_manager()
        entry = CorpusEntry(
            instrument_id="CHQ-003",
            bank_id="federal-bank",
            image_path="minio://cts-images/federal-bank/2026/08/CHQ-003.tiff",
            ocr_text="ജോർജ്ജ്",
            label="negative",
            failure_mode_str="LEXICON_GAP",
        )
        await mgr.add_entry(entry)
        call_args = mgr._redis.incr.call_args[0][0]
        assert "federal-bank" in call_args

    @pytest.mark.asyncio
    async def test_get_stats_returns_corpus_stats(self):
        mgr = self._make_manager()
        mgr._redis.get = AsyncMock(return_value=b"47")
        stats = await mgr.get_stats("saraswat-coop")
        assert isinstance(stats, CorpusStats)
        assert stats.bank_id == "saraswat-coop"
        assert stats.count == 47

    @pytest.mark.asyncio
    async def test_retrain_not_triggered_below_threshold(self):
        mgr = self._make_manager()
        mgr._redis.get = AsyncMock(return_value=b"200")
        should = await mgr.should_trigger_retrain("saraswat-coop", threshold=500)
        assert should is False

    @pytest.mark.asyncio
    async def test_retrain_triggered_at_threshold(self):
        mgr = self._make_manager()
        mgr._redis.get = AsyncMock(return_value=b"501")
        should = await mgr.should_trigger_retrain("saraswat-coop", threshold=500)
        assert should is True

    @pytest.mark.asyncio
    async def test_minio_path_follows_convention(self):
        mgr = self._make_manager()
        entry = CorpusEntry(
            instrument_id="CHQ-004",
            bank_id="saraswat-coop",
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-004.tiff",
            ocr_text="देशपांडे",
            label="negative",
            failure_mode_str="OCR_CHAR_ERROR",
        )
        await mgr.add_entry(entry)
        call_kwargs = mgr._minio.put_object.call_args
        # Path must be scoped to bank_id
        bucket_or_path = str(call_kwargs)
        assert "saraswat-coop" in bucket_or_path

    @pytest.mark.asyncio
    async def test_no_raw_account_numbers_in_stored_entry(self):
        """PII guard: corpus entries must never contain raw account numbers."""
        mgr = self._make_manager()
        entry = CorpusEntry(
            instrument_id="CHQ-005",
            bank_id="saraswat-coop",
            image_path="minio://cts-images/saraswat-coop/2026/08/CHQ-005.tiff",
            ocr_text="Ramesh Kumar",
            label="positive",
            failure_mode_str="CLEAN",
        )
        import json
        stored_payload: str | None = None
        async def capture_put(*args, **kwargs):
            nonlocal stored_payload
            data = kwargs.get("data") or (args[2] if len(args) > 2 else None)
            if data and hasattr(data, "read"):
                stored_payload = data.read().decode()
            elif data and isinstance(data, (str, bytes)):
                stored_payload = data if isinstance(data, str) else data.decode()
        mgr._minio.put_object = capture_put
        await mgr.add_entry(entry)

        if stored_payload:
            # No 10+ digit numeric string (raw account numbers are 10+ digits)
            import re
            assert not re.search(r'\d{10,}', stored_payload), \
                "Raw account number found in corpus entry"
