"""
Tests for modules/ej/workflows/activities/trigger_dispute_check.py

Publishes normalised EJ record to Kafka for dispute matching.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ej.workflows.activities.trigger_dispute_check import (
    EJTriggerDisputeCheckResult,
    trigger_dispute_check,
)


def _mock_producer():
    producer = MagicMock()
    producer.publish = AsyncMock(return_value=None)
    return producer


class TestEJTriggerDisputeCheckResult:
    def test_result_fields(self):
        r = EJTriggerDisputeCheckResult(outcome="TRIGGERED", bank_id="test-bank")
        assert r.outcome == "TRIGGERED"
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJTriggerDisputeCheckResult(outcome="TRIGGERED", bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestTriggerDisputeCheckActivity:
    @pytest.mark.asyncio
    async def test_happy_path_returns_triggered(self):
        result = await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=_mock_producer(),
        )
        assert result.outcome == "TRIGGERED"

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="kotak-mah",
            kafka_producer=_mock_producer(),
        )
        assert result.bank_id == "kotak-mah"

    @pytest.mark.asyncio
    async def test_no_producer_returns_skipped(self):
        """Without kafka_producer, activity degrades gracefully to SKIPPED."""
        result = await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=None,
        )
        assert result.outcome == "SKIPPED"

    @pytest.mark.asyncio
    async def test_kafka_topic_is_bank_scoped(self):
        producer = _mock_producer()
        await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="saraswat-coop",
            kafka_producer=producer,
        )
        call_kwargs = producer.publish.call_args.kwargs
        assert call_kwargs["topic"] == "ej.canonical.saraswat-coop"

    @pytest.mark.asyncio
    async def test_canonical_record_included_in_payload(self):
        producer = _mock_producer()
        await trigger_dispute_check(
            canonical_hash="a" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            canonical_record={"transaction_type": "DISPENSE"},
            kafka_producer=producer,
        )
        call_kwargs = producer.publish.call_args.kwargs
        assert call_kwargs["payload"]["transaction_type"] == "DISPENSE"
