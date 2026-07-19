"""
OutwardScanTrigger — Kafka → OutwardScanWorkflow bridge.

Reads the cts.outward.scanned.{bank_id} topic, parses BatchScannedEvent payloads,
and starts one OutwardScanWorkflow per scan in per_scan_data.

Design:
  - Non-blocking: uses asyncio.to_thread() around synchronous kafka-python poll
  - Bank-scoped: events for other bank_ids are silently dropped (topic fan-out safety)
  - Resilient: malformed JSON, missing fields, or Temporal failures are logged and
    skipped; the poll loop never dies
  - Exactly-once: Temporal workflow ID is deterministic per scan_id — re-delivering
    the same Kafka message just returns WorkflowAlreadyStartedError (swallowed)

Usage (in modules/cts/worker.py):
    trigger = OutwardScanTrigger(
        bank_id=bank_id,
        bootstrap_servers=bootstrap_servers,
        temporal_client=client,
        task_queue=task_queue,
    )
    asyncio.create_task(trigger.run())
    ...
    trigger.stop()  # on shutdown
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import structlog

log = structlog.get_logger()

# Kafka-python is synchronous — we wrap every blocking call with asyncio.to_thread()
try:
    from kafka import KafkaConsumer

    _KAFKA_AVAILABLE = True
except ImportError:
    _KAFKA_AVAILABLE = False


class OutwardScanTrigger:
    """
    Polls cts.outward.scanned.{bank_id} and starts OutwardScanWorkflow for each scan.

    Args:
        bank_id: Only events with this bank_id are processed.
        bootstrap_servers: Kafka broker address(es).
        temporal_client: Connected temporalio.client.Client instance.
        task_queue: Temporal task queue for OutwardScanWorkflow workers.
    """

    def __init__(
        self,
        *,
        bank_id: str,
        bootstrap_servers: str,
        temporal_client: Any,
        task_queue: str,
    ) -> None:
        self._bank_id = bank_id
        self._bootstrap_servers = bootstrap_servers
        self._temporal = temporal_client
        self._task_queue = task_queue
        self._stop = threading.Event()

    def stop(self) -> None:
        """Signal the poll loop to exit at the next iteration."""
        self._stop.set()

    async def run(self) -> None:
        """
        Blocking poll loop — run as an asyncio background task.

        Exits when stop() is called. Constructs the KafkaConsumer lazily so
        tests can inject a pre-built consumer or mock the entire run().
        """
        if not _KAFKA_AVAILABLE:
            log.error(
                "outward_scan_trigger.kafka_not_installed",
                bank_id=self._bank_id,
            )
            return

        topic = f"cts.outward.scanned.{self._bank_id}"
        consumer = await asyncio.to_thread(
            KafkaConsumer,
            topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=f"cg-cts-outscan-trigger-{self._bank_id}",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            consumer_timeout_ms=500,
        )

        log.info(
            "outward_scan_trigger.started",
            bank_id=self._bank_id,
            topic=topic,
            task_queue=self._task_queue,
        )

        try:
            while not self._stop.is_set():
                messages = await asyncio.to_thread(
                    self._poll_once, consumer
                )
                for message in messages:
                    await self._handle_message(message)
        finally:
            await asyncio.to_thread(consumer.close)
            log.info("outward_scan_trigger.stopped", bank_id=self._bank_id)

    def _poll_once(self, consumer: Any) -> list:
        """Blocking poll — called via asyncio.to_thread."""
        try:
            records = consumer.poll(timeout_ms=500)
            messages = []
            for partition_records in records.values():
                messages.extend(partition_records)
            return messages
        except Exception:
            return []

    async def _handle_message(self, message: Any) -> None:
        """
        Parse one Kafka message and start OutwardScanWorkflow for each scan.

        Failures per-scan do not abort the loop for other scans in the same event.
        """
        try:
            event = json.loads(message.value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as exc:
            log.warning(
                "outward_scan_trigger.malformed_message",
                bank_id=self._bank_id,
                error=str(exc),
            )
            return

        # Drop events intended for a different bank (topic fan-out safety)
        event_bank_id = event.get("bank_id", "")
        if event_bank_id != self._bank_id:
            log.debug(
                "outward_scan_trigger.wrong_bank_id",
                expected=self._bank_id,
                got=event_bank_id,
            )
            return

        per_scan_data: list[dict] = event.get("per_scan_data", [])
        if not per_scan_data:
            log.debug(
                "outward_scan_trigger.no_per_scan_data",
                bank_id=self._bank_id,
                batch_id=event.get("batch_id"),
            )
            return

        pu_id = event.get("pu_id", "")
        branch_id = event.get("branch_id", "")
        batch_id = event.get("batch_id", "")

        for scan_data in per_scan_data:
            scan_id = scan_data.get("scan_id", "")
            if not scan_id:
                continue

            wf_id = f"cts-outscan-{self._bank_id}-{pu_id}-{scan_id}" if pu_id else \
                    f"cts-outscan-{self._bank_id}-{scan_id}"

            await self._start_one_workflow(
                scan_id=scan_id,
                wf_id=wf_id,
                scan_data=scan_data,
                event=event,
                batch_id=batch_id,
                pu_id=pu_id,
                branch_id=branch_id,
            )

    async def _start_one_workflow(
        self,
        *,
        scan_id: str,
        wf_id: str,
        scan_data: dict,
        event: dict,
        batch_id: str,
        pu_id: str,
        branch_id: str,
    ) -> None:
        """Start a single OutwardScanWorkflow; log and continue on any failure."""
        try:
            from modules.cts.workflows.outward_scan_workflow import (
                OutwardScanWorkflow,
                OutwardScanInput,
            )

            inp = OutwardScanInput(
                scan_id=scan_id,
                instrument_id=scan_id,          # placeholder; lot manager assigns real ID
                bank_id=self._bank_id,
                bank_ifsc="",                   # resolved in workflow from CBS/lot context
                session_id=batch_id,
                image_front_url=scan_data.get("image_front_url", ""),
                image_rear_url=scan_data.get("image_rear_url", ""),
                pu_id=pu_id or None,
                branch_id=branch_id or None,
            )

            await self._temporal.start_workflow(
                OutwardScanWorkflow.run,
                inp,
                id=wf_id,
                task_queue=self._task_queue,
            )

            log.info(
                "outward_scan_trigger.workflow_started",
                bank_id=self._bank_id,
                scan_id=scan_id,
                wf_id=wf_id,
            )

        except Exception as exc:
            # WorkflowAlreadyStartedError is fine (exactly-once duplicate delivery)
            exc_name = type(exc).__name__
            if "WorkflowAlreadyStarted" in exc_name:
                log.debug(
                    "outward_scan_trigger.already_started",
                    wf_id=wf_id,
                    bank_id=self._bank_id,
                )
            else:
                log.error(
                    "outward_scan_trigger.workflow_start_failed",
                    bank_id=self._bank_id,
                    scan_id=scan_id,
                    wf_id=wf_id,
                    error=str(exc),
                )
