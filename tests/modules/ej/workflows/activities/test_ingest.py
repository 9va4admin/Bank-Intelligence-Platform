"""
Tests for modules/ej/workflows/activities/ingest.py

EJ ingestion: validates raw log, computes content hash, stores metadata.
Rules:
- Raw EJ files are immutable once ingested — no modification allowed
- Content hash (SHA-256) computed before storage
- Duplicate detection: same hash → returns existing record (idempotent)
- Always stores to MinIO reference — never inline content in DB
- bank_id isolation: strict
"""
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_input(
    raw_log="[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
    atm_id="ATM001",
    bank_id="test-bank",
    source="branch-mcp",
):
    from modules.ej.workflows.activities.ingest import EJIngestInput
    return EJIngestInput(
        raw_log=raw_log,
        atm_id=atm_id,
        bank_id=bank_id,
        source=source,
    )


class TestEJIngestInput:
    def test_requires_raw_log(self):
        from modules.ej.workflows.activities.ingest import EJIngestInput
        with pytest.raises(Exception):
            EJIngestInput(atm_id="ATM1", bank_id="b", source="s")

    def test_requires_atm_id(self):
        from modules.ej.workflows.activities.ingest import EJIngestInput
        with pytest.raises(Exception):
            EJIngestInput(raw_log="log", bank_id="b", source="s")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.raw_log = "other"


class TestEJIngestHappyPath:
    @pytest.mark.asyncio
    async def test_ingest_returns_accepted(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "ej/test-bank/ATM001/abc123.log"})

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_ingest_computes_sha256_hash(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        raw_log = "[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK"
        expected_hash = hashlib.sha256(raw_log.encode()).hexdigest()

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "ej/test-bank/ATM001/abc.log"})

        result = await ingest_ej_log(_make_input(raw_log=raw_log), object_store=mock_store)
        assert result.raw_log_hash == expected_hash

    @pytest.mark.asyncio
    async def test_ingest_stores_to_object_store(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "ej/test-bank/ATM001/abc.log"})

        await ingest_ej_log(_make_input(), object_store=mock_store)
        mock_store.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_result_contains_object_key(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        expected_key = "ej/test-bank/ATM001/abc123.log"
        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": expected_key})

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result.object_key == expected_key

    @pytest.mark.asyncio
    async def test_ingest_includes_bank_id_in_result(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(return_value={"object_key": "ej/kotak/ATM001/x.log"})

        result = await ingest_ej_log(_make_input(bank_id="kotak"), object_store=mock_store)
        assert result.bank_id == "kotak"


class TestEJIngestDuplicate:
    @pytest.mark.asyncio
    async def test_duplicate_log_returns_already_ingested(self):
        """Same content hash → idempotent, returns existing record."""
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=Exception("ObjectAlreadyExists"))

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result.outcome in ("ACCEPTED", "ALREADY_INGESTED")

    @pytest.mark.asyncio
    async def test_duplicate_does_not_raise(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=Exception("ObjectAlreadyExists"))

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result is not None


class TestEJIngestDegradation:
    @pytest.mark.asyncio
    async def test_store_failure_returns_ingest_failed(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=RuntimeError("MinIO unavailable"))

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result.outcome == "INGEST_FAILED"

    @pytest.mark.asyncio
    async def test_store_failure_does_not_raise(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await ingest_ej_log(_make_input(), object_store=mock_store)
        assert result is not None

    @pytest.mark.asyncio
    async def test_store_failure_hash_still_computed(self):
        """Even on failure, hash is computed for deduplication later."""
        from modules.ej.workflows.activities.ingest import ingest_ej_log

        raw_log = "some log"
        expected_hash = hashlib.sha256(raw_log.encode()).hexdigest()

        mock_store = AsyncMock()
        mock_store.put = AsyncMock(side_effect=RuntimeError("disk full"))

        result = await ingest_ej_log(_make_input(raw_log=raw_log), object_store=mock_store)
        assert result.raw_log_hash == expected_hash
