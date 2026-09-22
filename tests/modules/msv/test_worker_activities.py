"""build_bound_activities — MSV worker dependency injection.

Never exercised by any test before (no test file existed). A full read of the file found every single
dependency constructed with the wrong signature:
  - SignatoryRegistry() called with no args (needs redis_client, db_pool, config_service)
  - AccountEnroller() called with no args (needs cbs_connector, embedding_model, registry, progress_tracker)
  - SignatureDetector() / SignatureEmbeddingModel() called with no args (need vllm_client)
  - shared.cbs_connector.factory.build_cbs_connector does not exist (no factory.py in that package)
  - ImmudbClient.connect(collection=...) — the real signature needs host, port, bank_id, username=, password=
Every one of these was silently swallowed by a bare `except Exception`, so the MSV orchestrator, enroller and
audit writer have never actually initialised in any real run — every activity call degraded to its
"unavailable" AMBER/None path regardless of whether real infra was reachable.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.msv.worker_activities import build_bound_activities


def _fake_config_service(**secrets):
    cfg = MagicMock()
    cfg.get_platform = MagicMock(side_effect=lambda k: {
        "cbs_connector_type": "dev_stub", "cbs.connector.type": "dev_stub", "cbs.base_url": "http://cbs.local",
        "immudb.host": "localhost", "immudb.port": "3322", "vllm.url": "http://vllm.local",
    }.get(k, MagicMock()))
    cfg.get_secret = AsyncMock(side_effect=lambda k: secrets.get(k, "secret-value"))
    cfg.get = AsyncMock(side_effect=lambda k: {"vllm.url": "http://vllm.local"}.get(k, "x"))
    return cfg


@pytest.mark.asyncio
async def test_signatory_registry_constructed_with_redis_db_and_config():
    with patch("modules.msv.vaults.signatory_registry.SignatoryRegistry") as MockRegistry, \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        await build_bound_activities("kbl", _fake_config_service())
        # Called twice by design — orchestrator and enroller each get an independent registry
        # instance, so a failure building one never takes the other down.
        assert MockRegistry.call_count == 2
        for args, kwargs in [c.args + (tuple(c.kwargs.values()),) if False else (c.args, c.kwargs)
                             for c in MockRegistry.call_args_list]:
            all_args = args + tuple(kwargs.values())
            assert "DB_POOL" in all_args and "REDIS" in all_args


@pytest.mark.asyncio
async def test_account_enroller_constructed_with_four_real_dependencies():
    with patch("modules.msv.enrollment.account_enroller.AccountEnroller") as MockEnroller, \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        await build_bound_activities("kbl", _fake_config_service())
        MockEnroller.assert_called_once()
        args, kwargs = MockEnroller.call_args
        assert len(args) + len(kwargs) == 4


@pytest.mark.asyncio
async def test_signature_detector_and_embedding_model_get_a_vllm_client():
    with patch("modules.msv.ai.signature_detector.SignatureDetector") as MockDetector, \
         patch("modules.msv.ai.embedding_model.SignatureEmbeddingModel") as MockEmbed, \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        await build_bound_activities("kbl", _fake_config_service())
        MockDetector.assert_called_once()
        assert MockDetector.call_args.args[0] is not None
        # Called twice by design — orchestrator and enroller each get an independent embedding model.
        assert MockEmbed.call_count == 2
        for c in MockEmbed.call_args_list:
            assert c.args[0] is not None


@pytest.mark.asyncio
async def test_cbs_connector_uses_the_real_shared_connector_classes_not_a_nonexistent_factory():
    with patch("shared.cbs_connector.dev_stub.DevStubCBSConnector") as MockConnector, \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        instance = MockConnector.return_value
        instance.connect = MagicMock()
        await build_bound_activities("kbl", _fake_config_service())
        MockConnector.assert_called_once()


@pytest.mark.asyncio
async def test_immudb_client_connect_called_with_host_port_and_credentials():
    with patch("shared.audit.immudb_client.ImmudbClient") as MockImmudb, \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        await build_bound_activities("kbl", _fake_config_service())
        MockImmudb.return_value.connect.assert_called_once()
        _, kwargs = MockImmudb.return_value.connect.call_args
        assert kwargs.get("host") and kwargs.get("port") and kwargs.get("username") and kwargs.get("password")


@pytest.mark.asyncio
async def test_one_failed_dependency_does_not_prevent_others_from_building():
    with patch("modules.msv.vaults.signatory_registry.SignatoryRegistry", side_effect=RuntimeError("boom")), \
         patch("modules.msv.worker_activities._build_db_pool", new=AsyncMock(return_value="DB_POOL")), \
         patch("modules.msv.worker_activities._build_redis_client", new=AsyncMock(return_value="REDIS")):
        bound = await build_bound_activities("kbl", _fake_config_service())
        # orchestrator depends on registry, so it degrades too — but the call must not raise
        assert bound is not None
