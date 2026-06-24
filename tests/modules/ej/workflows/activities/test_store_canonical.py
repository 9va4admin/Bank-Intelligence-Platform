"""
Tests for modules/ej/workflows/activities/store_canonical.py

Persists a normalised EJ canonical record to YugabyteDB.
"""
import pytest

from modules.ej.workflows.activities.store_canonical import (
    EJStoreCanonicalResult,
    store_canonical,
)


class TestEJStoreCanonicalResult:
    def test_result_fields(self):
        r = EJStoreCanonicalResult(outcome="STORED", canonical_hash="a" * 64, bank_id="test-bank")
        assert r.outcome == "STORED"
        assert r.canonical_hash == "a" * 64
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJStoreCanonicalResult(outcome="STORED", canonical_hash="a" * 64, bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestStoreCanonicalActivity:
    @pytest.mark.asyncio
    async def test_happy_path_returns_stored(self):
        result = await store_canonical(
            canonical_record={"transaction_type": "DISPENSE", "amount": 5000.0},
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.outcome == "STORED"

    @pytest.mark.asyncio
    async def test_canonical_hash_preserved_in_result(self):
        result = await store_canonical(
            canonical_record={"transaction_type": "DISPENSE"},
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
        )
        assert result.canonical_hash == "b" * 64

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await store_canonical(
            canonical_record={},
            canonical_hash="c" * 64,
            atm_id="ATM002",
            bank_id="kotak-mah",
        )
        assert result.bank_id == "kotak-mah"
