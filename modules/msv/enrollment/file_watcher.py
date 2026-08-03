"""
DropZoneHandler — watches the MSV drop-zone directory for new enrollment files.

Drop zone layout:
  /msv/dropzone/incoming/    ← scanner / CBS batch drops files here
  /msv/dropzone/processing/  ← atomic rename before processing (in-flight)
  /msv/dropzone/processed/   ← successful files archived here
  /msv/dropzone/failed/      ← failed files + {filename}.error.txt

Atomic rename guarantee:
  File is renamed incoming/ → processing/ BEFORE any processing begins.
  This ensures that a crash mid-way leaves the file in processing/ (orphan),
  which recover_orphans() re-processes at next startup.

_wait_stable(path):
  Polls file size at poll_interval seconds until unchanged for 2 consecutive reads.
  Prevents processing of a file that is still being written.

Supported file patterns (others silently ignored):
  signatories_bulk_YYYYMMDD.csv.gz       → full bulk enrollment
  signatories_delta_YYYYMMDD[_HHMM].csv.gz → incremental delta
  signatories_revocation_YYYYMMDD.csv.gz  → revocation (future use)

Security:
  No image bytes or raw account numbers are logged.
  All PII handling delegated to BulkEnrollmentProcessor → AccountEnroller → SignatoryRegistry.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.file_watcher")

_SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".gz"})
_STABLE_CHECK_COUNT = 2   # file size must match for this many consecutive checks
_DEFAULT_POLL_INTERVAL = 0.5  # seconds between size polls


class DropZoneHandler:
    """
    Handles new enrollment files arriving in the drop-zone.

    Lifecycle of a file:
      1. Caller (watchdog event / startup scan) calls handle_new_file(path)
      2. _wait_stable(): wait until file size stops changing
      3. Atomic rename: incoming/file.gz → processing/file.gz
      4. BulkEnrollmentProcessor.process_file()
      5a. Success: rename processing/file.gz → processed/file.gz.{timestamp}
      5b. Failure: rename processing/file.gz → failed/file.gz
                   write failed/file.gz.error.txt with traceback

    recover_orphans():
      Called at startup. Re-queues any file found in processing/ that was
      left there by a previous crashed session.
    """

    def __init__(
        self,
        incoming_dir: Path,
        processing_dir: Path,
        processed_dir: Path,
        failed_dir: Path,
        processor,        # BulkEnrollmentProcessor
        bank_id: str,
    ) -> None:
        self._incoming = incoming_dir
        self._processing = processing_dir
        self._processed = processed_dir
        self._failed = failed_dir
        self._processor = processor
        self._bank_id = bank_id

        # Ensure dirs exist
        for d in (incoming_dir, processing_dir, processed_dir, failed_dir):
            d.mkdir(parents=True, exist_ok=True)

    async def handle_new_file(self, incoming_path: Path) -> None:
        """
        Process a single file from the incoming/ directory.

        Silently ignores files that are not .gz (non-enrollment files).
        Never raises — errors result in the file going to failed/.
        """
        with tracer.start_as_current_span("msv.file_watcher.handle_new_file") as span:
            span.set_attribute("bank_id", self._bank_id)
            span.set_attribute("filename", incoming_path.name)

            # Ignore unsupported file types
            if incoming_path.suffix not in _SUPPORTED_SUFFIXES:
                log.debug(
                    "msv.file_watcher.ignored",
                    filename=incoming_path.name,
                    reason="unsupported_suffix",
                )
                return

            # Wait until file size is stable (not still being written)
            if incoming_path.exists():
                await self._wait_stable(incoming_path)

            # Atomic rename: incoming/ → processing/
            processing_path = self._processing / incoming_path.name
            try:
                incoming_path.rename(processing_path)
            except FileNotFoundError:
                # Another worker picked it up between the exists() check and rename
                log.warning(
                    "msv.file_watcher.race_condition",
                    filename=incoming_path.name,
                    bank_id=self._bank_id,
                )
                return

            log.info(
                "msv.file_watcher.processing_started",
                filename=processing_path.name,
                bank_id=self._bank_id,
            )

            job_id = f"msv-job-{uuid.uuid4().hex[:12]}"
            span.set_attribute("job_id", job_id)

            try:
                await self._processor.process_file(
                    processing_path, self._bank_id, job_id
                )

                # Success → move to processed/ with timestamp suffix
                timestamp = int(time.time())
                final_name = f"{incoming_path.name}.{timestamp}"
                processed_path = self._processed / final_name
                processing_path.rename(processed_path)

                log.info(
                    "msv.file_watcher.processing_complete",
                    filename=incoming_path.name,
                    job_id=job_id,
                    bank_id=self._bank_id,
                    archive=str(processed_path),
                )
                span.set_attribute("outcome", "SUCCESS")

            except Exception as exc:
                # Failure → move to failed/ + write .error.txt
                self._handle_failure(processing_path, exc, job_id)
                span.set_attribute("outcome", "FAILED")
                span.set_attribute("error", str(exc))

    def _handle_failure(self, processing_path: Path, exc: Exception, job_id: str) -> None:
        """Move file to failed/ and write accompanying .error.txt."""
        timestamp = int(time.time())
        failed_data = self._failed / processing_path.name
        failed_error = self._failed / f"{processing_path.name}.{timestamp}.error.txt"

        try:
            processing_path.rename(failed_data)
        except Exception as rename_exc:
            log.error(
                "msv.file_watcher.failed_rename_error",
                filename=processing_path.name,
                error=str(rename_exc),
            )

        try:
            error_text = (
                f"job_id: {job_id}\n"
                f"bank_id: {self._bank_id}\n"
                f"filename: {processing_path.name}\n"
                f"error: {exc.__class__.__name__}: {exc}\n"
                f"timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(timestamp))}\n"
            )
            failed_error.write_text(error_text, encoding="utf-8")
        except Exception as write_exc:
            log.error(
                "msv.file_watcher.error_txt_write_failed",
                filename=processing_path.name,
                error=str(write_exc),
            )

        log.error(
            "msv.file_watcher.processing_failed",
            filename=processing_path.name,
            job_id=job_id,
            bank_id=self._bank_id,
            error=str(exc),
        )

    async def recover_orphans(self) -> None:
        """
        Re-process files stranded in processing/ from a previous crashed session.

        Called once at startup before watchdog begins. Each orphaned file is
        processed exactly as if it had just arrived in incoming/ — the atomic
        rename step is skipped since the file is already in processing/.
        """
        with tracer.start_as_current_span("msv.file_watcher.recover_orphans") as span:
            span.set_attribute("bank_id", self._bank_id)

            orphans = list(self._processing.iterdir())
            span.set_attribute("orphan_count", len(orphans))

            if not orphans:
                return

            log.warning(
                "msv.file_watcher.orphan_recovery_start",
                count=len(orphans),
                bank_id=self._bank_id,
            )

            for orphan_path in orphans:
                if orphan_path.suffix not in _SUPPORTED_SUFFIXES:
                    continue

                log.info(
                    "msv.file_watcher.recovering_orphan",
                    filename=orphan_path.name,
                    bank_id=self._bank_id,
                )

                job_id = f"msv-orphan-{uuid.uuid4().hex[:12]}"
                try:
                    await self._processor.process_file(
                        orphan_path, self._bank_id, job_id
                    )
                    timestamp = int(time.time())
                    final_name = f"{orphan_path.name}.{timestamp}"
                    orphan_path.rename(self._processed / final_name)
                    log.info(
                        "msv.file_watcher.orphan_recovered",
                        filename=orphan_path.name,
                        job_id=job_id,
                        bank_id=self._bank_id,
                    )
                except Exception as exc:
                    self._handle_failure(orphan_path, exc, job_id)

    async def _wait_stable(
        self,
        path: Path,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        """
        Wait until path's file size has not changed for _STABLE_CHECK_COUNT polls.

        Args:
            path:          File to monitor
            poll_interval: Seconds between size checks
        """
        previous_size: Optional[int] = None
        stable_count = 0

        while stable_count < _STABLE_CHECK_COUNT:
            try:
                current_size = path.stat().st_size
            except FileNotFoundError:
                return  # file gone — caller will handle

            if current_size == previous_size:
                stable_count += 1
            else:
                stable_count = 0
                previous_size = current_size

            if stable_count < _STABLE_CHECK_COUNT:
                await asyncio.sleep(poll_interval)
