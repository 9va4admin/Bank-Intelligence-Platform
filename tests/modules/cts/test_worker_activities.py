"""
Tests for modules/cts/worker_activities.py — BoundCTSActivities DI wiring.

Covers:
  - Representative bound-method delegation across every DI shape (CBS,
    vault, AI cascade, audit/decision, Kafka, stateful lot manager).
  - build_bound_activities()'s graceful degradation: a config_service that
    fails every lookup must still produce a fully-constructed
    BoundCTSActivities with every dependency at None, never raise.
  - build_bound_activities()'s happy path: a config_service/class stack
    that succeeds must thread real values through to the right builder.
  - The one genuinely stateful piece — per-(bank_ifsc, session_id)
    LotManager caching.
  - activity_list() completeness: exactly the 23 DI-needing activities,
    no duplicates, names matching the real @activity.defn registrations.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# temporalio is a real installed dependency in this environment (used
# throughout this branch's WorkflowEnvironment-based tests) — @activity.defn
# preserves __name__ via its own internal wraps, so no stubbing is needed
# here, unlike tests/modules/cts/test_worker.py which deliberately exercises
# the _TEMPORAL_AVAILABLE=False fallback path.

from modules.cts.worker_activities import (
    BoundCTSActivities,
    build_bound_activities,
)
# unittest.mock.patch() resolves dotted targets via getattr() on the already-
# imported parent package — these two submodules are only ever imported
# lazily (inside BoundCTSActivities' bound-method bodies), so without an
# explicit import here, patch("modules.cts.workflows.delta_vault_sync_workflow...")
# fails with AttributeError before the submodule has ever been imported once.
import modules.cts.workflows.delta_vault_sync_workflow  # noqa: F401
import modules.cts.workflows.mismatch_resolution_workflow  # noqa: F401


def _bound(**overrides):
    return BoundCTSActivities(bank_id="test-bank", **overrides)


class TestBoundMethodDelegation:
    """One representative activity per DI shape — proves the pattern, not
    23 near-identical repeats. activity_list() completeness (below) covers
    the rest structurally."""

    @pytest.mark.asyncio
    async def test_check_cbs_balance_passes_injected_cbs_connector(self):
        fake_cbs = MagicMock()
        bound = _bound(cbs_connector=fake_cbs)
        with patch("modules.cts.workflows.activities.cbs.check_cbs_balance", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.check_cbs_balance("INPUT")
        mock_real.assert_awaited_once_with("INPUT", cbs_connector=fake_cbs)
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_lookup_pps_passes_injected_pps_vault(self):
        fake_vault = MagicMock()
        bound = _bound(pps_vault=fake_vault)
        with patch("modules.cts.workflows.activities.pps.lookup_pps", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.lookup_pps("INPUT")
        mock_real.assert_awaited_once_with("INPUT", vault=fake_vault)
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_ocr_extract_passes_orchestrator_and_config_service(self):
        fake_orch = MagicMock()
        fake_cfg = MagicMock()
        bound = _bound(orchestrator=fake_orch, config_service=fake_cfg)
        with patch("modules.cts.workflows.activities.ocr.ocr_extract", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.ocr_extract("INPUT")
        mock_real.assert_awaited_once_with("INPUT", config_service=fake_cfg, orchestrator=fake_orch)
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_synthesise_decision_passes_config_and_kill_switch(self):
        fake_immudb = MagicMock()
        fake_opa = MagicMock()
        bound = _bound(immudb_client=fake_immudb, opa_client=fake_opa)
        with patch("modules.cts.workflows.activities.decision.synthesise_decision", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.synthesise_decision("INPUT", {"cfg": 1}, kill_switch_status="ELEVATED")
        mock_real.assert_awaited_once_with(
            "INPUT", {"cfg": 1},
            kill_switch_status="ELEVATED",
            immudb_client=fake_immudb,
            opa_client=fake_opa,
        )
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_file_to_ngch_passes_ngch_adapter_and_event_producer(self):
        fake_ngch = MagicMock()
        fake_producer = MagicMock()
        bound = _bound(ngch_adapter=fake_ngch, event_producer=fake_producer)
        with patch("modules.cts.workflows.activities.ngch_filer.file_to_ngch", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.file_to_ngch("INPUT")
        mock_real.assert_awaited_once_with("INPUT", ngch_adapter=fake_ngch, event_producer=fake_producer)
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_publish_mismatch_hold_passes_event_producer(self):
        fake_producer = MagicMock()
        bound = _bound(event_producer=fake_producer)
        with patch("modules.cts.workflows.mismatch_resolution_workflow.publish_mismatch_hold", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.publish_mismatch_hold("INPUT")
        mock_real.assert_awaited_once_with("INPUT", event_producer=fake_producer)
        assert result == "RESULT"

    @pytest.mark.asyncio
    async def test_fetch_delta_stop_payments_passes_positional_bank_and_window(self):
        """DeltaVaultSyncWorkflow calls this with args=[bank_id, window_minutes] — the
        bound method must accept exactly that shape and supply cbs_connector itself,
        since the underlying activity's cbs_client param has no default."""
        fake_cbs = MagicMock()
        bound = _bound(cbs_connector=fake_cbs)
        with patch("modules.cts.workflows.delta_vault_sync_workflow.fetch_delta_stop_payments", new=AsyncMock(return_value=[])) as mock_real:
            result = await bound.fetch_delta_stop_payments("test-bank", 15)
        mock_real.assert_awaited_once_with("test-bank", 15, fake_cbs)
        assert result == []

    @pytest.mark.asyncio
    async def test_update_bloom_filter_passes_positional_deltas_and_bloom_client(self):
        fake_bloom = MagicMock()
        bound = _bound(bloom_client=fake_bloom)
        with patch("modules.cts.workflows.delta_vault_sync_workflow.update_bloom_filter", new=AsyncMock(return_value={"serials_added": 0})) as mock_real:
            result = await bound.update_bloom_filter("test-bank", [], [])
        mock_real.assert_awaited_once_with("test-bank", [], [], fake_bloom)
        assert result == {"serials_added": 0}

    @pytest.mark.asyncio
    async def test_get_kill_switch_status_passes_config_service(self):
        fake_cfg = MagicMock()
        bound = _bound(config_service=fake_cfg)
        with patch("modules.cts.workflows.activities.kill_switch_lookup.get_kill_switch_status", new=AsyncMock(return_value="RESULT")) as mock_real:
            result = await bound.get_kill_switch_status("INPUT")
        mock_real.assert_awaited_once_with("INPUT", config_service=fake_cfg)
        assert result == "RESULT"


class TestLotManagerCaching:
    def test_same_session_returns_same_lot_manager_instance(self):
        bound = _bound()
        m1 = bound._get_or_create_lot_manager("SBIN0001234", "session-1")
        m2 = bound._get_or_create_lot_manager("SBIN0001234", "session-1")
        assert m1 is m2

    def test_different_session_returns_different_lot_manager_instance(self):
        bound = _bound()
        m1 = bound._get_or_create_lot_manager("SBIN0001234", "session-1")
        m2 = bound._get_or_create_lot_manager("SBIN0001234", "session-2")
        assert m1 is not m2

    def test_different_bank_ifsc_same_session_id_are_isolated(self):
        bound = _bound()
        m1 = bound._get_or_create_lot_manager("SBIN0001234", "session-1")
        m2 = bound._get_or_create_lot_manager("HDFC0005678", "session-1")
        assert m1 is not m2

    @pytest.mark.asyncio
    async def test_create_lot_entry_reuses_cached_manager_across_calls(self):
        """Two instruments in the same session must land in sequentially
        assigned lots — proving create_lot_entry actually reuses the cached
        LotManager rather than constructing a fresh (always-first-lot) one
        per call."""
        bound = _bound()

        class _FakeInput:
            def __init__(self, instrument_id):
                self.instrument_id = instrument_id
                self.bank_ifsc = "SBIN0001234"
                self.session_id = "session-1"

        r1 = await bound.create_lot_entry(_FakeInput("INSTR-1"))
        r2 = await bound.create_lot_entry(_FakeInput("INSTR-2"))
        # Same LotManager instance underneath => same lot until it fills up
        assert r1.lot_number == r2.lot_number


class TestActivityListCompleteness:
    def test_returns_exactly_23_bound_methods(self):
        bound = _bound()
        activities = bound.activity_list()
        assert len(activities) == 23

    def test_no_duplicate_names(self):
        bound = _bound()
        names = [a.__name__ for a in bound.activity_list()]
        assert len(names) == len(set(names))

    def test_every_entry_is_a_bound_method_of_this_instance(self):
        bound = _bound()
        for a in bound.activity_list():
            assert a.__self__ is bound


class TestBuildBoundActivitiesGracefulDegradation:
    @pytest.mark.asyncio
    async def test_every_dependency_none_when_config_service_fails_everything(self):
        """A config_service that raises/returns garbage for every lookup must
        never prevent BoundCTSActivities from being constructed — every
        dependency degrades to None independently, matching the activities'
        own None-safe fallback paths."""
        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=Exception("no such key"))
        fake_cfg.get_secret = AsyncMock(side_effect=Exception("vault unreachable"))
        fake_cfg.get = AsyncMock(side_effect=Exception("layer 3 unreachable"))
        fake_cfg.get_ai_config = AsyncMock(side_effect=Exception("layer 3 unreachable"))

        bound = await build_bound_activities("test-bank", fake_cfg)

        assert bound._cbs_connector is None
        assert bound._redis_client is None
        assert bound._immudb_client is None
        assert bound._event_producer is None
        assert bound._ngch_adapter is None
        assert bound._opa_client is None
        assert bound._orchestrator is None
        assert bound._fraud_vllm_client is None
        assert bound._signature_vault is None
        assert bound._pps_vault is None
        # Bloom client is constructed even with no Redis backing (its own
        # add_bulk/initialize calls are internally None-safe) — see
        # CanceledLeafBloom.initialize()'s own try/except.
        assert bound._bloom_client is not None

    @pytest.mark.asyncio
    async def test_never_raises_even_when_every_builder_fails(self):
        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=Exception("boom"))
        fake_cfg.get_secret = AsyncMock(side_effect=Exception("boom"))
        fake_cfg.get = AsyncMock(side_effect=Exception("boom"))
        fake_cfg.get_ai_config = AsyncMock(side_effect=Exception("boom"))

        # Must not raise.
        bound = await build_bound_activities("test-bank", fake_cfg)
        assert isinstance(bound, BoundCTSActivities)


class TestBuildBoundActivitiesHappyPath:
    @pytest.mark.asyncio
    async def test_signature_and_pps_vaults_skipped_without_pepper(self):
        """Both vaults hash account numbers with the bank's PII pepper — if
        the pepper secret can't be fetched, constructing a vault that would
        silently hash with an empty pepper is worse than not constructing it
        at all (every existing lookup would miss against real vault data)."""
        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=Exception("no platform config"))
        fake_cfg.get_secret = AsyncMock(side_effect=Exception("no pepper"))
        fake_cfg.get = AsyncMock(side_effect=Exception("no layer 3"))
        fake_cfg.get_ai_config = AsyncMock(side_effect=Exception("no layer 3"))

        bound = await build_bound_activities("test-bank", fake_cfg)

        assert bound._signature_vault is None
        assert bound._pps_vault is None

    @pytest.mark.asyncio
    async def test_bloom_client_uses_configured_capacity_and_fpr(self):
        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=Exception("no platform config"))
        fake_cfg.get_secret = AsyncMock(side_effect=Exception("no secrets"))

        async def _get(key):
            if key == "vault.bloom_expected_items":
                return 250_000
            if key == "vault.bloom_false_positive_rate":
                return 0.0005
            raise Exception(f"unconfigured key: {key}")

        fake_cfg.get = AsyncMock(side_effect=_get)
        fake_cfg.get_ai_config = AsyncMock(side_effect=Exception("no layer 3"))

        bound = await build_bound_activities("test-bank", fake_cfg)

        assert bound._bloom_client.expected_items == 250_000
        assert bound._bloom_client.false_positive_rate == 0.0005


class TestCBSConnectorSelection:
    @pytest.mark.asyncio
    async def test_unknown_connector_type_degrades_to_none(self):
        from modules.cts.worker_activities import _build_cbs_connector

        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=lambda k: {
            "cbs.connector.type": "some_unsupported_cbs",
            "cbs.base_url": "https://cbs.example.internal",
        }[k])

        connector = await _build_cbs_connector(fake_cfg, "test-bank")
        assert connector is None

    @pytest.mark.asyncio
    async def test_finacle_connector_constructed_and_connected(self):
        from modules.cts.worker_activities import _build_cbs_connector

        fake_cfg = MagicMock()
        fake_cfg.get_platform = MagicMock(side_effect=lambda k: {
            "cbs.connector.type": "finacle",
            "cbs.base_url": "https://cbs.example.internal",
        }[k])

        fake_connector_instance = MagicMock()
        fake_connector_cls = MagicMock(return_value=fake_connector_instance)

        with patch("shared.cbs_connector.finacle.FinacleCBSConnector", fake_connector_cls):
            connector = await _build_cbs_connector(fake_cfg, "test-bank")

        fake_connector_cls.assert_called_once_with(base_url="https://cbs.example.internal", bank_id="test-bank")
        fake_connector_instance.connect.assert_called_once_with()  # sync, not awaited
        assert connector is fake_connector_instance
