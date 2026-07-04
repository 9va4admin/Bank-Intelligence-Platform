"""
CTS Drop-Folder File Watcher.

Monitors the configured drop folder for new metadata files written by OEM scanner
software. When a new file appears and is stable (size unchanged for
stability_wait_seconds), it is processed through ScannerDropFolderMapper and the
resulting ScannedChequeInput records are published to Kafka as a BatchScannedEvent.

File lifecycle:
  drop_folder/batch.dat  →  mapper parses  →  Kafka publish
                         →  move to processed/ (success)
                         →  move to error/     (ScannerMappingError or Kafka failure)

The watcher never raises — all failures are logged and the file is quarantined in
error/. This guarantees the watchdog loop never dies due to a single bad batch.

Integration points:
  - Called by EEH service (Phase 2) which runs one DropFolderWatcher per branch
  - Kafka producer injected at startup (from app.state.kafka_producer_cts)
  - CRLService injected to validate branch→PU routing before publish
"""
from __future__ import annotations

import json
import shutil
import structlog
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from modules.cts.scanner.mapper import (
    ScannedChequeInput,
    ScannerDropFolderMapper,
    ScannerMappingError,
    ScannerOEM,
)

log = structlog.get_logger()


# ── File stability ─────────────────────────────────────────────────────────────

def is_file_stable(path: Path, *, prior_size: int) -> bool:
    """
    Returns True if the file exists and its current size matches prior_size.

    Callers poll twice (sleep stability_wait_seconds between polls).
    A stable file has the same size both times — OEM software has finished writing.
    """
    try:
        current_size = path.stat().st_size
        return current_size == prior_size
    except (FileNotFoundError, OSError):
        return False


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class WatcherConfig:
    """Per-branch watcher configuration. One DropFolderWatcher per branch."""

    bank_id:                  str
    branch_id:                str
    pu_id:                    str
    drop_folder:              Path
    metadata_glob:            str          # e.g. "*.dat", "*.csv", "*.xml"
    stability_wait_seconds:   int          # seconds to wait before declaring file stable
    kafka_topic:              str          # cts.outward.scanned.{bank_id}.{pu_id}
    archive_dir:              Optional[Path] = None   # defaults to drop_folder/processed
    error_dir:                Optional[Path] = None   # defaults to drop_folder/error

    def __post_init__(self) -> None:
        if self.archive_dir is None:
            self.archive_dir = self.drop_folder / "processed"
        if self.error_dir is None:
            self.error_dir = self.drop_folder / "error"


# ── Kafka event ────────────────────────────────────────────────────────────────

@dataclass
class BatchScannedEvent:
    """
    Kafka event published to cts.outward.scanned.{bank_id}.{pu_id} when a batch
    of scanned cheques is ready for OutwardScanWorkflow processing.

    Contains only routing metadata and scan IDs — never raw MICR or account numbers.
    Kafka consumers use scan_ids to look up full ScannedChequeInput records from
    the processing state store (Redis or YugabyteDB staging table).

    schema_version: "1.0" — increment on breaking payload changes (see api-versioning.md).
    """

    event_id:          str
    bank_id:           str
    branch_id:         str
    pu_id:             str
    batch_id:          str
    instrument_count:  int
    kafka_topic:       str
    scan_ids:          list[str]
    oem:               ScannerOEM
    scanned_at:        datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_kafka_payload(self) -> str:
        return json.dumps({
            "schema_version": "1.0",
            "event_id": self.event_id,
            "bank_id": self.bank_id,
            "branch_id": self.branch_id,
            "pu_id": self.pu_id,
            "batch_id": self.batch_id,
            "instrument_count": self.instrument_count,
            "scan_ids": self.scan_ids,
            "oem": self.oem.value,
            "scanned_at": self.scanned_at.isoformat(),
        })


# ── Watcher ────────────────────────────────────────────────────────────────────

class DropFolderWatcher:
    """
    Monitors one branch drop folder and processes new metadata files.

    Usage:
        watcher = DropFolderWatcher(config, mapper, kafka_producer)
        # In watchdog event loop:
        await watcher.process_file(path_to_new_file)
    """

    def __init__(
        self,
        *,
        config: WatcherConfig,
        mapper: ScannerDropFolderMapper,
        kafka_producer: Any,
    ) -> None:
        self._cfg = config
        self._mapper = mapper
        self._kafka = kafka_producer

    # ── Public: skip check ────────────────────────────────────────────────────

    def should_skip(self, path: Path) -> bool:
        """Return True if the file is inside a managed subdirectory (processed/, error/)."""
        try:
            path.relative_to(self._cfg.archive_dir)
            return True
        except ValueError:
            pass
        try:
            path.relative_to(self._cfg.error_dir)
            return True
        except ValueError:
            pass
        return False

    # ── Public: process one file ──────────────────────────────────────────────

    async def process_file(self, metadata_path: Path) -> None:
        """
        Process a single metadata file from the drop folder.

        1. Call mapper → list[ScannedChequeInput]
        2. If instruments found → publish BatchScannedEvent to Kafka
        3. Move file to archive_dir on success, error_dir on any failure
        4. Never raise — all failures are quarantined and logged.
        """
        self._ensure_dirs()

        try:
            instruments = self._mapper.parse_metadata_file(metadata_path)
        except ScannerMappingError as exc:
            log.error(
                "drop_folder.mapper_failed",
                file=str(metadata_path),
                branch_id=self._cfg.branch_id,
                error=str(exc),
            )
            self._quarantine(metadata_path)
            return
        except Exception as exc:
            log.error(
                "drop_folder.unexpected_error",
                file=str(metadata_path),
                branch_id=self._cfg.branch_id,
                error=str(exc),
            )
            self._quarantine(metadata_path)
            return

        if instruments:
            try:
                await self._publish(instruments, metadata_path)
            except Exception as exc:
                log.error(
                    "drop_folder.kafka_failed",
                    file=str(metadata_path),
                    branch_id=self._cfg.branch_id,
                    instrument_count=len(instruments),
                    error=str(exc),
                )
                self._quarantine(metadata_path)
                return

        self._archive(metadata_path)
        log.info(
            "drop_folder.processed",
            file=str(metadata_path),
            branch_id=self._cfg.branch_id,
            instrument_count=len(instruments),
        )

    # ── Internal: publish ─────────────────────────────────────────────────────

    async def _publish(
        self,
        instruments: list[ScannedChequeInput],
        source_path: Path,
    ) -> None:
        batch_id = instruments[0].batch_id if instruments else source_path.stem
        event = BatchScannedEvent(
            event_id=f"BSE-{uuid.uuid4().hex[:12].upper()}",
            bank_id=self._cfg.bank_id,
            branch_id=self._cfg.branch_id,
            pu_id=self._cfg.pu_id,
            batch_id=batch_id,
            instrument_count=len(instruments),
            kafka_topic=self._cfg.kafka_topic,
            scan_ids=[i.scan_id for i in instruments],
            oem=instruments[0].oem if instruments else ScannerOEM.GENERIC,
        )
        await self._kafka.send(
            self._cfg.kafka_topic,
            value=event.to_kafka_payload().encode("utf-8"),
            key=f"{self._cfg.bank_id}:{self._cfg.branch_id}".encode("utf-8"),
        )

    # ── Internal: file management ─────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        self._cfg.archive_dir.mkdir(parents=True, exist_ok=True)
        self._cfg.error_dir.mkdir(parents=True, exist_ok=True)

    def _archive(self, path: Path) -> None:
        dest = self._cfg.archive_dir / path.name
        shutil.move(str(path), str(dest))

    def _quarantine(self, path: Path) -> None:
        self._ensure_dirs()
        try:
            dest = self._cfg.error_dir / path.name
            shutil.move(str(path), str(dest))
        except Exception as exc:
            log.error("drop_folder.quarantine_failed", file=str(path), error=str(exc))
