"""
Tests for modules/cts/lot/lot_store.py

LotStore.build_ngch_file() — reads accepted instruments for a lot from DB,
assembles CXF XML, uploads to MinIO, returns (file_path, sha256_hex).
"""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_db():
    """asyncpg pool with one connection that returns test instrument rows."""
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=conn)

    # outward_scan_events rows (instrument_id list for the lot)
    scan_rows = [
        {"instrument_id": "INST-001", "scanned_at": "2026-09-01T10:00:00+05:30"},
        {"instrument_id": "INST-002", "scanned_at": "2026-09-01T10:01:00+05:30"},
    ]
    # cheque_instruments rows
    instr_rows = [
        {
            "instrument_id": "INST-001",
            "cheque_number": "100001",
            "micr_code": "400053001",
            "drawee_ifsc": "SVCB0000001",
            "presenting_ifsc": "SVCB0000002",
            "amount_paise": 5000000,
            "cheque_date": "2026-09-01",
            "account_last4": "4521",
        },
        {
            "instrument_id": "INST-002",
            "cheque_number": "100002",
            "micr_code": "400053002",
            "drawee_ifsc": "SVCB0000001",
            "presenting_ifsc": "SVCB0000002",
            "amount_paise": 12500000,
            "cheque_date": "2026-09-01",
            "account_last4": "7890",
        },
    ]

    # fetch returns scan_rows first call, instr_rows second
    conn.fetch = AsyncMock(side_effect=[scan_rows, instr_rows])
    return pool, conn


def _mock_minio():
    """MinIO client stub that records uploaded object key."""
    minio = MagicMock()
    minio.put_object = MagicMock()
    return minio


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLotStoreBuildNgchFile:
    @pytest.mark.asyncio
    async def test_returns_file_path_with_correct_key(self):
        from modules.cts.lot.lot_store import LotStore

        pool, _ = _mock_db()
        minio = _mock_minio()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        file_path, checksum = await store.build_ngch_file(
            lot_number="LOT_SVCB0000002_20260901_AM_01",
            bank_id="test-bank",
            bank_ifsc="SVCB0000002",
            session_id="SES-ABC001",
            clearing_date="2026-09-01",
        )

        assert file_path.startswith("cts/ngch/test-bank/")
        assert file_path.endswith(".xml")

    @pytest.mark.asyncio
    async def test_returns_valid_sha256_hex(self):
        from modules.cts.lot.lot_store import LotStore

        pool, _ = _mock_db()
        minio = _mock_minio()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        _, checksum = await store.build_ngch_file(
            lot_number="LOT_SVCB0000002_20260901_AM_01",
            bank_id="test-bank",
            bank_ifsc="SVCB0000002",
            session_id="SES-ABC001",
            clearing_date="2026-09-01",
        )

        # Must be a valid 64-char lowercase hex (SHA-256)
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    @pytest.mark.asyncio
    async def test_minio_put_object_called(self):
        from modules.cts.lot.lot_store import LotStore

        pool, _ = _mock_db()
        minio = _mock_minio()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        await store.build_ngch_file(
            lot_number="LOT_SVCB0000002_20260901_AM_01",
            bank_id="test-bank",
            bank_ifsc="SVCB0000002",
            session_id="SES-ABC001",
            clearing_date="2026-09-01",
        )

        assert minio.put_object.called

    @pytest.mark.asyncio
    async def test_empty_lot_returns_stub_path(self):
        """When no accepted instruments found, build an empty-lot stub file."""
        from modules.cts.lot.lot_store import LotStore

        conn = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=conn)
        # Empty lot — fetch returns empty list for scan events
        conn.fetch = AsyncMock(side_effect=[[], []])

        minio = _mock_minio()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        file_path, checksum = await store.build_ngch_file(
            lot_number="LOT_SVCB0000002_20260901_AM_99",
            bank_id="test-bank",
            bank_ifsc="SVCB0000002",
            session_id="SES-ABC001",
            clearing_date="2026-09-01",
        )

        # Even empty lot produces valid output (MinIO not called, stub path returned)
        assert "test-bank" in file_path

    @pytest.mark.asyncio
    async def test_xml_content_contains_instrument_count(self):
        """The CXF XML BatchHeader must state ItemCount == 2 for a 2-instrument lot."""
        from modules.cts.lot.lot_store import LotStore

        pool, _ = _mock_db()
        captured_bytes = []

        minio = MagicMock()
        def capture_put(bucket, key, data, length, content_type):
            captured_bytes.append(data.read())
        minio.put_object = MagicMock(side_effect=capture_put)

        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")
        await store.build_ngch_file(
            lot_number="LOT_SVCB0000002_20260901_AM_01",
            bank_id="test-bank",
            bank_ifsc="SVCB0000002",
            session_id="SES-ABC001",
            clearing_date="2026-09-01",
        )

        assert len(captured_bytes) == 1
        xml_str = captured_bytes[0].decode("utf-8")
        assert "<ItemCount>2</ItemCount>" in xml_str
        assert "INST-001" not in xml_str  # instrument_id is internal — not in CXF
        assert "100001" in xml_str         # cheque_number is in CXF
