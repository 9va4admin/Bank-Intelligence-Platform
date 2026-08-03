"""
Tests for modules/ej/workflows/activities/write_audit.py

Publishes EJ normalisation audit events to Kafka platform.audit.events topic.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ej.workflows.activities.write_audit import (
    EJWriteAuditResult,
    write_audit,
)


def _mock_producer():
    """Return an AsyncMock publisher that accepts publish() calls."""
    producer = MagicMock()
    producer.publish = AsyncMock(return_value=None)
    return producer


class TestEJWriteAuditResult:
    def test_result_fields(self):
        r = EJWriteAuditResult(outcome="WRITTEN", bank_id="test-bank")
        assert r.outcome == "WRITTEN"
        assert r.bank_id == "test-bank"

    def test_result_is_frozen(self):
        r = EJWriteAuditResult(outcome="WRITTEN", bank_id="test-bank")
        with pytest.raises(Exception):
            r.outcome = "other"


class TestWriteAuditActivity:
    @pytest.mark.asyncio
    async def test_write_on_normalised_outcome(self):
        result = await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=_mock_producer(),
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_write_on_parse_failed_outcome(self):
        result = await write_audit(
            workflow_outcome="PARSE_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash=None,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=_mock_producer(),
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_write_on_validation_failed_outcome(self):
        result = await write_audit(
            workflow_outcome="VALIDATION_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=_mock_producer(),
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        result = await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="kotak-mah",
            kafka_producer=_mock_producer(),
        )
        assert result.bank_id == "kotak-mah"

    @pytest.mark.asyncio
    async def test_accepts_none_canonical_hash(self):
        """canonical_hash is None when parse fails before hash is produced."""
        result = await write_audit(
            workflow_outcome="PARSE_FAILED",
            raw_log_hash="a" * 64,
            canonical_hash=None,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=_mock_producer(),
        )
        assert result.outcome == "WRITTEN"

    @pytest.mark.asyncio
    async def test_no_producer_returns_skipped(self):
        """Without kafka_producer, activity degrades gracefully to SKIPPED."""
        result = await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=None,
        )
        assert result.outcome == "SKIPPED"

    @pytest.mark.asyncio
    async def test_kafka_publish_called_with_correct_topic(self):
        """Verify the correct Kafka topic receives the audit event."""
        producer = _mock_producer()
        await write_audit(
            workflow_outcome="NORMALISED",
            raw_log_hash="a" * 64,
            canonical_hash="b" * 64,
            atm_id="ATM001",
            bank_id="test-bank",
            kafka_producer=producer,
        )
        producer.publish.assert_called_once()
        call_kwargs = producer.publish.call_args.kwargs
        assert call_kwargs["topic"] == "platform.audit.events"
