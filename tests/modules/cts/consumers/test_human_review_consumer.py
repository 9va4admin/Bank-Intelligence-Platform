"""
Tests for modules/cts/consumers/human_review_consumer.py

Consumes cts.human.review.{bank_id} events and:
  - Writes CTS_REVIEW_ASSIGNED audit record to Immudb
  - Updates cts.cheque_instruments status to IN_HUMAN_REVIEW in YugabyteDB

Critical invariants:
  - Every routing-to-human-review is an auditable event (RBI requirement)
  - Wrong bank_id → skipped
  - Immudb unavailable → logs warning, no crash
  - DB unavailable → logs warning, no crash
"""
import pytest
from unittest.mock import AsyncMock

from shared.event_bus.schemas import KafkaEventEnvelope


def _make_envelope(
    bank_id="saraswat-coop",
    event_type="CTS_HUMAN_REVIEW_REQUIRED",
    instrument_id="INST-002",
    workflow_id="cts-saraswat-coop-INST-002",
    iet_deadline=9999999999.0,
):
    return KafkaEventEnvelope(
        event_id="evt-002",
        event_type=event_type,
        bank_id=bank_id,
        schema_version="1.0",
        payload={
            "instrument_id": instrument_id,
            "workflow_id": workflow_id,
            "context_bundle": {"fraud_score": 0.74, "ocr_confidence": 0.91},
            "iet_deadline": iet_deadline,
        },
    )


class TestHandleHumanReviewEvent:

    @pytest.mark.asyncio
    async def test_writes_immudb_review_assigned(self):
        """CTS_HUMAN_REVIEW_REQUIRED → Immudb write with CTS_REVIEW_ASSIGNED type."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        immudb.write_event.assert_awaited_once()
        call_kwargs = immudb.write_event.call_args[1]
        assert call_kwargs["event_type"] == "CTS_REVIEW_ASSIGNED"
        assert call_kwargs["bank_id"] == "saraswat-coop"
        assert "INST-002" in str(call_kwargs["payload"])

    @pytest.mark.asyncio
    async def test_updates_instrument_status_in_db(self):
        """CTS_HUMAN_REVIEW_REQUIRED → updates cheque_instruments status to IN_HUMAN_REVIEW."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        conn = AsyncMock()
        db = AsyncMock()
        db.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        db.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        conn.execute.assert_awaited_once()
        sql = conn.execute.call_args[0][0]
        assert "IN_HUMAN_REVIEW" in sql or "status" in sql.lower()

    @pytest.mark.asyncio
    async def test_wrong_bank_id_skipped(self):
        """Envelope bank_id != consumer's bank_id → no writes."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(bank_id="wrong-bank")

        await handle_human_review_event(
            envelope, immudb=immudb, db=db, consumer_bank_id="saraswat-coop"
        )

        immudb.write_event.assert_not_awaited()
        db.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_immudb_unavailable_does_not_crash(self):
        """Immudb=None → logs warning, returns cleanly."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=None, db=db)

    @pytest.mark.asyncio
    async def test_db_unavailable_does_not_crash(self):
        """DB=None → logs warning, returns cleanly."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=None)

    @pytest.mark.asyncio
    async def test_immudb_error_does_not_crash(self):
        """Immudb write failure → logs error, does not crash consumer."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        immudb.write_event.side_effect = RuntimeError("immudb timeout")
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_human_review_event(envelope, immudb=immudb, db=db)

    @pytest.mark.asyncio
    async def test_iet_deadline_included_in_audit_payload(self):
        """IET deadline is captured in the Immudb payload — reviewers need to know urgency."""
        from modules.cts.consumers.human_review_consumer import handle_human_review_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(iet_deadline=1750000000.0)

        await handle_human_review_event(envelope, immudb=immudb, db=db)

        payload = immudb.write_event.call_args[1]["payload"]
        assert payload.get("iet_deadline") == 1750000000.0
