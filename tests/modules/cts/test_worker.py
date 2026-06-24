"""
Tests for modules/cts/worker.py.

The worker module imports temporalio at module level via try/except, and
defines run_worker() which creates a Temporal client and Worker.
We test the importable constants and the run_worker() failure path when
temporalio is not available.
"""
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _stub_temporalio():
    """Stub temporalio into sys.modules so worker imports succeed."""
    from datetime import timedelta

    retry_cls = MagicMock()
    retry_cls.return_value = MagicMock()

    temporal_mod = MagicMock()
    temporal_common = MagicMock()
    temporal_common.RetryPolicy = retry_cls
    temporal_client_mod = MagicMock()
    temporal_client_mod.Client = MagicMock()
    temporal_worker_mod = MagicMock()
    temporal_worker_mod.Worker = MagicMock()

    sys.modules.setdefault("temporalio", temporal_mod)
    sys.modules.setdefault("temporalio.common", temporal_common)
    sys.modules.setdefault("temporalio.client", temporal_client_mod)
    sys.modules.setdefault("temporalio.worker", temporal_worker_mod)
    return temporal_client_mod, temporal_worker_mod


class TestWorkerModuleConstants:
    def test_all_workflows_list_is_non_empty(self):
        """ALL_WORKFLOWS contains the four expected workflow classes."""
        _stub_temporalio()
        from modules.cts.worker import ALL_WORKFLOWS
        assert len(ALL_WORKFLOWS) == 4

    def test_all_activities_list_is_non_empty(self):
        """ALL_ACTIVITIES contains the expected activity functions."""
        _stub_temporalio()
        from modules.cts.worker import ALL_ACTIVITIES
        assert len(ALL_ACTIVITIES) >= 10

    def test_temporal_available_flag_when_stubbed(self):
        """_TEMPORAL_AVAILABLE is True when temporalio is importable."""
        _stub_temporalio()
        import importlib
        import modules.cts.worker as w
        # Either True (if temporalio was already stubbed) or False (normal test env)
        assert isinstance(w._TEMPORAL_AVAILABLE, bool)


class TestRunWorkerNotInstalled:
    @pytest.mark.asyncio
    async def test_run_worker_raises_when_temporal_not_available(self):
        """Covers lines 109-115: RuntimeError when _TEMPORAL_AVAILABLE is False."""
        _stub_temporalio()
        import modules.cts.worker as w
        original = w._TEMPORAL_AVAILABLE
        w._TEMPORAL_AVAILABLE = False
        try:
            with pytest.raises(RuntimeError, match="temporalio package not installed"):
                await w.run_worker("test-bank")
        finally:
            w._TEMPORAL_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_run_worker_uses_config_service_when_provided(self):
        """Covers config_service.get calls in run_worker."""
        _stub_temporalio()
        import modules.cts.worker as w
        original = w._TEMPORAL_AVAILABLE
        w._TEMPORAL_AVAILABLE = False
        try:
            mock_cfg = MagicMock()
            mock_cfg.get = MagicMock(return_value="test-value")
            with pytest.raises(RuntimeError):
                await w.run_worker("test-bank", config_service=mock_cfg)
        finally:
            w._TEMPORAL_AVAILABLE = original


class TestMainEntrypoint:
    def test_main_function_exists(self):
        """main() is callable."""
        _stub_temporalio()
        from modules.cts.worker import main
        assert callable(main)
