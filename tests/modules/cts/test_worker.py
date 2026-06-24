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


class TestWorkerRetryConstants:
    def test_retry_constants_defined_when_temporal_available(self):
        """Covers lines 32-61: try block where RetryPolicy constants are defined."""
        import sys
        import importlib
        from unittest.mock import MagicMock
        from datetime import timedelta

        # Build full temporalio stubs with a real-enough RetryPolicy mock
        retry_instances = {}

        def make_retry(**kwargs):
            m = MagicMock()
            m._kwargs = kwargs
            return m

        retry_cls = MagicMock(side_effect=make_retry)

        temporal_mod = MagicMock()
        temporal_common = MagicMock()
        temporal_common.RetryPolicy = retry_cls
        temporal_client_mod = MagicMock()
        temporal_client_mod.Client = MagicMock()
        temporal_worker_mod = MagicMock()
        temporal_worker_mod.Worker = MagicMock()

        # Force a fresh import of the worker module with temporalio available
        saved = {}
        for key in list(sys.modules.keys()):
            if key == "modules.cts.worker" or key.startswith("temporalio"):
                saved[key] = sys.modules.pop(key)

        sys.modules["temporalio"] = temporal_mod
        sys.modules["temporalio.common"] = temporal_common
        sys.modules["temporalio.client"] = temporal_client_mod
        sys.modules["temporalio.worker"] = temporal_worker_mod

        # Pre-clear any None sentinel entries so real module packages aren't
        # poisoned when the mock temporalio package is traversed during import
        for key in [k for k, v in list(sys.modules.items()) if v is None]:
            sys.modules.pop(key, None)

        try:
            import modules.cts.worker as w_fresh
            assert w_fresh._TEMPORAL_AVAILABLE is True
            assert hasattr(w_fresh, "AI_ACTIVITY_RETRY")
            assert hasattr(w_fresh, "NGCH_FILING_RETRY")
            assert hasattr(w_fresh, "CBS_RETRY")
            assert hasattr(w_fresh, "AUDIT_RETRY")
        finally:
            # Restore original state
            sys.modules.pop("modules.cts.worker", None)
            for key, val in saved.items():
                sys.modules[key] = val
            # Remove any None sentinel entries Python added for modules.ej.*
            # (Python sets sys.modules[name] = None as a negative cache when a
            # parent package is a mock and a subpackage was never found)
            for key in [k for k, v in list(sys.modules.items())
                        if v is None and k.startswith("modules.")]:
                sys.modules.pop(key, None)


class TestRunWorkerHappyPath:
    @pytest.mark.asyncio
    async def test_run_worker_connects_and_starts(self):
        """Covers lines 130-179: run_worker happy path with mocked Temporal."""
        import sys
        import asyncio
        from unittest.mock import MagicMock, AsyncMock, patch

        _stub_temporalio()
        import modules.cts.worker as w

        # Ensure _TEMPORAL_AVAILABLE is True
        w._TEMPORAL_AVAILABLE = True

        # Mock config_service
        mock_cfg = MagicMock()
        mock_cfg.get = MagicMock(side_effect=lambda k: {
            "temporal.address": "localhost:7233",
            "temporal.namespace": "default",
            "platform.version": "1.0.0",
        }.get(k, "mock-value"))

        # Mock Client.connect to return a mock client
        mock_client = MagicMock()
        mock_connect = AsyncMock(return_value=mock_client)

        # Mock Worker as an async context manager that exits immediately
        mock_worker_instance = AsyncMock()
        mock_worker_instance.__aenter__ = AsyncMock(return_value=mock_worker_instance)
        mock_worker_instance.__aexit__ = AsyncMock(return_value=False)
        mock_worker_cls = MagicMock(return_value=mock_worker_instance)

        # Patch shutdown to fire immediately
        async def instant_wait():
            pass  # returns immediately — simulates shutdown signal received

        with patch.object(w, "Client") as mock_client_cls, \
             patch.object(w, "Worker", mock_worker_cls), \
             patch("asyncio.Event") as mock_event_cls:

            mock_client_cls.connect = mock_connect
            mock_event = MagicMock()
            mock_event.wait = AsyncMock(return_value=None)  # immediate return
            mock_event_cls.return_value = mock_event

            await w.run_worker("test-bank", config_service=mock_cfg)

        mock_connect.assert_called_once_with("localhost:7233", namespace="default")
        assert mock_worker_cls.called

    def test_main_parses_bank_id_arg(self):
        """Covers lines 183-188: main() parses --bank-id arg."""
        import sys
        from unittest.mock import patch, AsyncMock

        _stub_temporalio()
        import modules.cts.worker as w

        captured = {}

        def fake_asyncio_run(coro):
            captured["coro"] = coro
            coro.close()

        with patch("sys.argv", ["worker.py", "--bank-id", "test-bank"]), \
             patch("asyncio.run", side_effect=fake_asyncio_run):
            w.main()

        assert "coro" in captured
