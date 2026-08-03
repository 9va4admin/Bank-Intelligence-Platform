"""
Integration test: real Temporal → BoundCTSActivities.write_audit → real Immudb.

Proves three things in one end-to-end execution:

  1. Temporal correctly deserializes WriteAuditInput (not a plain dict) when
     the bound method has `inp: WriteAuditInput` type annotation — the fix in
     modules/cts/worker_activities.py. Without it, `inp.event_type` would
     raise AttributeError on a dict.

  2. AsyncImmudbWriter.write() reaches the real Immudb instance and calls
     verifiedSet() (not the old unverified set()). WriteAuditResult.success
     is True only when verifiedSet() returns verified=True.

  3. The full registration chain works: Worker() accepts a BoundCTSActivities
     bound method as a registered activity; the workflow dispatches to it by
     name string "write_audit"; the result round-trips back as WriteAuditResult.

Requires: infra/docker-compose.integration.yml up (Temporal + Immudb at minimum).
Skipped automatically when the stack isn't running — see conftest.py _require().

Run:
    docker compose -f infra/docker-compose.integration.yml up -d
    pytest tests/integration/test_temporal_workflow_integration.py -m integration -v
"""
import uuid
from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from modules.cts.worker_activities import BoundCTSActivities
from modules.cts.workflows.activities.write_audit import WriteAuditInput, WriteAuditResult
from shared.audit.immudb_client import ImmudbClient
from shared.audit.immudb_writer import AsyncImmudbWriter
from tests.integration.conftest import (
    IMMUDB_HOST,
    IMMUDB_PASSWORD,
    IMMUDB_PORT,
    IMMUDB_USERNAME,
    TEMPORAL_HOST,
    TEMPORAL_PORT,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal smoke workflow — delegates to the write_audit activity by name.
# Must be at module level for Worker() to register it as a @workflow.defn.
# ---------------------------------------------------------------------------


@workflow.defn
class _CtsAuditSmokeWorkflow:
    """
    Single-activity wrapper that calls write_audit and returns its result.
    Exists only for this integration test — not registered in the production
    worker.py (where ChequeProcessingWorkflow is the real entry point).
    """

    @workflow.run
    async def run(self, inp: WriteAuditInput) -> WriteAuditResult:
        return await workflow.execute_activity(
            "write_audit",   # matched by name to BoundCTSActivities.write_audit
            inp,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_audit_via_temporal_to_immudb(
    require_temporal: None,
    require_immudb: None,
) -> None:
    """
    Full chain: real Temporal server → BoundCTSActivities.write_audit →
    real Immudb server.

    Assertions:
    - result is WriteAuditResult (not a dict — proves type deserialization works)
    - result.success is True
    - result.immudb_tx_id is a non-empty numeric string (verifiedSet tx ID)
    """
    task_queue = f"astra-it-audit-smoke-{uuid.uuid4().hex[:8]}"
    bank_id = "it-test-bank"

    # Build a real AsyncImmudbWriter backed by the Docker Immudb container.
    raw_client = ImmudbClient()
    raw_client.connect(
        IMMUDB_HOST,
        IMMUDB_PORT,
        bank_id,
        username=IMMUDB_USERNAME,
        password=IMMUDB_PASSWORD,
    )
    immudb_writer = AsyncImmudbWriter(raw_client)

    # BoundCTSActivities with only immudb_client wired — all other dependencies
    # stay None (write_audit doesn't need them; they degrade gracefully anyway).
    bound = BoundCTSActivities(bank_id=bank_id, immudb_client=immudb_writer)

    # Connect to the real Temporal auto-setup container.
    client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}", namespace="default")

    inp = WriteAuditInput(
        event_type="CTS_NGCH_FILED_CONFIRM",
        bank_id=bank_id,
        instrument_id="IT-SMOKE-001",
        payload={"integration_test": True, "run_id": uuid.uuid4().hex},
    )

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[_CtsAuditSmokeWorkflow],
        activities=[bound.write_audit],
        # UnsandboxedWorkflowRunner bypasses the Temporal determinism sandbox
        # that otherwise produces false-positive violations from transitive
        # imports (structlog, pydantic, etc.) in our activity modules.
        workflow_runner=UnsandboxedWorkflowRunner(),
        max_concurrent_activities=1,
    ):
        result = await client.execute_workflow(
            _CtsAuditSmokeWorkflow.run,
            inp,
            id=f"it-audit-smoke-{uuid.uuid4().hex}",
            task_queue=task_queue,
            execution_timeout=timedelta(seconds=30),
        )

    # If inp was deserialized as a plain dict (missing type annotation), the
    # activity would crash with AttributeError before reaching Immudb —
    # result would be a WorkflowFailureError, not a WriteAuditResult.
    assert isinstance(result, WriteAuditResult), (
        f"Expected WriteAuditResult but got {type(result).__name__}: {result!r}\n"
        "If type is dict, the `inp: WriteAuditInput` annotation is missing or "
        "not resolvable by get_type_hints() (check module-level import)."
    )
    assert result.success is True, (
        f"write_audit returned success=False: {result!r}\n"
        "Immudb write failed — check that verifiedSet() is called, not set()."
    )
    assert result.immudb_tx_id is not None, (
        "immudb_tx_id is None on success — verifiedSet() should return a tx ID"
    )
    assert result.immudb_tx_id.isdigit(), (
        f"immudb_tx_id should be a numeric Immudb transaction ID, got: "
        f"{result.immudb_tx_id!r}"
    )
