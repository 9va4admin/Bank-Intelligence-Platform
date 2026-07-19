"""
CTS Temporal Worker — polls cts-processing-{bank_id} task queue exclusively.

Registers all CTS workflows and activities.
Graceful shutdown: 2-minute drain window so in-flight workflows complete.
Never polls EJ task queues — module blast isolation enforced here.

Usage:
    python -m modules.cts.worker --bank-id saraswat-coop
"""
import asyncio
import os
import signal
import sys
from datetime import timedelta
from typing import Optional

import structlog

from shared.config.config_service import ConfigService
from shared.config.exceptions import ConfigKeyNotFoundError
from shared.observability.otel_setup import configure_otel

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Retry policies — canonical constants from temporal.md
# ---------------------------------------------------------------------------

try:
    from temporalio.common import RetryPolicy
    from temporalio.client import Client
    from temporalio.worker import Worker

    AI_ACTIVITY_RETRY = RetryPolicy(
        maximum_attempts=2,
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,
        non_retryable_error_types=["ValidationError", "IETBreachError"],
    )

    NGCH_FILING_RETRY = RetryPolicy(
        maximum_attempts=3,
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        non_retryable_error_types=["DuplicateFilingError"],
    )

    CBS_RETRY = RetryPolicy(
        maximum_attempts=3,
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=1.5,
    )

    AUDIT_RETRY = RetryPolicy(
        maximum_attempts=0,
        initial_interval=timedelta(seconds=1),
        maximum_interval=timedelta(minutes=5),
    )

    _TEMPORAL_AVAILABLE = True

except ImportError:
    _TEMPORAL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Workflow and activity imports
# ---------------------------------------------------------------------------

from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
from modules.cts.workflows.vault_sync_workflow import VaultSyncWorkflow
from modules.cts.workflows.delta_vault_sync_workflow import DeltaVaultSyncWorkflow
from modules.cts.workflows.smb_forwarding_workflow import SMBForwardingWorkflow
from modules.cts.workflows.smb_cheque_processing_workflow import SMBChequeProcessingWorkflow
from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
from modules.cts.workflows.batch_endorsement_workflow import BatchEndorsementWorkflow
from modules.cts.workflows.ngch_submission_workflow import NGCHSubmissionWorkflow

from modules.cts.workflows.activities.ocr import ocr_extract
from modules.cts.workflows.activities.alteration import detect_alteration
from modules.cts.workflows.activities.signature import verify_signature
from modules.cts.workflows.activities.pps import lookup_pps
from modules.cts.workflows.activities.cbs import check_cbs_balance, check_account_status
from modules.cts.workflows.activities.stop_payment import check_stop_payment
from modules.cts.workflows.activities.fraud import score_fraud
from modules.cts.workflows.activities.decision import synthesise_decision
from modules.cts.workflows.activities.ngch_filer import file_to_ngch
from modules.cts.workflows.activities.write_audit import write_audit
from modules.cts.workflows.activities.kill_switch_lookup import get_kill_switch_status
from modules.cts.workflows.activities.smb_forwarding_activities import (
    validate_smb_forwarding_window,
    write_forwarding_log_start,
    write_forwarding_log_complete,
    write_smb_forwarding_audit,
)
from modules.cts.workflows.vault_sync_workflow import (
    load_signatures_from_cbs,
    load_pps_from_cbs,
    warm_redis_vault,
    verify_vault_integrity,
)
from modules.cts.workflows.delta_vault_sync_workflow import (
    fetch_delta_stop_payments,
    fetch_delta_canceled_leaves,
    update_bloom_filter,
)
from modules.cts.workflows.human_review_workflow import push_to_review_queue
from modules.cts.sub_member.activities import (
    notify_sub_member_return,
    emit_batch_ledger_update,
    check_return_rate_shield,
)
from modules.cts.workflows.activities.outward_scan_activities import (
    validate_cts2010,
    create_lot_entry,
    run_vision_presentment_check,
)
from modules.cts.workflows.mismatch_resolution_workflow import publish_mismatch_hold
from modules.cts.workflows.activities.batch_endorsement_activities import (
    stamp_endorsement,
    update_lot_status,
)
from modules.cts.workflows.activities.ngch_submission_activities import (
    build_ngch_file,
    submit_to_ngch,
    confirm_acknowledgement,
)
from modules.cts.worker_activities import build_bound_activities

ALL_WORKFLOWS = [
    ChequeProcessingWorkflow,
    IETWatchdogWorkflow,
    HumanReviewWorkflow,
    VaultSyncWorkflow,
    DeltaVaultSyncWorkflow,
    SMBForwardingWorkflow,
    SMBChequeProcessingWorkflow,
    OutwardScanWorkflow,
    MismatchResolutionWorkflow,
    BatchEndorsementWorkflow,
    NGCHSubmissionWorkflow,
]

# Every registered CTS activity name, for reference/introspection. This list
# is NOT what gets passed to Worker() — see run_worker(), which combines
# NO_DI_ACTIVITIES (below, bare functions) with a BoundCTSActivities
# instance's DI-wired bound methods (modules/cts/worker_activities.py) built
# fresh per run_worker() call, since real dependency construction is async
# and needs a resolved bank_id + config_service that don't exist at import
# time.
ALL_ACTIVITIES = [
    ocr_extract,
    detect_alteration,
    verify_signature,
    lookup_pps,
    check_cbs_balance,
    check_account_status,
    check_stop_payment,
    score_fraud,
    synthesise_decision,
    file_to_ngch,
    write_audit,
    get_kill_switch_status,
    validate_smb_forwarding_window,
    write_forwarding_log_start,
    write_forwarding_log_complete,
    write_smb_forwarding_audit,
    load_signatures_from_cbs,
    load_pps_from_cbs,
    warm_redis_vault,
    verify_vault_integrity,
    fetch_delta_stop_payments,
    fetch_delta_canceled_leaves,
    update_bloom_filter,
    push_to_review_queue,
    notify_sub_member_return,
    emit_batch_ledger_update,
    check_return_rate_shield,
    validate_cts2010,
    create_lot_entry,
    run_vision_presentment_check,
    publish_mismatch_hold,
    stamp_endorsement,
    update_lot_status,
    build_ngch_file,
    submit_to_ngch,
    confirm_acknowledgement,
]

# Activities that take no injectable external dependency — pure computation
# (validate_cts2010 wraps InstrumentComplianceRecord, no I/O). Registered
# directly as a bare function — never wrapped in BoundCTSActivities.
NO_DI_ACTIVITIES = [
    validate_cts2010,
]


# ---------------------------------------------------------------------------
# Worker startup
# ---------------------------------------------------------------------------

async def run_worker(bank_id: str, config_service: Optional[ConfigService] = None) -> None:
    if not _TEMPORAL_AVAILABLE:
        log.error("worker.temporal_not_installed", bank_id=bank_id)
        raise RuntimeError(
            "temporalio package not installed. "
            "Run: pip install temporalio"
        )

    if config_service is None:
        config_service = ConfigService()
        await config_service.initialise()

    # temporal.address and temporal.namespace are Layer 2 (Helm-injected
    # deployment topology) — synchronous get_platform(), no DB round-trip.
    try:
        temporal_address = config_service.get_platform("temporal.address")
    except ConfigKeyNotFoundError:
        temporal_address = "localhost:7233"
        log.warning("worker.temporal_address_not_configured", fallback=temporal_address)

    try:
        temporal_namespace = config_service.get_platform("temporal.namespace")
    except ConfigKeyNotFoundError:
        temporal_namespace = "default"

    try:
        platform_version = config_service.get_platform("platform.version")
    except ConfigKeyNotFoundError:
        platform_version = "dev"

    task_queue = f"cts-processing-{bank_id}"

    configure_otel(
        service_name="cts-agent-worker",
        service_version=platform_version,
        bank_id=bank_id,
    )

    log.info(
        "worker.starting",
        bank_id=bank_id,
        task_queue=task_queue,
        temporal_address=temporal_address,
    )

    # Real dependency construction (CBS/Redis/Immudb/Kafka/NGCH/OPA/vLLM) is
    # async and per-bank — cannot happen at module import time. Each
    # dependency degrades independently to None on failure; see
    # modules/cts/worker_activities.py's module docstring.
    bound_activities = await build_bound_activities(bank_id, config_service)
    worker_activities = NO_DI_ACTIVITIES + bound_activities.activity_list()

    client = await Client.connect(
        temporal_address,
        namespace=temporal_namespace,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=ALL_WORKFLOWS,
        activities=worker_activities,
        max_concurrent_workflow_tasks=100,
        max_concurrent_activities=200,
        graceful_shutdown_timeout=timedelta(minutes=2),
    )

    shutdown_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("worker.shutdown_requested", bank_id=bank_id)
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # ProactorEventLoop (Windows) never implements add_signal_handler —
            # production runs on Linux K8s pods where the loop-native path
            # above always succeeds; this fallback only serves local Windows
            # dev/test runs so graceful shutdown still works there too.
            signal.signal(sig, lambda *_: _handle_signal())

    async with worker:
        log.info("worker.ready", bank_id=bank_id, task_queue=task_queue)
        await shutdown_event.wait()

    log.info("worker.stopped", bank_id=bank_id)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="ASTRA CTS Temporal Worker")
    parser.add_argument("--bank-id", required=True, help="Bank identifier (e.g. saraswat-coop)")
    args = parser.parse_args()

    asyncio.run(run_worker(bank_id=args.bank_id))


if __name__ == "__main__":
    main()
