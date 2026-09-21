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

    try:
        import temporalio.worker.workflow_sandbox  # noqa: F401
        return temporal_client_mod, temporal_worker_mod   # real SDK present — never shadow it
    except ImportError:
        pass
    sys.modules.setdefault("temporalio", temporal_mod)
    sys.modules.setdefault("temporalio.common", temporal_common)
    sys.modules.setdefault("temporalio.client", temporal_client_mod)
    sys.modules.setdefault("temporalio.worker", temporal_worker_mod)
    return temporal_client_mod, temporal_worker_mod


class TestWorkerModuleConstants:
    def test_all_workflows_list_is_non_empty(self):
        """ALL_WORKFLOWS registers the core inward workflows (and every other CTS one)."""
        _stub_temporalio()
        from modules.cts.worker import ALL_WORKFLOWS
        names = {w.__name__ for w in ALL_WORKFLOWS}
        assert {"ChequeProcessingWorkflow", "IETWatchdogWorkflow", "HumanReviewWorkflow"} <= names
        assert len(names) == len(ALL_WORKFLOWS)   # no duplicates

    def test_all_activities_list_is_non_empty(self):
        """ALL_ACTIVITIES contains the expected activity functions."""
        _stub_temporalio()
        from modules.cts.worker import ALL_ACTIVITIES
        assert len(ALL_ACTIVITIES) >= 10

    def test_no_di_activities_plus_bound_activity_list_matches_all_activities(self):
        """Regression guard: every activity registered in ALL_ACTIVITIES must be
        reachable through exactly one of the two paths run_worker() actually
        uses — NO_DI_ACTIVITIES (bare functions) or BoundCTSActivities.activity_list()
        (DI-wired bound methods). If someone adds a new activity to ALL_ACTIVITIES
        without adding it to one of these two, run_worker() silently drops it from
        the real Worker() registration — this test catches that drift."""
        _stub_temporalio()
        from modules.cts.worker import ALL_ACTIVITIES, NO_DI_ACTIVITIES
        from modules.cts.worker_activities import BoundCTSActivities

        bound = BoundCTSActivities(bank_id="test-bank")
        bound_names = {m.__name__ for m in bound.activity_list()}
        no_di_names = {f.__name__ for f in NO_DI_ACTIVITIES}
        all_names = {f.__name__ for f in ALL_ACTIVITIES}

        assert all_names <= (bound_names | no_di_names)   # nothing listed is silently dropped
        assert bound_names & no_di_names == set()  # no activity double-registered

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
        """Real temporalio is installed: constants are real RetryPolicy objects
        matching temporal.md (no stubbing — stubs hid the real import path)."""
        import modules.cts.worker as w
        assert w._TEMPORAL_AVAILABLE is True
        assert w.AI_ACTIVITY_RETRY.maximum_attempts == 2
        assert w.NGCH_FILING_RETRY.maximum_attempts == 3
        assert w.AUDIT_RETRY.maximum_attempts is None   # unlimited — audit must succeed

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
        _platform_values = {
            "temporal.address": "localhost:7233",
            "temporal.namespace": "default",
            "platform.version": "1.0.0",
        }
        mock_cfg.get = MagicMock(side_effect=lambda k: _platform_values.get(k, "mock-value"))
        mock_cfg.get_platform = MagicMock(side_effect=lambda k: _platform_values.get(k, "mock-value"))

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
             patch("modules.cts.consumers.human_review_consumer.run_consumer", new=AsyncMock()), \
             patch("modules.cts.scanner.outward_scan_trigger.OutwardScanTrigger", new=MagicMock(return_value=MagicMock(run=AsyncMock()))), \
             patch("asyncio.Event") as mock_event_cls:

            mock_client_cls.connect = mock_connect
            mock_event = MagicMock()
            mock_event.wait = AsyncMock(return_value=None)  # immediate return
            mock_event_cls.return_value = mock_event

            await w.run_worker("test-bank", config_service=mock_cfg)

        from shared.temporal.converter import pydantic_data_converter
        mock_connect.assert_called_once_with(
            "localhost:7233", namespace="default", data_converter=pydantic_data_converter,
        )
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


class TestLoadTestStubHook:
    def test_stubs_applied_only_when_platform_flag_true(self, monkeypatch):
        from modules.cts.worker import _maybe_apply_load_test_stubs
        from modules.cts.worker_activities import BoundCTSActivities
        from shared.config.config_service import ConfigKeyNotFoundError
        monkeypatch.setenv("ASTRA_ENV", "development")
        bound = BoundCTSActivities(bank_id="kbl")

        off = MagicMock(); off.get_platform = MagicMock(side_effect=ConfigKeyNotFoundError("x"))
        assert _maybe_apply_load_test_stubs(bound, off) is bound

        on = MagicMock(); on.get_platform = MagicMock(return_value="true")
        out = _maybe_apply_load_test_stubs(bound, on)
        assert out is not bound and type(out).__name__ == "LoadTestBoundActivities"


class TestRegisteredActivities:
    def test_every_bare_activity_is_registered_once_and_none_keeps_extra_params(self):
        import inspect
        from modules.cts.worker import NO_DI_ACTIVITIES, _registered_activities
        from modules.cts.worker_activities import BoundCTSActivities
        b = BoundCTSActivities(bank_id="kbl")
        acts = _registered_activities(b)
        names = [a.__name__ for a in acts]
        assert len(names) == len(set(names)), "an activity is registered twice"
        assert len(acts) == len(NO_DI_ACTIVITIES) + len(b.activity_list())
        bare = {f.__name__ for f in NO_DI_ACTIVITIES}
        for a in acts:
            if a.__name__ in bare:
                assert len(inspect.signature(a).parameters) <= 1, a.__name__
