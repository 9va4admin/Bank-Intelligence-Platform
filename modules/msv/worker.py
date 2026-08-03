"""
MSV Temporal Worker — polls msv-processing-{bank_id} task queue exclusively.

Registers MSVValidationWorkflow and its three activities.
Graceful shutdown: 2-minute drain window so in-flight workflows complete.
Never polls CTS or EJ task queues — module blast isolation enforced here.

Usage:
    python -m modules.msv.worker --bank-id saraswat-coop
"""
import asyncio
import signal
import sys
from datetime import timedelta
from typing import Optional

import structlog

from shared.config.config_service import ConfigService
from shared.config.exceptions import ConfigKeyNotFoundError
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

try:
    from temporalio.client import Client
    from temporalio.worker import Worker

    _TEMPORAL_AVAILABLE = True
except ImportError:
    _TEMPORAL_AVAILABLE = False

from modules.msv.workflows.msv_workflow import MSVValidationWorkflow
from modules.msv.worker_activities import build_bound_activities

ALL_WORKFLOWS = [MSVValidationWorkflow]


async def run_worker(bank_id: str, config_service: Optional[ConfigService] = None) -> None:
    if not _TEMPORAL_AVAILABLE:
        log.error("msv_worker.temporal_not_installed", bank_id=bank_id)
        raise RuntimeError("temporalio package not installed. Run: pip install temporalio")

    if config_service is None:
        config_service = ConfigService()
        await config_service.initialise()

    try:
        temporal_address = config_service.get_platform("temporal.address")
    except ConfigKeyNotFoundError:
        temporal_address = "localhost:7233"
        log.warning("msv_worker.temporal_address_not_configured", fallback=temporal_address)

    try:
        temporal_namespace = config_service.get_platform("temporal.namespace")
    except ConfigKeyNotFoundError:
        temporal_namespace = "default"

    try:
        platform_version = config_service.get_platform("platform.version")
    except ConfigKeyNotFoundError:
        platform_version = "dev"

    task_queue = f"msv-processing-{bank_id}"

    configure_otel(
        service_name="msv-worker",
        service_version=platform_version,
        bank_id=bank_id,
    )

    log.info(
        "msv_worker.starting",
        bank_id=bank_id,
        task_queue=task_queue,
        temporal_address=temporal_address,
    )

    bound_activities = await build_bound_activities(bank_id, config_service)

    client = await Client.connect(
        temporal_address,
        namespace=temporal_namespace,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=ALL_WORKFLOWS,
        activities=bound_activities.activity_list(),
        max_concurrent_workflow_tasks=50,
        max_concurrent_activities=100,
        graceful_shutdown_timeout=timedelta(minutes=2),
    )

    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("msv_worker.shutdown_requested", bank_id=bank_id)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _handle_signal())

    async with worker:
        log.info("msv_worker.ready", bank_id=bank_id, task_queue=task_queue)
        await shutdown_event.wait()

    log.info("msv_worker.stopped", bank_id=bank_id)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ASTRA MSV Temporal Worker")
    parser.add_argument("--bank-id", required=True, help="Bank identifier (e.g. saraswat-coop)")
    args = parser.parse_args()
    asyncio.run(run_worker(bank_id=args.bank_id))


if __name__ == "__main__":
    main()
