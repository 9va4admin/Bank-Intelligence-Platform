"""
Tests for modules/ej/worker.py

TDD: tests written before implementation.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWorkerImports:
    def test_module_importable(self):
        import modules.ej.worker  # must not raise

    def test_run_worker_function_exists(self):
        from modules.ej.worker import run_worker
        assert callable(run_worker)

    def test_all_workflows_defined(self):
        from modules.ej.worker import ALL_WORKFLOWS
        assert isinstance(ALL_WORKFLOWS, list)
        assert len(ALL_WORKFLOWS) >= 2

    def test_all_activities_defined(self):
        from modules.ej.worker import ALL_ACTIVITIES
        assert isinstance(ALL_ACTIVITIES, list)
        assert len(ALL_ACTIVITIES) >= 1

    def test_ej_normalisation_workflow_in_workflows(self):
        from modules.ej.worker import ALL_WORKFLOWS
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
        assert EJNormalisationWorkflow in ALL_WORKFLOWS

    def test_dispute_resolution_workflow_in_workflows(self):
        from modules.ej.worker import ALL_WORKFLOWS
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow
        assert DisputeResolutionWorkflow in ALL_WORKFLOWS


class TestWorkerTaskQueue:
    def test_task_queue_uses_ej_prefix(self):
        """Worker must poll ej-normalisation-{bank_id} — never cts-*."""
        from modules.ej.worker import TASK_QUEUE_PREFIX
        assert TASK_QUEUE_PREFIX == "ej-normalisation"

    def test_task_queue_never_references_cts(self):
        """Isolation rule: EJ worker must not reference CTS task queues."""
        import modules.ej.worker as worker_module
        import inspect
        source = inspect.getsource(worker_module)
        assert "cts-processing" not in source
        assert "cts-agent" not in source


class TestRunWorkerNoTemporal:
    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_temporal_unavailable(self):
        from modules.ej.worker import run_worker
        with patch("modules.ej.worker._TEMPORAL_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="temporalio"):
                await run_worker(bank_id="test-bank")

    @pytest.mark.asyncio
    async def test_accepts_bank_id_and_temporal_address_params(self):
        """run_worker must accept temporal_address for testability."""
        from modules.ej.worker import run_worker
        import inspect
        sig = inspect.signature(run_worker)
        assert "bank_id" in sig.parameters
        assert "temporal_address" in sig.parameters


class TestMainCLI:
    def test_main_function_exists(self):
        from modules.ej.worker import main
        assert callable(main)
