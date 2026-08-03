"""
Tests for apps/eeh/sse.py — EEH SSE Publisher.

The SSE status feed uses Redis Pub/Sub. The EEH service publishes cheque-ack and
mismatch-hold events to a per-branch channel; the FastAPI SSE endpoint subscribes
and streams them to the branch portal browser client.

TDD: confirm RED before implementation.
"""
import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_sse_publisher_importable():
    from apps.eeh.sse import SSEPublisher


def test_sse_channel_key_importable():
    from apps.eeh.sse import sse_channel_key


def test_branch_sse_stream_importable():
    from apps.eeh.sse import branch_sse_stream


# ── 2. Channel key helper ─────────────────────────────────────────────────────

def test_sse_channel_key_format():
    from apps.eeh.sse import sse_channel_key
    key = sse_channel_key("branch-01", date(2026, 7, 5))
    assert key == "eeh:sse:branch-01:2026-07-05"


def test_sse_channel_key_different_branches():
    from apps.eeh.sse import sse_channel_key
    k1 = sse_channel_key("b1", date(2026, 7, 5))
    k2 = sse_channel_key("b2", date(2026, 7, 5))
    assert k1 != k2


def test_sse_channel_key_different_dates():
    from apps.eeh.sse import sse_channel_key
    k1 = sse_channel_key("b1", date(2026, 7, 5))
    k2 = sse_channel_key("b1", date(2026, 7, 6))
    assert k1 != k2


# ── 3. SSEPublisher ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_cheque_ack_calls_redis_publish():
    from apps.eeh.sse import SSEPublisher

    mock_redis = AsyncMock()
    publisher = SSEPublisher(redis=mock_redis)

    await publisher.publish_cheque_ack(
        branch_id="branch-01",
        clearing_date=date(2026, 7, 5),
        ack={"scan_id": "SC-001", "status": "ACCEPTED", "lot_id": "LOT-07"},
    )

    mock_redis.publish.assert_awaited_once()
    call_args = mock_redis.publish.await_args
    channel = call_args[0][0]
    message = call_args[0][1]
    assert "eeh:sse:branch-01:2026-07-05" == channel
    payload = json.loads(message)
    assert payload["type"] == "CHEQUE_ACK"
    assert payload["data"]["scan_id"] == "SC-001"


@pytest.mark.asyncio
async def test_publish_mismatch_hold_calls_redis_publish():
    from apps.eeh.sse import SSEPublisher

    mock_redis = AsyncMock()
    publisher = SSEPublisher(redis=mock_redis)

    await publisher.publish_mismatch_hold(
        branch_id="branch-01",
        clearing_date=date(2026, 7, 5),
        item={"mismatch_id": "MM-001", "mismatch_fields": ["amount_figures"]},
    )

    mock_redis.publish.assert_awaited_once()
    call_args = mock_redis.publish.await_args
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "MISMATCH_HOLD"
    assert payload["data"]["mismatch_id"] == "MM-001"


@pytest.mark.asyncio
async def test_publish_lot_sealed_calls_redis_publish():
    from apps.eeh.sse import SSEPublisher

    mock_redis = AsyncMock()
    publisher = SSEPublisher(redis=mock_redis)

    await publisher.publish_lot_sealed(
        branch_id="b1",
        clearing_date=date(2026, 7, 5),
        lot_id="LOT-07",
        instrument_count=42,
    )

    mock_redis.publish.assert_awaited_once()
    payload = json.loads(mock_redis.publish.await_args[0][1])
    assert payload["type"] == "LOT_SEALED"
    assert payload["data"]["lot_id"] == "LOT-07"
    assert payload["data"]["instrument_count"] == 42


# ── 4. SSE payload format ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_payload_contains_timestamp():
    from apps.eeh.sse import SSEPublisher

    mock_redis = AsyncMock()
    publisher = SSEPublisher(redis=mock_redis)

    await publisher.publish_cheque_ack(
        branch_id="b1",
        clearing_date=date(2026, 7, 5),
        ack={"scan_id": "SC-001", "status": "ACCEPTED"},
    )

    payload = json.loads(mock_redis.publish.await_args[0][1])
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_sse_payload_contains_branch_id():
    from apps.eeh.sse import SSEPublisher

    mock_redis = AsyncMock()
    publisher = SSEPublisher(redis=mock_redis)

    await publisher.publish_cheque_ack(
        branch_id="branch-99",
        clearing_date=date(2026, 7, 5),
        ack={"scan_id": "SC-001", "status": "ACCEPTED"},
    )

    payload = json.loads(mock_redis.publish.await_args[0][1])
    assert payload["branch_id"] == "branch-99"


# ── 5. SSE format_as_sse helper ───────────────────────────────────────────────

def test_format_as_sse_basic():
    from apps.eeh.sse import format_as_sse
    event = format_as_sse(data={"msg": "hello"}, event_type="CHEQUE_ACK")
    assert event.startswith("event: CHEQUE_ACK\n")
    assert "data:" in event
    assert event.endswith("\n\n")


def test_format_as_sse_data_is_json():
    from apps.eeh.sse import format_as_sse
    event = format_as_sse(data={"count": 5}, event_type="LOT_SEALED")
    # Extract data line
    for line in event.split("\n"):
        if line.startswith("data:"):
            parsed = json.loads(line[len("data:"):].strip())
            assert parsed["count"] == 5
            break
    else:
        pytest.fail("No data: line in SSE event")
