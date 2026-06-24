"""
EJ Temporal Worker — polls ej-normalisation-{bank_id} task queue exclusively.

Registers all EJ workflows and activities.
Graceful shutdown: 2-minute drain window so in-flight workflows complete.
Never polls CTS task queues — module blast isolation enforced here.

Usage:
    python -m modules.ej.worker --bank-id saraswat-coop
"""
import asyncio
import signal
import sys
from datetime import timedelta
from typing import Optional

import structlog

log = structlog.get_logger()

TASK_QUEUE_PREFIX = "ej-normalisation"

try:
    from temporalio.client import Client
    from temporalio.worker import Worker

    _TEMPORAL_AVAILABLE = True
except ImportError:
    _TEMPORAL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Workflow and activity imports
# ---------------------------------------------------------------------------

from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow

from modules.ej.workflows.activities.ingest import ingest_ej_log
from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint
from modules.ej.workflows.activities.llm_parse import llm_parse_ej
from modules.ej.workflows.activities.validate import validate_ej_canonical
from modules.ej.workflows.activities.store_canonical import store_canonical
from modules.ej.workflows.activities.trigger_dispute_check import trigger_dispute_check
from modules.ej.workflows.activities.update_atm_health import update_atm_health
from modules.ej.workflows.activities.write_audit import write_audit
from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej
from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence

ALL_WORKFLOWS = [
    EJNormalisationWorkflow,
    DisputeResolutionWorkflow,
]

ALL_ACTIVITIES = [
    ingest_ej_log,
    validate_oem_fingerprint,
    llm_parse_ej,
    validate_ej_canonical,
    store_canonical,
    trigger_dispute_check,
    update_atm_health,
    write_audit,
    match_dispute_to_ej,
    extract_cctv_evidence,
]


# ---------------------------------------------------------------------------
# Worker startup
# ---------------------------------------------------------------------------

async def run_worker(
    bank_id: str,
    temporal_address: str = "localhost:7233",
    temporal_namespace: str = "default",
) -> None:
    if not _TEMPORAL_AVAILABLE:
        log.error("worker.temporal_not_installed", bank_id=bank_id)
        raise RuntimeError(
            "temporalio package not installed. "
            "Run: pip install temporalio"
        )

    task_queue = f"{TASK_QUEUE_PREFIX}-{bank_id}"

    log.info(
        "worker.starting",
        bank_id=bank_id,
        task_queue=task_queue,
        temporal_address=temporal_address,
    )

    client = await Client.connect(
        temporal_address,
        namespace=temporal_namespace,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=ALL_WORKFLOWS,
        activities=ALL_ACTIVITIES,
        max_concurrent_workflow_tasks=100,
        max_concurrent_activities=200,
        graceful_shutdown_timeout=timedelta(minutes=2),
    )

    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("worker.shutdown_requested", bank_id=bank_id)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, _handle_signal)
    loop.add_signal_handler(signal.SIGINT, _handle_signal)

    async with worker:
        log.info("worker.ready", bank_id=bank_id, task_queue=task_queue)
        await shutdown_event.wait()

    log.info("worker.stopped", bank_id=bank_id)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ASTRA EJ Temporal Worker")
    parser.add_argument("--bank-id", required=True, help="Bank identifier (e.g. saraswat-coop)")
    parser.add_argument(
        "--temporal-address",
        default="localhost:7233",
        help="Temporal server address",
    )
    args = parser.parse_args()

    asyncio.run(run_worker(bank_id=args.bank_id, temporal_address=args.temporal_address))


if __name__ == "__main__":
    main()
