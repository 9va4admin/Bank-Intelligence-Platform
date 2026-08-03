"""
Tests for modules/cts/consumers/vault_sync_consumer.py

Consumes cts.vault.sync.{bank_id} events and writes sync stats to Immudb:
  - signatures_loaded, pps_records_loaded, cheque_leaves_loaded
  - integrity_check_passed, outcome (SYNC_COMPLETE | PARTIAL_FAILURE)
  - started_at, completed_at (from payload)
  - triggered_by (SCHEDULED | MANUAL | MCP)

This is the RBI-auditable record of when the vault was last synced
and how many records were loaded.

Critical invariants:
  - Both SYNC_COMPLETE and PARTIAL_FAILURE write to Immudb
  - Wrong bank_id → skipped
  - Immudb unavailable → logs warning, no crash
"""
import pytest
from unittest.mock import AsyncMock

from shared.event_bus.schemas import KafkaEventEnvelope


def _make_envelope(
    bank_id="saraswat-coop",
    event_type="CTS_VAULT_SYNC_COMPLETE",
    outcome="SYNC_COMPLETE",
    signatures_loaded=1200,
    pps_records_loaded=340,
    cheque_leaves_loaded=850,
    integrity_check_passed=True,
    triggered_by="SCHEDULED",
    started_at="2026-08-03T06:00:00Z",
    completed_at="2026-08-03T06:02:14Z",
):
    return KafkaEventEnvelope(
        event_id="evt-003",
        event_type=event_type,
        bank_id=bank_id,
        schema_version="1.0",
        payload={
            "outcome": outcome,
            "signatures_loaded": signatures_loaded,
            "pps_records_loaded": pps_records_loaded,
            "cheque_leaves_loaded": cheque_leaves_loaded,
            "integrity_check_passed": integrity_check_passed,
            "triggered_by": triggered_by,
            "started_at": started_at,
            "completed_at": completed_at,
        },
    )


class TestHandleVaultSyncEvent:

    @pytest.mark.asyncio
    async def test_sync_complete_writes_immudb(self):
        """SYNC_COMPLETE → Immudb write with VAULT_SYNC event type."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        envelope = _make_envelope()

        await handle_vault_sync_event(envelope, immudb=immudb)

        immudb.write_event.assert_awaited_once()
        call_kwargs = immudb.write_event.call_args[1]
        assert call_kwargs["event_type"] == "VAULT_SYNC"
        assert call_kwargs["bank_id"] == "saraswat-coop"

    @pytest.mark.asyncio
    async def test_partial_failure_writes_immudb_failed_type(self):
        """PARTIAL_FAILURE outcome → Immudb write with VAULT_SYNC_FAILED event type."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        envelope = _make_envelope(
            event_type="CTS_VAULT_SYNC_COMPLETE",
            outcome="PARTIAL_FAILURE",
        )

        await handle_vault_sync_event(envelope, immudb=immudb)

        call_kwargs = immudb.write_event.call_args[1]
        assert call_kwargs["event_type"] == "VAULT_SYNC_FAILED"

    @pytest.mark.asyncio
    async def test_immudb_payload_contains_all_stats(self):
        """Immudb payload captures signatures, pps, cheque_leaves, timing."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        envelope = _make_envelope(
            signatures_loaded=1200,
            pps_records_loaded=340,
            cheque_leaves_loaded=850,
            started_at="2026-08-03T06:00:00Z",
            completed_at="2026-08-03T06:02:14Z",
            triggered_by="SCHEDULED",
        )

        await handle_vault_sync_event(envelope, immudb=immudb)

        payload = immudb.write_event.call_args[1]["payload"]
        assert payload["signatures_loaded"] == 1200
        assert payload["pps_records_loaded"] == 340
        assert payload["cheque_leaves_loaded"] == 850
        assert payload["started_at"] == "2026-08-03T06:00:00Z"
        assert payload["completed_at"] == "2026-08-03T06:02:14Z"
        assert payload["triggered_by"] == "SCHEDULED"

    @pytest.mark.asyncio
    async def test_wrong_bank_id_skipped(self):
        """Envelope bank_id != consumer's bank_id → no Immudb write."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        envelope = _make_envelope(bank_id="other-bank")

        await handle_vault_sync_event(
            envelope, immudb=immudb, consumer_bank_id="saraswat-coop"
        )

        immudb.write_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_immudb_unavailable_does_not_crash(self):
        """Immudb=None → logs warning, returns cleanly."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        envelope = _make_envelope()

        await handle_vault_sync_event(envelope, immudb=None)

    @pytest.mark.asyncio
    async def test_immudb_error_does_not_crash(self):
        """Immudb write failure → logs error, does not crash consumer."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        immudb.write_event.side_effect = RuntimeError("immudb unreachable")
        envelope = _make_envelope()

        await handle_vault_sync_event(envelope, immudb=immudb)

    @pytest.mark.asyncio
    async def test_integrity_check_failure_captured(self):
        """integrity_check_passed=False is captured in payload."""
        from modules.cts.consumers.vault_sync_consumer import handle_vault_sync_event

        immudb = AsyncMock()
        envelope = _make_envelope(integrity_check_passed=False, outcome="PARTIAL_FAILURE")

        await handle_vault_sync_event(envelope, immudb=immudb)

        payload = immudb.write_event.call_args[1]["payload"]
        assert payload["integrity_check_passed"] is False
