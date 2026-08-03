"""
Tests for modules/cts/scanner/file_watcher.py — Drop-Folder File Watcher.

The file watcher monitors configured drop folders, detects stable new metadata
files, calls ScannerDropFolderMapper, and publishes ScannedChequeInput events
to Kafka cts.outward.scanned.{bank_id}.{pu_id}.

TDD: confirm RED before implementation.
"""

import asyncio
import json
import pytest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
from dataclasses import dataclass


# ── 1. Import guard ───────────────────────────────────────────────────────────

def test_file_watcher_importable():
    from modules.cts.scanner.file_watcher import DropFolderWatcher


def test_batch_event_importable():
    from modules.cts.scanner.file_watcher import BatchScannedEvent


def test_watcher_config_importable():
    from modules.cts.scanner.file_watcher import WatcherConfig


def test_file_stability_checker_importable():
    from modules.cts.scanner.file_watcher import is_file_stable


# ── 2. WatcherConfig ─────────────────────────────────────────────────────────

def test_watcher_config_has_required_fields():
    from modules.cts.scanner.file_watcher import WatcherConfig
    cfg = WatcherConfig(
        bank_id="saraswat",
        branch_id="branch-01",
        pu_id="PU-MUMBAI-01",
        drop_folder=Path("/drop/branch-01"),
        metadata_glob="*.dat",
        stability_wait_seconds=2,
        kafka_topic="cts.outward.scanned.saraswat.PU-MUMBAI-01",
    )
    assert cfg.bank_id == "saraswat"
    assert cfg.kafka_topic == "cts.outward.scanned.saraswat.PU-MUMBAI-01"


def test_watcher_config_archive_dir_defaults_to_drop_subfolder():
    from modules.cts.scanner.file_watcher import WatcherConfig
    cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=Path("/drop/b1"),
        metadata_glob="*.dat",
        stability_wait_seconds=2,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )
    # Default archive dir = drop_folder / "processed"
    assert cfg.archive_dir == Path("/drop/b1/processed")


def test_watcher_config_error_dir_defaults_to_drop_subfolder():
    from modules.cts.scanner.file_watcher import WatcherConfig
    cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=Path("/drop/b1"),
        metadata_glob="*.dat",
        stability_wait_seconds=2,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )
    assert cfg.error_dir == Path("/drop/b1/error")


def test_watcher_config_custom_archive_dir():
    from modules.cts.scanner.file_watcher import WatcherConfig
    cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=Path("/drop/b1"),
        metadata_glob="*.dat",
        stability_wait_seconds=2,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        archive_dir=Path("/archive/b1"),
    )
    assert cfg.archive_dir == Path("/archive/b1")


# ── 3. File stability ─────────────────────────────────────────────────────────

def test_file_stable_if_size_unchanged(tmp_path):
    from modules.cts.scanner.file_watcher import is_file_stable
    f = tmp_path / "batch.dat"
    f.write_text("data", encoding="utf-8")
    # Simulate two reads with same size → stable
    assert is_file_stable(f, prior_size=4) is True


def test_file_not_stable_if_size_changed(tmp_path):
    from modules.cts.scanner.file_watcher import is_file_stable
    f = tmp_path / "batch.dat"
    f.write_text("data", encoding="utf-8")
    # Prior size was 0 → file is still being written
    assert is_file_stable(f, prior_size=0) is False


def test_file_not_stable_if_not_exists(tmp_path):
    from modules.cts.scanner.file_watcher import is_file_stable
    missing = tmp_path / "ghost.dat"
    assert is_file_stable(missing, prior_size=0) is False


# ── 4. BatchScannedEvent ─────────────────────────────────────────────────────

def test_batch_scanned_event_has_required_fields():
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM
    evt = BatchScannedEvent(
        event_id="EVT-001",
        bank_id="sb1",
        branch_id="b1",
        pu_id="pu1",
        batch_id="BATCH20260705001",
        instrument_count=5,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["SCAN-001", "SCAN-002"],
        oem=ScannerOEM.PANINI,
    )
    assert evt.instrument_count == 5
    assert len(evt.scan_ids) == 2


def test_batch_scanned_event_serialises_to_kafka_payload():
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM
    evt = BatchScannedEvent(
        event_id="EVT-001",
        bank_id="sb1",
        branch_id="b1",
        pu_id="pu1",
        batch_id="BATCH001",
        instrument_count=2,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["S1", "S2"],
        oem=ScannerOEM.MAGTEK,
    )
    payload = evt.to_kafka_payload()
    data = json.loads(payload)
    assert data["event_id"] == "EVT-001"
    assert data["bank_id"] == "sb1"
    assert data["instrument_count"] == 2
    assert data["schema_version"] == "1.0"


# ── 5. DropFolderWatcher — core processing ───────────────────────────────────

@pytest.mark.asyncio
async def test_process_file_calls_mapper(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannerOEM, ScannerConfig

    drop = tmp_path / "drop"
    drop.mkdir()
    metadata_file = drop / "batch001.dat"
    metadata_file.write_text("header\ndata", encoding="utf-8")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop,
        metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[])  # empty batch
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg,
        mapper=mock_mapper,
        kafka_producer=mock_kafka,
    )
    await watcher.process_file(metadata_file)

    mock_mapper.parse_metadata_file.assert_called_once_with(metadata_file)


@pytest.mark.asyncio
async def test_process_file_publishes_to_kafka_when_cheques_found(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannedChequeInput, ScannerOEM
    from datetime import datetime, timezone

    drop = tmp_path / "drop"
    drop.mkdir()
    f = drop / "batch001.dat"
    f.write_text("x", encoding="utf-8")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop,
        metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )

    # Simulate mapper returning 2 cheques
    cheque = ScannedChequeInput(
        scan_id="SCAN-001", branch_id="b1", oem=ScannerOEM.PANINI,
        scanner_model="Vision X", micr_line="0001234000019876543210",
        account_number_hash="abc123", account_suffix="3210",
        amount_figures=Decimal("10000.00"), amount_words="Ten thousand",
        payee_masked="R***", cheque_date=date(2026, 7, 5),
        image_color_path=drop / "img.tif", image_grey_path=drop / "img.tif",
        image_rear_path=drop / "img.tif",
        scan_timestamp=datetime.now(tz=timezone.utc),
        batch_id="batch001", sequence_in_batch=1,
        oem_confidence=None,
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[cheque, cheque])
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg,
        mapper=mock_mapper,
        kafka_producer=mock_kafka,
    )
    await watcher.process_file(f)

    mock_kafka.send.assert_awaited_once()
    call_args = mock_kafka.send.await_args
    assert call_args[0][0] == "cts.outward.scanned.sb1.pu1"


@pytest.mark.asyncio
async def test_process_file_archives_on_success(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig

    drop = tmp_path / "drop"
    drop.mkdir()
    archive = tmp_path / "archive"
    f = drop / "batch002.dat"
    f.write_text("x", encoding="utf-8")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop,
        metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        archive_dir=archive,
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[])
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg,
        mapper=mock_mapper,
        kafka_producer=mock_kafka,
    )
    await watcher.process_file(f)

    # File must be moved to archive dir
    assert not f.exists()
    assert (archive / "batch002.dat").exists()


@pytest.mark.asyncio
async def test_process_file_moves_to_error_on_mapper_failure(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannerMappingError

    drop = tmp_path / "drop"
    drop.mkdir()
    error_dir = tmp_path / "error"
    f = drop / "bad_batch.dat"
    f.write_text("corrupt", encoding="utf-8")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop,
        metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        error_dir=error_dir,
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(
        side_effect=ScannerMappingError("bad field")
    )
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg,
        mapper=mock_mapper,
        kafka_producer=mock_kafka,
    )
    # Must NOT raise — moves file to error dir and logs
    await watcher.process_file(f)

    assert not f.exists()
    assert (error_dir / "bad_batch.dat").exists()
    mock_kafka.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_file_does_not_raise_on_kafka_failure(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannedChequeInput, ScannerOEM
    from datetime import datetime, timezone

    drop = tmp_path / "drop"
    drop.mkdir()
    f = drop / "batch003.dat"
    f.write_text("x", encoding="utf-8")

    cheque = ScannedChequeInput(
        scan_id="S1", branch_id="b1", oem=ScannerOEM.GENERIC,
        scanner_model="generic", micr_line="0001234",
        account_number_hash="h1", account_suffix="1234",
        amount_figures=Decimal("1000"), amount_words="One thousand",
        payee_masked="A***", cheque_date=date(2026, 7, 5),
        image_color_path=drop / "i.tif", image_grey_path=drop / "i.tif",
        image_rear_path=drop / "i.tif",
        scan_timestamp=datetime.now(tz=timezone.utc),
        batch_id="b003", sequence_in_batch=1, oem_confidence=None,
    )

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop, metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[cheque])
    mock_kafka = AsyncMock()
    mock_kafka.send = AsyncMock(side_effect=Exception("kafka broker down"))

    watcher = DropFolderWatcher(
        config=watcher_cfg, mapper=mock_mapper, kafka_producer=mock_kafka,
    )
    # Must not raise — file goes to error dir, Kafka failure is logged
    await watcher.process_file(f)


@pytest.mark.asyncio
async def test_skip_files_in_archive_and_error_subdirs(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig

    drop = tmp_path / "drop"
    drop.mkdir()

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop, metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )

    mock_mapper = MagicMock()
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(config=watcher_cfg, mapper=mock_mapper, kafka_producer=mock_kafka)

    # Files in processed/ and error/ subdirs must be ignored
    processed = drop / "processed"
    processed.mkdir()
    (processed / "old.dat").write_text("x", encoding="utf-8")

    error = drop / "error"
    error.mkdir()
    (error / "bad.dat").write_text("x", encoding="utf-8")

    assert watcher.should_skip(processed / "old.dat") is True
    assert watcher.should_skip(error / "bad.dat") is True


@pytest.mark.asyncio
async def test_should_not_skip_new_drop_file(tmp_path):
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig

    drop = tmp_path / "drop"
    drop.mkdir()
    f = drop / "batch004.dat"
    f.write_text("x", encoding="utf-8")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop, metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
    )

    watcher = DropFolderWatcher(
        config=watcher_cfg, mapper=MagicMock(), kafka_producer=AsyncMock()
    )
    assert watcher.should_skip(f) is False


# ── 6. Kafka payload schema_version ──────────────────────────────────────────

def test_kafka_payload_has_schema_version():
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM
    evt = BatchScannedEvent(
        event_id="E1", bank_id="sb1", branch_id="b1", pu_id="pu1",
        batch_id="B1", instrument_count=1,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["S1"], oem=ScannerOEM.DIGITAL_CHECK,
    )
    payload = json.loads(evt.to_kafka_payload())
    assert payload["schema_version"] == "1.0"
    assert "event_id" in payload
    assert "bank_id" in payload
    assert "pu_id" in payload


def test_kafka_payload_does_not_include_micr_or_account():
    """MICR lines and account numbers must never appear in Kafka event payloads."""
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM
    evt = BatchScannedEvent(
        event_id="E1", bank_id="sb1", branch_id="b1", pu_id="pu1",
        batch_id="B1", instrument_count=1,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["S1"], oem=ScannerOEM.DIGITAL_CHECK,
    )
    payload = evt.to_kafka_payload()
    assert "micr" not in payload.lower()
    assert "account_number" not in payload.lower()


# ── 7. MinIO image upload ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_file_uploads_images_to_minio_when_store_injected(tmp_path):
    """When minio_store is injected, drop folder watcher uploads cheque images."""
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannedChequeInput, ScannerOEM
    from datetime import datetime, timezone

    drop = tmp_path / "drop"
    drop.mkdir()
    img = drop / "scan001.tif"
    img.write_bytes(b"\x00\x01\x02\x03")  # dummy TIFF bytes

    f = drop / "batch005.dat"
    f.write_text("x", encoding="utf-8")

    cheque = ScannedChequeInput(
        scan_id="SCAN-MINIO-001", branch_id="b1", oem=ScannerOEM.PANINI,
        scanner_model="Vision X", micr_line="0001234000019876543210",
        account_number_hash="abc123", account_suffix="3210",
        amount_figures=Decimal("10000.00"), amount_words="Ten thousand",
        payee_masked="R***", cheque_date=date(2026, 7, 5),
        image_color_path=img, image_grey_path=img, image_rear_path=img,
        scan_timestamp=datetime.now(tz=timezone.utc),
        batch_id="batch005", sequence_in_batch=1, oem_confidence=None,
    )

    mock_minio = AsyncMock()
    mock_minio.upload_bytes = AsyncMock(return_value="some-key")

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop, metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        minio_store=mock_minio,
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[cheque])
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg,
        mapper=mock_mapper,
        kafka_producer=mock_kafka,
    )
    await watcher.process_file(f)

    # MinIO should be called at least once (front image minimum)
    assert mock_minio.upload_bytes.await_count >= 1


def test_batch_scanned_event_has_per_scan_data_field():
    """BatchScannedEvent must have a per_scan_data field for image URLs."""
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM

    evt = BatchScannedEvent(
        event_id="EVT-001", bank_id="sb1", branch_id="b1", pu_id="pu1",
        batch_id="BATCH001", instrument_count=1,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["S1"], oem=ScannerOEM.PANINI,
        per_scan_data=[{
            "scan_id": "S1",
            "image_front_url": "minio://cts-cheques/sb1/outward/S1/front.tif",
        }],
    )
    assert len(evt.per_scan_data) == 1
    assert evt.per_scan_data[0]["scan_id"] == "S1"


def test_batch_scanned_event_per_scan_data_in_kafka_payload():
    """per_scan_data must appear in the Kafka JSON payload."""
    from modules.cts.scanner.file_watcher import BatchScannedEvent
    from modules.cts.scanner.mapper import ScannerOEM

    evt = BatchScannedEvent(
        event_id="EVT-002", bank_id="sb1", branch_id="b1", pu_id="pu1",
        batch_id="BATCH002", instrument_count=1,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        scan_ids=["S2"], oem=ScannerOEM.MAGTEK,
        per_scan_data=[{
            "scan_id": "S2",
            "image_front_url": "minio://cts-cheques/sb1/outward/S2/front.tif",
            "image_rear_url": "minio://cts-cheques/sb1/outward/S2/rear.tif",
        }],
    )
    payload = json.loads(evt.to_kafka_payload())
    assert "per_scan_data" in payload
    assert payload["per_scan_data"][0]["image_front_url"] == "minio://cts-cheques/sb1/outward/S2/front.tif"


@pytest.mark.asyncio
async def test_process_file_degrades_gracefully_without_minio_store(tmp_path):
    """Without minio_store, Kafka publish still happens (no image URLs in per_scan_data)."""
    from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
    from modules.cts.scanner.mapper import ScannedChequeInput, ScannerOEM
    from datetime import datetime, timezone

    drop = tmp_path / "drop"
    drop.mkdir()
    img = drop / "scan002.tif"
    img.write_bytes(b"\x00\x01")
    f = drop / "batch006.dat"
    f.write_text("x", encoding="utf-8")

    cheque = ScannedChequeInput(
        scan_id="SCAN-NOMINIO-001", branch_id="b1", oem=ScannerOEM.PANINI,
        scanner_model="Vision X", micr_line="0001234000019876543210",
        account_number_hash="abc123", account_suffix="3210",
        amount_figures=Decimal("5000.00"), amount_words="Five thousand",
        payee_masked="A***", cheque_date=date(2026, 7, 5),
        image_color_path=img, image_grey_path=img, image_rear_path=img,
        scan_timestamp=datetime.now(tz=timezone.utc),
        batch_id="batch006", sequence_in_batch=1, oem_confidence=None,
    )

    watcher_cfg = WatcherConfig(
        bank_id="sb1", branch_id="b1", pu_id="pu1",
        drop_folder=drop, metadata_glob="*.dat",
        stability_wait_seconds=0,
        kafka_topic="cts.outward.scanned.sb1.pu1",
        # minio_store intentionally absent
    )

    mock_mapper = MagicMock()
    mock_mapper.parse_metadata_file = MagicMock(return_value=[cheque])
    mock_kafka = AsyncMock()

    watcher = DropFolderWatcher(
        config=watcher_cfg, mapper=mock_mapper, kafka_producer=mock_kafka,
    )
    await watcher.process_file(f)

    # Kafka publish still happened
    mock_kafka.send.assert_awaited_once()
    # per_scan_data in the event payload should still be present (no URLs)
    call_kwargs = mock_kafka.send.await_args
    payload = json.loads(call_kwargs[1]["value"].decode("utf-8"))
    assert "per_scan_data" in payload
