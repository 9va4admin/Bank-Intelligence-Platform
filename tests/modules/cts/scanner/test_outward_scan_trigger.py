"""
Tests for modules/cts/scanner/outward_scan_trigger.py — Kafka → OutwardScanWorkflow trigger.

Polls cts.outward.scanned.{bank_id}, parses BatchScannedEvent, and starts
OutwardScanWorkflow for each scan in per_scan_data.

TDD: confirm RED before implementation.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_outward_scan_trigger_importable():
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger


# ── 2. Construction ───────────────────────────────────────────────────────────

def test_outward_scan_trigger_constructs():
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger
    mock_client = AsyncMock()
    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_client,
        task_queue="cts-processing-sb1",
    )
    assert trigger is not None


# ── 3. Message handling ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_starts_workflow_for_each_scan_in_event():
    """One start_workflow call per scan in per_scan_data."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_temporal_client = AsyncMock()
    mock_temporal_client.start_workflow = AsyncMock()

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    event_payload = json.dumps({
        "schema_version": "1.0",
        "event_id": "EVT-001",
        "bank_id": "sb1",
        "branch_id": "b1",
        "pu_id": "pu1",
        "batch_id": "batch001",
        "instrument_count": 2,
        "scan_ids": ["S1", "S2"],
        "oem": "PANINI",
        "scanned_at": "2026-07-19T10:00:00+00:00",
        "per_scan_data": [
            {
                "scan_id": "S1",
                "image_front_url": "minio://cts-cheques/sb1/outward/S1/front.tif",
                "image_rear_url": "minio://cts-cheques/sb1/outward/S1/rear.tif",
            },
            {
                "scan_id": "S2",
                "image_front_url": "minio://cts-cheques/sb1/outward/S2/front.tif",
                "image_rear_url": "minio://cts-cheques/sb1/outward/S2/rear.tif",
            },
        ],
    }).encode("utf-8")

    mock_message = MagicMock()
    mock_message.value = event_payload

    await trigger._handle_message(mock_message)

    assert mock_temporal_client.start_workflow.await_count == 2


@pytest.mark.asyncio
async def test_trigger_skips_event_for_wrong_bank_id():
    """Events for other banks must be silently dropped."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_temporal_client = AsyncMock()

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    event_payload = json.dumps({
        "schema_version": "1.0",
        "event_id": "EVT-002",
        "bank_id": "wrong-bank",
        "branch_id": "b1",
        "pu_id": "pu1",
        "batch_id": "batch001",
        "scan_ids": ["S1"],
        "per_scan_data": [{"scan_id": "S1"}],
    }).encode("utf-8")

    mock_message = MagicMock()
    mock_message.value = event_payload

    await trigger._handle_message(mock_message)

    mock_temporal_client.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_handles_malformed_json_without_crashing():
    """A corrupt Kafka message must be logged and skipped, not crash the poll loop."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_temporal_client = AsyncMock()

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    mock_message = MagicMock()
    mock_message.value = b"NOT VALID JSON {"

    await trigger._handle_message(mock_message)

    mock_temporal_client.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_handles_empty_per_scan_data():
    """Legacy event without per_scan_data field must not start any workflows."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_temporal_client = AsyncMock()

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    event_payload = json.dumps({
        "schema_version": "1.0",
        "event_id": "EVT-003",
        "bank_id": "sb1",
        "batch_id": "batch001",
        "scan_ids": ["S1"],
        # per_scan_data intentionally absent — legacy v1.0 event
    }).encode("utf-8")

    mock_message = MagicMock()
    mock_message.value = event_payload

    await trigger._handle_message(mock_message)

    mock_temporal_client.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_workflow_start_failure_does_not_crash_loop():
    """If start_workflow fails for one scan, loop continues to next scan."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_temporal_client = AsyncMock()
    # First call fails, second succeeds
    mock_temporal_client.start_workflow = AsyncMock(
        side_effect=[Exception("Temporal unreachable"), None]
    )

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    event_payload = json.dumps({
        "schema_version": "1.0",
        "event_id": "EVT-004",
        "bank_id": "sb1",
        "batch_id": "batch004",
        "per_scan_data": [
            {"scan_id": "S1", "image_front_url": "minio://bucket/S1/front.tif"},
            {"scan_id": "S2", "image_front_url": "minio://bucket/S2/front.tif"},
        ],
    }).encode("utf-8")

    mock_message = MagicMock()
    mock_message.value = event_payload

    # Must not raise even when first workflow start fails
    await trigger._handle_message(mock_message)

    # Both scans attempted
    assert mock_temporal_client.start_workflow.await_count == 2


@pytest.mark.asyncio
async def test_trigger_uses_deterministic_workflow_id_with_pu_id():
    """Workflow ID follows cts-outscan-{bank_id}-{pu_id}-{scan_id} pattern."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    workflow_ids_used = []

    async def capture_workflow_id(*args, **kwargs):
        workflow_ids_used.append(kwargs.get("id", args[1] if len(args) > 1 else ""))

    mock_temporal_client = AsyncMock()
    mock_temporal_client.start_workflow = AsyncMock(side_effect=capture_workflow_id)

    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_temporal_client,
        task_queue="cts-processing-sb1",
    )

    event_payload = json.dumps({
        "schema_version": "1.0",
        "event_id": "EVT-005",
        "bank_id": "sb1",
        "branch_id": "b1",
        "pu_id": "pu1",
        "batch_id": "batch005",
        "per_scan_data": [
            {"scan_id": "S5", "image_front_url": "minio://bucket/S5/front.tif"},
        ],
    }).encode("utf-8")

    mock_message = MagicMock()
    mock_message.value = event_payload

    await trigger._handle_message(mock_message)

    assert len(workflow_ids_used) == 1
    assert "sb1" in workflow_ids_used[0]
    assert "S5" in workflow_ids_used[0]


# ── 4. stop() lifecycle ───────────────────────────────────────────────────────

def test_trigger_stop_sets_stop_event():
    """stop() must mark the trigger as stopped so the poll loop exits."""
    from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger

    mock_client = AsyncMock()
    trigger = OutwardScanTrigger(
        bank_id="sb1",
        bootstrap_servers="localhost:9092",
        temporal_client=mock_client,
        task_queue="cts-processing-sb1",
    )

    assert not trigger._stop.is_set()
    trigger.stop()
    assert trigger._stop.is_set()
