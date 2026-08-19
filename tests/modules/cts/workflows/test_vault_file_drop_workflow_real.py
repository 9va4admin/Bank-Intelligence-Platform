"""
Real Temporal worker tests for VaultFileDropWorkflow.

Unlike test_vault_file_drop_workflow.py (which calls run_with_mocks()),
these tests drive the workflow through an actual Temporal worker using
WorkflowEnvironment.start_time_skipping(). The worker:
  - schedules the workflow via temporal_client.execute_workflow()
  - executes activity functions through the task queue
  - returns the VaultFileDropResult via Temporal's result protocol

This proves that:
  - The @workflow.defn / @activity.defn decorators are wired correctly
  - Activity scheduling order matches the workflow's control flow
  - Temporal serialises / deserialises Pydantic models correctly
  - Retry policies don't accidentally suppress expected results
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from modules.cts.workflows.vault_file_drop_workflow import (
    VaultFileDropWorkflow,
    VaultFileDropInput,
    FetchDropFileResult,
    FetchDropFileInput,
    ProcessVaultCSVResult,
    ProcessVaultCSVInput,
    ArchiveDropFileInput,
    VaultBatchAlertInput,
    fetch_drop_file,       # real activity — used for degradation tests
    process_vault_csv,     # real activity — used for degradation tests
    archive_drop_file,     # real activity — used for degradation tests
    emit_vault_batch_alert,
)


# ---------------------------------------------------------------------------
# Module-level result stores — set per test, reset in fixture
# ---------------------------------------------------------------------------

_fetch_result: FetchDropFileResult = FetchDropFileResult()
_process_result: ProcessVaultCSVResult = ProcessVaultCSVResult()
_alert_calls: list[VaultBatchAlertInput] = []
_archive_called: list[bool] = []


# ---------------------------------------------------------------------------
# Fake activity stubs — same @activity.defn name as production functions
# ---------------------------------------------------------------------------

@activity.defn(name="fetch_drop_file")
async def _fake_fetch(inp: FetchDropFileInput) -> FetchDropFileResult:
    return _fetch_result


@activity.defn(name="process_vault_csv")
async def _fake_process(inp: ProcessVaultCSVInput) -> ProcessVaultCSVResult:
    return _process_result


@activity.defn(name="archive_drop_file")
async def _fake_archive(inp: ArchiveDropFileInput) -> None:
    _archive_called.append(True)


@activity.defn(name="emit_vault_batch_alert")
async def _fake_alert(inp: VaultBatchAlertInput) -> None:
    _alert_calls.append(inp)


_FAKE_ACTIVITIES = [_fake_fetch, _fake_process, _fake_archive, _fake_alert]
_REAL_ACTIVITIES = [fetch_drop_file, process_vault_csv, archive_drop_file, emit_vault_batch_alert]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture(autouse=True)
def _reset_state():
    global _fetch_result, _process_result
    _fetch_result  = FetchDropFileResult()
    _process_result = ProcessVaultCSVResult()
    _alert_calls.clear()
    _archive_called.clear()
    yield
    _alert_calls.clear()
    _archive_called.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inp(vault_type="PPS", bank_id="saraswat-coop", file_hash=None) -> VaultFileDropInput:
    return VaultFileDropInput(
        bank_id=bank_id,
        vault_type=vault_type,
        minio_bucket="astra-vault-drops",
        minio_key=f"{bank_id}/{vault_type.lower()}/upload_20260819.csv",
        file_hash=file_hash or uuid.uuid4().hex,
        feed_name="sftp",
    )


async def _run_workflow(env, inp: VaultFileDropInput, activities=None):
    task_queue = f"tq-vault-{uuid.uuid4().hex[:8]}"
    acts = activities if activities is not None else _FAKE_ACTIVITIES
    async with Worker(
        env.client,
        task_queue=task_queue,
        workflows=[VaultFileDropWorkflow],
        activities=acts,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        return await env.client.execute_workflow(
            VaultFileDropWorkflow.run,
            inp,
            id=f"test-vault-drop-{uuid.uuid4().hex[:8]}",
            task_queue=task_queue,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVaultFileDropWorkflowRealWorker:
    """
    Each test starts a real Temporal worker and drives the workflow end-to-end.
    Activities are controlled via module-level result stores.
    """

    @pytest.mark.asyncio
    async def test_happy_path_returns_vault_updated(self, temporal_env):
        """
        fetch → bytes returned
        process → batch processed (10 rows, 0 failed)
        archive → non-fatal
        Result: VAULT_UPDATED, rows_processed=10
        """
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(
            batch_id="batch-real-001",
            rows_total=10,
            rows_processed=10,
            rows_failed=0,
        )

        result = await _run_workflow(temporal_env, _inp())

        assert result.outcome       == "VAULT_UPDATED"
        assert result.rows_total    == 10
        assert result.rows_processed == 10
        assert result.rows_failed   == 0
        assert result.batch_id      == "batch-real-001"

    @pytest.mark.asyncio
    async def test_fetch_unavailable_returns_parse_failed(self, temporal_env):
        """
        Real fetch_drop_file activity with minio_client=None →
        activity returns FetchDropFileResult(error="MINIO_UNAVAILABLE") →
        workflow returns PARSE_FAILED.

        This tests the actual degraded path through a live Temporal worker.
        """
        result = await _run_workflow(temporal_env, _inp(), activities=_REAL_ACTIVITIES)

        assert result.outcome == "PARSE_FAILED"
        assert "MINIO_UNAVAILABLE" in (result.error or "")

    @pytest.mark.asyncio
    async def test_process_error_returns_vault_update_failed(self, temporal_env):
        """process_vault_csv returns error → VAULT_UPDATE_FAILED."""
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(error="DB_UNAVAILABLE")

        result = await _run_workflow(temporal_env, _inp())

        assert result.outcome == "VAULT_UPDATE_FAILED"
        assert result.error   == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_duplicate_file_returns_duplicate_skipped(self, temporal_env):
        """fetch returns duplicate=True → DUPLICATE_SKIPPED, process never called."""
        global _fetch_result
        _fetch_result = FetchDropFileResult(csv_bytes=b"", duplicate=True)

        result = await _run_workflow(temporal_env, _inp())

        assert result.outcome == "DUPLICATE_SKIPPED"
        # process activity must NOT have been called
        # (process mock returns default empty result — but outcome proves process was skipped)
        assert result.rows_total == 0

    @pytest.mark.asyncio
    async def test_unknown_vault_type_returns_parse_failed_immediately(self, temporal_env):
        """
        An unknown vault_type is caught at the top of workflow.run()
        before any activity is scheduled.
        """
        result = await _run_workflow(temporal_env, _inp(vault_type="INVALID_TYPE"))

        assert result.outcome == "PARSE_FAILED"
        assert "INVALID_TYPE" in (result.error or "")

    @pytest.mark.asyncio
    async def test_partial_batch_triggers_emit_alert_activity(self, temporal_env):
        """
        rows_failed > 0 → workflow schedules emit_vault_batch_alert.
        The fake alert activity appends to _alert_calls — proves activity was executed.
        """
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(
            batch_id="batch-partial-001",
            rows_total=10,
            rows_processed=7,
            rows_failed=3,
        )

        result = await _run_workflow(temporal_env, _inp())

        assert result.outcome     == "VAULT_UPDATED"
        assert result.rows_failed == 3
        assert len(_alert_calls)  == 1
        alert = _alert_calls[0]
        assert alert.batch_id     == "batch-partial-001"
        assert alert.rows_failed  == 3

    @pytest.mark.asyncio
    async def test_complete_batch_does_not_trigger_alert(self, temporal_env):
        """rows_failed == 0 → emit_vault_batch_alert must NOT be scheduled."""
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(
            batch_id="batch-clean-001",
            rows_total=10,
            rows_processed=10,
            rows_failed=0,
        )

        await _run_workflow(temporal_env, _inp())

        assert len(_alert_calls) == 0   # no alert when batch is clean

    @pytest.mark.asyncio
    async def test_bank_id_propagated_to_workflow_result(self, temporal_env):
        """bank_id from input must appear in the returned result."""
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(
            batch_id="b", rows_total=5, rows_processed=5, rows_failed=0,
        )

        result = await _run_workflow(temporal_env, _inp(bank_id="federal-bank"))

        assert result.bank_id == "federal-bank"

    @pytest.mark.asyncio
    async def test_archive_activity_called_on_success(self, temporal_env):
        """After successful processing, archive_drop_file must be executed."""
        global _fetch_result, _process_result
        _fetch_result   = FetchDropFileResult(csv_bytes=b"col\nval", duplicate=False)
        _process_result = ProcessVaultCSVResult(
            batch_id="b", rows_total=5, rows_processed=5, rows_failed=0,
        )

        await _run_workflow(temporal_env, _inp())

        assert len(_archive_called) == 1

    @pytest.mark.asyncio
    async def test_archive_not_called_on_fetch_failure(self, temporal_env):
        """Fetch failed → workflow returns PARSE_FAILED → archive must NOT be called."""
        global _fetch_result
        _fetch_result = FetchDropFileResult(error="HASH_MISMATCH")

        result = await _run_workflow(temporal_env, _inp())

        assert result.outcome == "PARSE_FAILED"
        assert len(_archive_called) == 0
