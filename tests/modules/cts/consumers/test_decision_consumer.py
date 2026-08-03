"""
Tests for modules/cts/consumers/decision_consumer.py

Consumes cts.decisions.{bank_id} events and:
  - Writes CTS_NGCH_FILED audit record to Immudb
  - Updates cts.cheque_instruments with final NGCH acknowledgement_id

Critical invariants:
  - Wrong bank_id in envelope → silently skipped
  - Immudb unavailable → logs warning, does not crash
  - DB unavailable → logs warning, does not crash
  - Unknown event_type → silently skipped
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.event_bus.schemas import KafkaEventEnvelope


def _make_envelope(
    bank_id="saraswat-coop",
    event_type="CTS_NGCH_FILED",
    instrument_id="INST-001",
    decision="STP_CONFIRM",
    acknowledgement_id="NGCH-ACK-001",
    workflow_id="cts-saraswat-coop-INST-001",
    schema_version="1.0",
):
    return KafkaEventEnvelope(
        event_id="evt-001",
        event_type=event_type,
        bank_id=bank_id,
        schema_version=schema_version,
        payload={
            "instrument_id": instrument_id,
            "decision": decision,
            "acknowledgement_id": acknowledgement_id,
            "workflow_id": workflow_id,
        },
    )


class TestHandleDecisionEvent:

    @pytest.mark.asyncio
    async def test_ngch_filed_writes_immudb(self):
        """CTS_NGCH_FILED → Immudb write with CTS_NGCH_FILED event type."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_decision_event(envelope, immudb=immudb, db=db)

        immudb.write_event.assert_awaited_once()
        call_kwargs = immudb.write_event.call_args[1]
        assert call_kwargs["event_type"] == "CTS_NGCH_FILED"
        assert call_kwargs["bank_id"] == "saraswat-coop"
        assert "INST-001" in str(call_kwargs["payload"])

    @pytest.mark.asyncio
    async def test_ngch_filed_updates_db_acknowledgement(self):
        """CTS_NGCH_FILED → updates cheque_instruments with acknowledgement_id."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        conn = AsyncMock()
        db = AsyncMock()
        db.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        db.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        envelope = _make_envelope()

        await handle_decision_event(envelope, immudb=immudb, db=db)

        conn.execute.assert_awaited_once()
        sql = conn.execute.call_args[0][0]
        assert "acknowledgement_id" in sql.lower() or "ngch_ack" in sql.lower()

    @pytest.mark.asyncio
    async def test_wrong_bank_id_skipped(self):
        """Envelope bank_id != consumer's bank_id → no writes."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(bank_id="other-bank")

        await handle_decision_event(envelope, immudb=immudb, db=db, consumer_bank_id="saraswat-coop")

        immudb.write_event.assert_not_awaited()
        db.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_immudb_unavailable_does_not_crash(self):
        """Immudb=None → logs warning, returns cleanly."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        envelope = _make_envelope()
        db = AsyncMock()

        await handle_decision_event(envelope, immudb=None, db=db)  # must not raise

    @pytest.mark.asyncio
    async def test_db_unavailable_does_not_crash(self):
        """DB=None → logs warning, returns cleanly."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        envelope = _make_envelope()

        await handle_decision_event(envelope, immudb=immudb, db=None)  # must not raise

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped(self):
        """Non-decision event_type on this topic → skipped silently."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        db = AsyncMock()
        envelope = _make_envelope(event_type="SOME_OTHER_EVENT")

        await handle_decision_event(envelope, immudb=immudb, db=db)

        immudb.write_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_immudb_error_does_not_crash(self):
        """Immudb write failure → logs error, does not crash consumer."""
        from modules.cts.consumers.decision_consumer import handle_decision_event

        immudb = AsyncMock()
        immudb.write_event.side_effect = RuntimeError("immudb down")
        db = AsyncMock()
        envelope = _make_envelope()

        await handle_decision_event(envelope, immudb=immudb, db=db)  # must not raise
