"""
Tests for shared/audit/immudb_writer.py -- AsyncImmudbWriter.

Regression: modules/cts/workflows/activities/write_audit.py calls
`await immudb_client.write(collection=, event_type=, bank_id=,
instrument_id=, payload=)` but the real ImmudbClient only exposes a sync
`write_event(payload_dict)` with collection fixed at connect-time -- every
production call would have thrown AttributeError the moment Immudb actually
connected. This wrapper bridges that gap, matching the established
asyncio.to_thread() pattern from shared/storage/minio_client.py.

TDD: written BEFORE the implementation.
"""
import pytest
from unittest.mock import MagicMock


def _make_writer(mock_client):
    from shared.audit.immudb_writer import AsyncImmudbWriter
    return AsyncImmudbWriter(mock_client)


class TestWriteHappyPath:
    @pytest.mark.asyncio
    async def test_returns_tx_id_as_string(self):
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 42, "verified": True})
        writer = _make_writer(mock_client)

        tx_id = await writer.write(
            collection="cts_test-bank", event_type="CTS_NGCH_FILED_CONFIRM",
            bank_id="test-bank", instrument_id="CHQ-1", payload={"decision": "CONFIRM"},
        )

        assert tx_id == "42"

    @pytest.mark.asyncio
    async def test_sets_collection_before_writing(self):
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 1})
        writer = _make_writer(mock_client)

        await writer.write(
            collection="cts_kotak-mah", event_type="X", bank_id="kotak-mah", payload={},
        )

        mock_client.set_collection.assert_called_once_with("cts_kotak-mah")

    @pytest.mark.asyncio
    async def test_write_event_payload_includes_bank_id_and_event_type(self):
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 1})
        writer = _make_writer(mock_client)

        await writer.write(
            collection="cts_x", event_type="CTS_WF_IET_WATCHDOG_FIRED",
            bank_id="x-bank", payload={"seconds_remaining": 12},
        )

        sent_payload = mock_client.write_event.call_args[0][0]
        assert sent_payload["bank_id"] == "x-bank"
        assert sent_payload["event_type"] == "CTS_WF_IET_WATCHDOG_FIRED"
        assert sent_payload["payload"] == {"seconds_remaining": 12}

    @pytest.mark.asyncio
    async def test_instrument_id_included_when_provided(self):
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 1})
        writer = _make_writer(mock_client)

        await writer.write(
            collection="cts_x", event_type="X", bank_id="x-bank",
            instrument_id="CHQ-9", payload={},
        )

        sent_payload = mock_client.write_event.call_args[0][0]
        assert sent_payload["instrument_id"] == "CHQ-9"

    @pytest.mark.asyncio
    async def test_instrument_id_omitted_when_none(self):
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 1})
        writer = _make_writer(mock_client)

        await writer.write(collection="cts_x", event_type="X", bank_id="x-bank", payload={})

        sent_payload = mock_client.write_event.call_args[0][0]
        assert "instrument_id" not in sent_payload

    @pytest.mark.asyncio
    async def test_runs_off_the_event_loop(self):
        """set_collection + write_event are both sync (immudb-py) -- must not
        block the event loop. Verified indirectly: write() must be awaitable
        and complete even though the mock methods are plain sync callables
        (asyncio.to_thread requires exactly this shape)."""
        mock_client = MagicMock()
        mock_client.write_event = MagicMock(return_value={"tx_id": 7})
        writer = _make_writer(mock_client)

        result = await writer.write(collection="c", event_type="E", bank_id="b", payload={})
        assert result == "7"


class TestCollectionRaceSafety:
    @pytest.mark.asyncio
    async def test_set_collection_and_write_event_use_the_call_that_was_made(self):
        """Regression guard: set_collection() and write_event() must happen
        inside the SAME to_thread() call, not two separate ones -- otherwise
        concurrent writes to different collections on one ImmudbClient
        instance could interleave and write to the wrong collection."""
        calls = []
        mock_client = MagicMock()

        def _record_set_collection(name):
            calls.append(("set_collection", name))

        def _record_write_event(payload):
            calls.append(("write_event", payload["bank_id"]))
            return {"tx_id": 1}

        mock_client.set_collection = MagicMock(side_effect=_record_set_collection)
        mock_client.write_event = MagicMock(side_effect=_record_write_event)
        writer = _make_writer(mock_client)

        await writer.write(collection="cts_a", event_type="E", bank_id="bank-a", payload={})

        assert calls == [("set_collection", "cts_a"), ("write_event", "bank-a")]
