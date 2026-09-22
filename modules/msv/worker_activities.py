"""
BoundMSVActivities — worker-level dependency injection for MSV activities.

MSV has three activities that need real external dependencies:
  - orchestrate_msv_validation: needs SignatureOrchestrator (detector + embedding model
      + signatory registry + BRE engine)
  - write_audit:                needs AsyncImmudbWriter
  - sync_signatories_from_cbs:  needs CBS connector + AccountEnroller

functools.partial does not work for this: Temporal's Worker() inspects a
registered callable for @activity.defn metadata on the underlying function
object, and a partial-wrapped callable doesn't expose it. The correct pattern
is activities as bound methods on a class instance — each method is decorated
@activity.defn(name="<original free function's name>") so Temporal dispatches
to it under the exact same name the workflow calls.

Each real dependency is constructed independently; one failing must never
prevent others from starting. Failed dependency → None → activity's own
graceful-degradation path already handles None.

2026-09-22 rewrite: every dependency construction below was previously called with the wrong
constructor signature (SignatoryRegistry(), AccountEnroller(), SignatureDetector(),
SignatureEmbeddingModel() all with zero args; a nonexistent shared.cbs_connector.factory module;
ImmudbClient.connect(collection=...) missing host/port/username/password) — all silently swallowed
by broad except blocks, so this module has never actually initialised a working dependency in any
real run. No test file existed for it before today.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from temporalio import activity

from modules.msv.mandates.models import MSVOutcome, MSVOutput
from modules.msv.workflows.activities.write_audit import WriteAuditInput, WriteAuditResult
from modules.msv.workflows.activities.cbs_sync import CBSSyncInput, CBSSyncResult
from modules.msv.workflows.msv_workflow import MSVWorkflowInput

log = structlog.get_logger()


class BoundMSVActivities:
    """
    Holds real dependencies for MSV activities. Registered as a Worker()
    activity instance — Temporal calls the bound methods.
    """

    def __init__(
        self,
        orchestrator=None,
        immudb_client=None,
        cbs_connector=None,
        enroller=None,
    ) -> None:
        self._orchestrator = orchestrator
        self._immudb_client = immudb_client
        self._cbs_connector = cbs_connector
        self._enroller = enroller

    @activity.defn(name="orchestrate_msv_validation")
    async def orchestrate_msv_validation(self, inp: MSVWorkflowInput) -> MSVOutput:
        if self._orchestrator is None:
            log.warning(
                "msv.bound_orchestrate.no_orchestrator",
                instrument_id=inp.msv_input.instrument_id,
                bank_id=inp.msv_input.bank_id,
            )
            return MSVOutput(
                outcome=MSVOutcome.AMBER,
                confidence=0.0,
                reason_code="ORCHESTRATOR_UNAVAILABLE",
                reason_message=(
                    "SignatureOrchestrator not available at worker startup — "
                    "routing to human review."
                ),
                matched_signatories=[],
                detected_sig_count=0,
                mandate_rule_type="UNKNOWN",
            )
        return await self._orchestrator.validate(inp.msv_input, inp.account_meta)

    @activity.defn(name="write_audit")
    async def write_audit(self, inp: WriteAuditInput) -> WriteAuditResult:
        from modules.msv.workflows.activities.write_audit import write_audit as _free_fn
        return await _free_fn(inp, immudb_client=self._immudb_client)

    @activity.defn(name="sync_signatories_from_cbs")
    async def sync_signatories_from_cbs(self, inp: CBSSyncInput) -> CBSSyncResult:
        from modules.msv.workflows.activities.cbs_sync import sync_signatories_from_cbs as _free_fn
        return await _free_fn(
            inp,
            cbs_connector=self._cbs_connector,
            enroller=self._enroller,
        )

    def activity_list(self) -> list:
        return [
            self.orchestrate_msv_validation,
            self.write_audit,
            self.sync_signatories_from_cbs,
        ]


async def _get_pii_pepper(config_service: Any, bank_id: str) -> str:
    try:
        return await config_service.get_secret("pii_hash_pepper")
    except Exception as exc:
        log.warning("msv.worker.pii_pepper_unavailable", bank_id=bank_id, error=str(exc))
        return ""


async def _build_db_pool(config_service: Any) -> Any:
    """asyncpg pool for the msv schema tables — same DSN as CTS (one YugabyteDB cluster,
    separate schema, per infra/migrations/msv/20260709_create_msv_schema.py)."""
    try:
        import asyncpg
        dsn = await config_service.get_secret("db.cts.dsn")
        from shared.db.codecs import register_lenient_codecs
        pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=30,
                                         init=register_lenient_codecs)
        log.info("msv.worker.db_pool_ready")
        return pool
    except Exception as exc:
        log.warning("msv.worker.db_pool_unavailable", error=str(exc))
        return None


async def _build_redis_client(config_service: Any) -> Any:
    try:
        import redis.asyncio as aioredis
        redis_url = await config_service.get_secret("redis.cts.url")
        client = aioredis.from_url(redis_url, decode_responses=False)
        await client.ping()
        log.info("msv.worker.redis_client_ready")
        return client
    except Exception as exc:
        log.warning("msv.worker.redis_client_unavailable", error=str(exc))
        return None


async def _build_immudb_client(config_service: Any, bank_id: str) -> Any:
    try:
        from shared.audit.immudb_client import ImmudbClient
        from shared.audit.immudb_writer import AsyncImmudbWriter
        host = config_service.get_platform("immudb.host")
        port = int(config_service.get_platform("immudb.port"))
        username = await config_service.get_secret("immudb.username")
        password = await config_service.get_secret("immudb.password")
        client = ImmudbClient()
        client.connect(host=host, port=port, bank_id=bank_id, collection=f"msv_{bank_id}",
                       username=username, password=password)  # sync — immudb-py is sync
        log.info("msv.worker.immudb_ready", bank_id=bank_id)
        return AsyncImmudbWriter(client)
    except Exception as exc:
        log.warning("msv.worker.immudb_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_cbs_connector(config_service: Any, bank_id: str) -> Any:
    """Same _CONNECTOR_CLASSES pattern as modules/cts/worker_activities.py._build_cbs_connector —
    the module this used to import (shared.cbs_connector.factory) does not exist."""
    from shared.cbs_connector.finacle import FinacleCBSConnector
    from shared.cbs_connector.bancs import BaNCSCBSConnector
    from shared.cbs_connector.flexcube import FlexCubeCBSConnector
    from shared.cbs_connector.dev_stub import DevStubCBSConnector

    _CONNECTOR_CLASSES = {
        "finacle": FinacleCBSConnector,
        "bancs": BaNCSCBSConnector,
        "flexcube": FlexCubeCBSConnector,
        "dev_stub": DevStubCBSConnector,   # dev/test only — refuses outside ASTRA_ENV=development
    }
    try:
        connector_type = config_service.get_platform("cbs.connector.type")
        base_url = config_service.get_platform("cbs.base_url")
        cls = _CONNECTOR_CLASSES.get(connector_type.lower())
        if cls is None:
            log.warning("msv.worker.cbs_connector_unknown_type", connector_type=connector_type)
            return None
        pepper = await _get_pii_pepper(config_service, bank_id)
        connector = cls(base_url=base_url, bank_id=bank_id, pepper=pepper)
        connector.connect()  # sync — all three CBS connectors expose a sync connect()
        log.info("msv.worker.cbs_ready", bank_id=bank_id, cbs_type=connector_type)
        return connector
    except Exception as exc:
        log.warning("msv.worker.cbs_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_vllm_client(config_service: Any) -> Any:
    """OpenAI-compatible client shared by SignatureDetector and SignatureEmbeddingModel — same
    vLLM server as CTS, MSV-specific queues (msv-detect / msv-embeddings) passed per-call."""
    try:
        from openai import AsyncOpenAI
        base_url = await config_service.get("vllm.url")
        client = AsyncOpenAI(base_url=f"{base_url.rstrip('/')}/v1", api_key="x-istio", max_retries=0)
        log.info("msv.worker.vllm_client_ready")
        return client
    except Exception as exc:
        log.warning("msv.worker.vllm_client_unavailable", error=str(exc))
        return None


async def build_bound_activities(
    bank_id: str,
    config_service=None,
) -> BoundMSVActivities:
    """
    Construct real dependencies for MSV activities.

    Each dependency is built independently — one failure must not prevent
    the others from starting. Failed dependency is left None; the activity's
    own graceful-degradation path handles None at call time.
    """
    orchestrator = None
    immudb_client = None
    cbs_connector = None
    enroller = None

    db_pool = await _build_db_pool(config_service) if config_service else None
    redis_client = await _build_redis_client(config_service) if config_service else None

    # ── Immudb writer ────────────────────────────────────────────────────────
    if config_service:
        immudb_client = await _build_immudb_client(config_service, bank_id)

    # ── CBS connector ────────────────────────────────────────────────────────
    if config_service:
        cbs_connector = await _build_cbs_connector(config_service, bank_id)

    # ── SignatureOrchestrator (needs detector + embedding model + registry + BRE) ─
    try:
        from modules.msv.orchestrator import SignatureOrchestrator
        from modules.msv.ai.signature_detector import SignatureDetector
        from modules.msv.ai.embedding_model import SignatureEmbeddingModel
        from modules.msv.vaults.signatory_registry import SignatoryRegistry
        from modules.msv.mandates.bre_engine import BREEngine

        vllm_client = await _build_vllm_client(config_service) if config_service else None
        detector = SignatureDetector(vllm_client)
        embedding_model = SignatureEmbeddingModel(vllm_client)
        registry = SignatoryRegistry(redis_client, db_pool, config_service)
        bre_engine = BREEngine()
        orchestrator = SignatureOrchestrator(
            detector=detector,
            embedding_model=embedding_model,
            registry=registry,
            bre_engine=bre_engine,
            single_sig_validator=None,  # single-sig path uses orchestrator directly
        )
        log.info("msv.worker.orchestrator_ready", bank_id=bank_id)
    except Exception as exc:
        log.warning("msv.worker.orchestrator_unavailable", bank_id=bank_id, error=str(exc))

    # ── AccountEnroller ──────────────────────────────────────────────────────
    try:
        from modules.msv.enrollment.account_enroller import AccountEnroller
        from modules.msv.enrollment.progress_tracker import EnrollmentProgressTracker
        from modules.msv.ai.signature_detector import SignatureDetector
        from modules.msv.ai.embedding_model import SignatureEmbeddingModel
        from modules.msv.vaults.signatory_registry import SignatoryRegistry

        # Independent instances from the orchestrator's — a failure building the orchestrator above
        # must not also take down enrollment (and vice versa).
        enroll_vllm_client = await _build_vllm_client(config_service) if config_service else None
        enroll_embedding_model = SignatureEmbeddingModel(enroll_vllm_client)
        enroll_registry = SignatoryRegistry(redis_client, db_pool, config_service)
        progress_tracker = EnrollmentProgressTracker(db_pool)
        enroller = AccountEnroller(cbs_connector, enroll_embedding_model, enroll_registry, progress_tracker)
        log.info("msv.worker.enroller_ready", bank_id=bank_id)
    except Exception as exc:
        log.warning("msv.worker.enroller_unavailable", bank_id=bank_id, error=str(exc))

    return BoundMSVActivities(
        orchestrator=orchestrator,
        immudb_client=immudb_client,
        cbs_connector=cbs_connector,
        enroller=enroller,
    )
