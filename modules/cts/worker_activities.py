"""
BoundCTSActivities — worker-level dependency injection for CTS activities.

Every CTS activity function takes its real external dependency (CBS
connector, Redis client, Immudb client, Kafka producer, vLLM cascade
orchestrator, OPA client, signature/PPS vault, Bloom filter, LotManager)
as a `=None` keyword default — by design, so the activity's own
graceful-degradation path (see .claude/rules/temporal.md) is exercised
whenever a dependency genuinely isn't available. Until this file, nothing
ever supplied a real instance: Worker() always registered the bare
functions, so every activity ran with every dependency at its None
default in any real Temporal execution — decorators and dispatch were
fixed in three prior commits on this branch, but nothing behind them was
real yet.

functools.partial does NOT work for this: Temporal's Worker() inspects a
registered callable for @activity.defn metadata attached to the
underlying function object, and a partial-wrapped callable doesn't expose
it (confirmed empirically against the installed temporalio version — see
project memory "production wiring campaign"). The correct, supported
pattern is activities as bound methods on a class instance: this class
holds the real, already-connected dependencies, and each method is
decorated @activity.defn(name="<original activity's registered name>")
so Temporal dispatches to it under the exact same name every workflow
already calls via workflow.execute_activity(original_free_function, ...)
— Temporal resolves activities by name string, not Python object
identity (already proven throughout this branch's tests by every
@activity.defn(name="...") test double).

Each real dependency is constructed independently with its own
try/except in build_bound_activities(): one bank's CBS being unreachable
at worker startup must never prevent Redis/Kafka/Immudb from coming up
too, and every one of these dependencies already has its own None-safe
graceful-degradation path inside the activity it's injected into. A
dependency that fails to construct is logged at WARNING and left None —
never silent, never a startup crash.

Explicitly NOT wired here (flagged, not faked — see project memory):
  - model/explainer (score_fraud's XGBoost + SHAP) and model
    (verify_signature's Siamese network): no trained model artifact or
    loader exists anywhere in the repo. This is a data-science delivery
    gap, not a wiring gap — already degrades to a documented rule-based
    fallback (fraud.py) with SHAP always populated.
  - smb_proxy: designed as an external Go binary/MCP service, not built
    in this repo. Already degrades to the local vault.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from temporalio import activity

# Input/result types imported at module level so Temporal's get_type_hints()
# can resolve the string annotations produced by `from __future__ import
# annotations` — TYPE_CHECKING imports would be invisible at runtime and
# cause Temporal to fall back to plain-dict deserialization.
from modules.cts.workflows.activities.alteration import AlterationActivityInput
from modules.cts.workflows.activities.cbs import CBSActivityInput
from modules.cts.workflows.activities.decision import DecisionInput
from modules.cts.workflows.activities.fraud import FraudActivityInput
from modules.cts.workflows.activities.kill_switch_lookup import KillSwitchLookupInput
from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
from modules.cts.workflows.activities.ocr import OCRActivityInput
from modules.cts.workflows.activities.outward_scan_activities import (
    LotAssignmentInput,
    VisionPresentmentCheckInput,
)
from modules.cts.workflows.activities.pps import PPSActivityInput
from modules.cts.workflows.activities.signature import SignatureActivityInput
from modules.cts.workflows.activities.stop_payment import StopPaymentActivityInput
from modules.cts.workflows.activities.write_audit import WriteAuditInput
from modules.cts.workflows.human_review_workflow import HumanReviewInput
from modules.cts.workflows.mismatch_resolution_workflow import PublishMismatchHoldInput

log = structlog.get_logger()


class BoundCTSActivities:
    def __init__(
        self,
        *,
        bank_id: str,
        cbs_connector: Any = None,
        redis_client: Any = None,
        immudb_client: Any = None,
        event_producer: Any = None,
        ngch_adapter: Any = None,
        opa_client: Any = None,
        signature_vault: Any = None,
        pps_vault: Any = None,
        bloom_client: Any = None,
        orchestrator: Any = None,
        fraud_vllm_client: Any = None,
        config_service: Any = None,
        db_pool: Any = None,
        hsm_signer: Any = None,
    ) -> None:
        self._bank_id = bank_id
        self._cbs_connector = cbs_connector
        self._redis_client = redis_client
        self._immudb_client = immudb_client
        self._event_producer = event_producer
        self._ngch_adapter = ngch_adapter
        self._opa_client = opa_client
        self._signature_vault = signature_vault
        self._pps_vault = pps_vault
        self._bloom_client = bloom_client
        self._orchestrator = orchestrator
        self._fraud_vllm_client = fraud_vllm_client
        self._config_service = config_service
        self._db_pool = db_pool
        self._hsm_signer = hsm_signer
        # LotManager is stateful/in-memory per clearing session (see
        # modules/cts/lot/manager.py) — cached by (bank_ifsc, session_id) so
        # sequential lot numbers are correct across a session's many
        # instruments, not one fresh (and therefore always-first-lot)
        # manager per activity call.
        self._lot_managers: dict[tuple[str, str], Any] = {}

    def _get_or_create_lot_manager(self, bank_ifsc: str, session_id: str):
        from datetime import datetime, timezone
        from modules.cts.lot.manager import LotManager

        key = (bank_ifsc, session_id)
        if key not in self._lot_managers:
            self._lot_managers[key] = LotManager(
                bank_ifsc=bank_ifsc,
                session_id=session_id,
                session_date=datetime.now(timezone.utc),
            )
        return self._lot_managers[key]

    # ------------------------------------------------------------------
    # CBS-backed
    # ------------------------------------------------------------------

    @activity.defn(name="check_cbs_balance")
    async def check_cbs_balance(self, inp: CBSActivityInput):
        from modules.cts.workflows.activities.cbs import check_cbs_balance as _real
        return await _real(inp, cbs_connector=self._cbs_connector)

    @activity.defn(name="check_account_status")
    async def check_account_status(self, inp: CBSActivityInput):
        from modules.cts.workflows.activities.cbs import check_account_status as _real
        return await _real(inp, cbs_connector=self._cbs_connector)

    @activity.defn(name="load_signatures_from_cbs")
    async def load_signatures_from_cbs(self, bank_id: str):
        from modules.cts.workflows.vault_sync_workflow import load_signatures_from_cbs as _real
        return await _real(bank_id, cbs_connector=self._cbs_connector)

    @activity.defn(name="load_pps_from_cbs")
    async def load_pps_from_cbs(self, bank_id: str):
        from modules.cts.workflows.vault_sync_workflow import load_pps_from_cbs as _real
        return await _real(bank_id, cbs_connector=self._cbs_connector)

    # ------------------------------------------------------------------
    # Signature / PPS vaults (Redis-backed)
    # ------------------------------------------------------------------

    @activity.defn(name="lookup_pps")
    async def lookup_pps(self, inp: PPSActivityInput):
        from modules.cts.workflows.activities.pps import lookup_pps as _real
        return await _real(inp, vault=self._pps_vault)

    @activity.defn(name="verify_signature")
    async def verify_signature(self, inp: SignatureActivityInput):
        from modules.cts.workflows.activities.signature import verify_signature as _real
        # smb_proxy intentionally omitted — external service, not built in
        # this repo yet (see module docstring). model intentionally
        # omitted — no trained Siamese network artifact exists.
        return await _real(
            inp,
            vault=self._signature_vault,
            cbs_connector=self._cbs_connector,
            config_service=self._config_service,
        )

    # ------------------------------------------------------------------
    # Redis vault sync (full + delta)
    # ------------------------------------------------------------------

    @activity.defn(name="warm_redis_vault")
    async def warm_redis_vault(self, bank_id: str, pepper: str, signature_records, pps_records):
        from modules.cts.workflows.vault_sync_workflow import warm_redis_vault as _real
        return await _real(bank_id, pepper, signature_records, pps_records, redis_client=self._redis_client)

    @activity.defn(name="verify_vault_integrity")
    async def verify_vault_integrity(self, bank_id: str, pepper: str, sample_accounts):
        from modules.cts.workflows.vault_sync_workflow import verify_vault_integrity as _real
        return await _real(bank_id, pepper, sample_accounts, redis_client=self._redis_client)

    # ------------------------------------------------------------------
    # Stop payment (CBS + Bloom filter)
    # ------------------------------------------------------------------

    @activity.defn(name="check_stop_payment")
    async def check_stop_payment(self, inp: StopPaymentActivityInput):
        from modules.cts.workflows.activities.stop_payment import check_stop_payment as _real
        return await _real(inp, cbs_connector=self._cbs_connector, bloom_client=self._bloom_client)

    # ------------------------------------------------------------------
    # Delta vault sync (15-min stop-payment + canceled-leaf Bloom refresh)
    # ------------------------------------------------------------------

    @activity.defn(name="fetch_delta_stop_payments")
    async def fetch_delta_stop_payments(self, bank_id: str, window_minutes: int):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_stop_payments as _real
        return await _real(bank_id, window_minutes, self._cbs_connector)

    @activity.defn(name="fetch_delta_canceled_leaves")
    async def fetch_delta_canceled_leaves(self, bank_id: str, window_minutes: int):
        from modules.cts.workflows.delta_vault_sync_workflow import fetch_delta_canceled_leaves as _real
        return await _real(bank_id, window_minutes, self._cbs_connector)

    @activity.defn(name="update_bloom_filter")
    async def update_bloom_filter(self, bank_id: str, stop_payment_deltas, canceled_leaf_deltas):
        from modules.cts.workflows.delta_vault_sync_workflow import update_bloom_filter as _real
        return await _real(bank_id, stop_payment_deltas, canceled_leaf_deltas, self._bloom_client)

    # ------------------------------------------------------------------
    # AI (vLLM L1/L2 cascade)
    # ------------------------------------------------------------------

    @activity.defn(name="ocr_extract")
    async def ocr_extract(self, inp: OCRActivityInput):
        from modules.cts.workflows.activities.ocr import ocr_extract as _real
        return await _real(inp, config_service=self._config_service, orchestrator=self._orchestrator)

    @activity.defn(name="detect_alteration")
    async def detect_alteration(self, inp: AlterationActivityInput, kill_switch_status=None):
        from modules.cts.workflows.activities.alteration import detect_alteration as _real
        # hsm intentionally omitted — no real implementation exists yet.
        return await _real(
            inp,
            kill_switch_status=kill_switch_status,
            immudb_client=self._immudb_client,
            orchestrator=self._orchestrator,
            config_service=self._config_service,
        )

    @activity.defn(name="score_fraud")
    async def score_fraud(self, inp: FraudActivityInput):
        from modules.cts.workflows.activities.fraud import score_fraud as _real
        # model/explainer intentionally omitted — no trained artifact
        # exists; the activity's own rule-based fallback handles this.
        return await _real(inp, vllm_client=self._fraud_vllm_client, config_service=self._config_service)

    @activity.defn(name="run_vision_presentment_check")
    async def run_vision_presentment_check(self, inp: VisionPresentmentCheckInput):
        from modules.cts.workflows.activities.outward_scan_activities import (
            run_vision_presentment_check as _real,
        )
        return await _real(inp, orchestrator=self._orchestrator)

    # ------------------------------------------------------------------
    # Decision / audit / NGCH filing
    # ------------------------------------------------------------------

    @activity.defn(name="synthesise_decision")
    async def synthesise_decision(self, inp: DecisionInput, config: dict, kill_switch_status=None):
        from modules.cts.workflows.activities.decision import synthesise_decision as _real
        # hsm intentionally omitted — no real implementation exists yet.
        return await _real(
            inp, config,
            kill_switch_status=kill_switch_status,
            immudb_client=self._immudb_client,
            opa_client=self._opa_client,
        )

    @activity.defn(name="write_audit")
    async def write_audit(self, inp: WriteAuditInput):
        from modules.cts.workflows.activities.write_audit import write_audit as _real
        return await _real(inp, immudb_client=self._immudb_client, hsm=self._hsm_signer)

    @activity.defn(name="file_to_ngch")
    async def file_to_ngch(self, inp: NGCHFilerInput):
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch as _real
        return await _real(inp, ngch_adapter=self._ngch_adapter, event_producer=self._event_producer)

    # ------------------------------------------------------------------
    # Kafka-backed notifications / mismatch hold
    # ------------------------------------------------------------------

    @activity.defn(name="push_to_review_queue")
    async def push_to_review_queue(self, inp: HumanReviewInput):
        from modules.cts.workflows.human_review_workflow import push_to_review_queue as _real
        return await _real(inp, event_producer=self._event_producer)

    @activity.defn(name="publish_mismatch_hold")
    async def publish_mismatch_hold(self, inp: PublishMismatchHoldInput):
        from modules.cts.workflows.mismatch_resolution_workflow import publish_mismatch_hold as _real
        return await _real(inp, event_producer=self._event_producer)

    # ------------------------------------------------------------------
    # Lot assignment (stateful, per-session)
    # ------------------------------------------------------------------

    @activity.defn(name="create_lot_entry")
    async def create_lot_entry(self, inp: LotAssignmentInput):
        from modules.cts.workflows.activities.outward_scan_activities import create_lot_entry as _real
        lot_manager = self._get_or_create_lot_manager(inp.bank_ifsc, inp.session_id)
        return await _real(inp, lot_manager=lot_manager)

    # ------------------------------------------------------------------
    # Kill switch (config_service only — cheap, no external I/O)
    # ------------------------------------------------------------------

    @activity.defn(name="get_kill_switch_status")
    async def get_kill_switch_status(self, inp: KillSwitchLookupInput):
        from modules.cts.workflows.activities.kill_switch_lookup import get_kill_switch_status as _real
        return await _real(inp, config_service=self._config_service)

    # ------------------------------------------------------------------
    # SMB forwarding hop (cts.smb_forwarding_log, cts.sub_member_banks)
    # ------------------------------------------------------------------

    @activity.defn(name="validate_smb_forwarding_window")
    async def validate_smb_forwarding_window(self, instrument_id, bank_id, sub_member_id, iet_deadline_utc):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            validate_smb_forwarding_window as _real,
        )
        return await _real(instrument_id, bank_id, sub_member_id, iet_deadline_utc, db=self._db_pool)

    @activity.defn(name="write_forwarding_log_start")
    async def write_forwarding_log_start(
        self, forwarding_id, instrument_id, bank_id, sub_member_id, micr_prefix_matched, iet_deadline_utc,
    ):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_start as _real,
        )
        return await _real(
            forwarding_id, instrument_id, bank_id, sub_member_id, micr_prefix_matched,
            iet_deadline_utc, db=self._db_pool,
        )

    @activity.defn(name="write_forwarding_log_complete")
    async def write_forwarding_log_complete(self, forwarding_id, bank_id, terminal_decision, smb_workflow_id):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_forwarding_log_complete as _real,
        )
        return await _real(forwarding_id, bank_id, terminal_decision, smb_workflow_id, db=self._db_pool)

    @activity.defn(name="write_smb_forwarding_audit")
    async def write_smb_forwarding_audit(self, forwarding_id, bank_id, terminal_decision, completion_type):
        from modules.cts.workflows.activities.smb_forwarding_activities import (
            write_smb_forwarding_audit as _real,
        )
        return await _real(
            forwarding_id, bank_id, terminal_decision, completion_type,
            immudb_client=self._immudb_client,
        )

    # ------------------------------------------------------------------
    # Sub-Member Bank notifications / risk shield (sub_member_batch_ledgers)
    # ------------------------------------------------------------------

    @activity.defn(name="notify_sub_member_return")
    async def notify_sub_member_return(
        self, instrument_id, bank_id, sub_member_id, return_reason, bucket, amount_range, cheque_number_suffix,
    ):
        from modules.cts.sub_member.activities import notify_sub_member_return as _real
        return await _real(
            instrument_id, bank_id, sub_member_id, return_reason, bucket, amount_range,
            cheque_number_suffix, event_producer=self._event_producer,
        )

    @activity.defn(name="emit_batch_ledger_update")
    async def emit_batch_ledger_update(self, bank_id, sub_member_id, session_date, clearing_session, bucket):
        from modules.cts.sub_member.activities import emit_batch_ledger_update as _real
        return await _real(bank_id, sub_member_id, session_date, clearing_session, bucket, db=self._db_pool)

    @activity.defn(name="check_return_rate_shield")
    async def check_return_rate_shield(
        self, bank_id, sub_member_id, session_date, clearing_session, mock_shield_status=None,
    ):
        from modules.cts.sub_member.activities import check_return_rate_shield as _real
        return await _real(
            bank_id, sub_member_id, session_date, clearing_session,
            mock_shield_status=mock_shield_status,
            db=self._db_pool, event_producer=self._event_producer, immudb_client=self._immudb_client,
        )

    # ------------------------------------------------------------------
    # Registration list — every bound method Worker() should dispatch to.
    # ------------------------------------------------------------------

    def activity_list(self) -> list:
        """All 30 DI-needing activities as bound methods, ready for
        Worker(activities=...). The one remaining registered CTS activity
        (validate_cts2010) takes no injectable dependency and is registered
        directly from worker.py as a bare function — see NO_DI_ACTIVITIES
        there."""
        return [
            self.check_cbs_balance,
            self.check_account_status,
            self.load_signatures_from_cbs,
            self.load_pps_from_cbs,
            self.lookup_pps,
            self.verify_signature,
            self.warm_redis_vault,
            self.verify_vault_integrity,
            self.check_stop_payment,
            self.fetch_delta_stop_payments,
            self.fetch_delta_canceled_leaves,
            self.update_bloom_filter,
            self.ocr_extract,
            self.detect_alteration,
            self.score_fraud,
            self.run_vision_presentment_check,
            self.synthesise_decision,
            self.write_audit,
            self.file_to_ngch,
            self.push_to_review_queue,
            self.publish_mismatch_hold,
            self.create_lot_entry,
            self.get_kill_switch_status,
            self.validate_smb_forwarding_window,
            self.write_forwarding_log_start,
            self.write_forwarding_log_complete,
            self.write_smb_forwarding_audit,
            self.notify_sub_member_return,
            self.emit_batch_ledger_update,
            self.check_return_rate_shield,
        ]


# ---------------------------------------------------------------------------
# Construction — one real dependency at a time, independently fail-safe.
# ---------------------------------------------------------------------------

async def build_bound_activities(bank_id: str, config_service: Any) -> BoundCTSActivities:
    """
    Constructs every real dependency BoundCTSActivities needs, logging a
    WARNING and leaving that one dependency None on failure rather than
    aborting worker startup — consistent with this codebase's established
    graceful-degradation philosophy (CLAUDE.md NFR section): one bank's
    CBS/OPA/Redis/Kafka/vLLM being unreachable must never prevent the
    others from coming up, and every dependency here is already None-safe
    inside the activity it's injected into.
    """
    cbs_connector = await _build_cbs_connector(config_service, bank_id)
    redis_client = await _build_redis_client(config_service)
    immudb_client = await _build_immudb_client(config_service, bank_id)
    event_producer = await _build_event_producer(config_service, bank_id)
    ngch_adapter = await _build_ngch_adapter(config_service, bank_id)
    opa_client = await _build_opa_client(config_service)
    orchestrator = await _build_cascade_orchestrator(config_service, bank_id)
    fraud_vllm_client = await _build_fraud_vllm_client(config_service)
    db_pool = await _build_db_pool(config_service)
    hsm_signer = _build_hsm_signer(config_service, bank_id)

    pepper = await _get_pii_pepper(config_service, bank_id)
    signature_vault = _build_signature_vault(bank_id, pepper, redis_client)
    pps_vault = _build_pps_vault(bank_id, pepper, redis_client)
    bloom_client = await _build_bloom_client(redis_client, bank_id, config_service)

    return BoundCTSActivities(
        bank_id=bank_id,
        cbs_connector=cbs_connector,
        redis_client=redis_client,
        immudb_client=immudb_client,
        event_producer=event_producer,
        ngch_adapter=ngch_adapter,
        opa_client=opa_client,
        signature_vault=signature_vault,
        pps_vault=pps_vault,
        bloom_client=bloom_client,
        orchestrator=orchestrator,
        fraud_vllm_client=fraud_vllm_client,
        config_service=config_service,
        db_pool=db_pool,
        hsm_signer=hsm_signer,
    )


async def _build_db_pool(config_service: Any) -> Any:
    """asyncpg pool for cts schema tables (sub_member_banks, smb_forwarding_log,
    sub_member_batch_ledgers) — same DSN key and pool sizing convention as
    apps/api/main.py's db_pool_cts and modules/cts/crl/service.py's CRLService."""
    try:
        import asyncpg
        dsn = await config_service.get_secret("db.cts.dsn")
        pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=30)
        log.info("worker_activities.db_pool_ready")
        return pool
    except Exception as exc:
        log.warning("worker_activities.db_pool_unavailable", error=str(exc))
        return None


async def _build_cbs_connector(config_service: Any, bank_id: str) -> Any:
    from shared.cbs_connector.finacle import FinacleCBSConnector
    from shared.cbs_connector.bancs import BaNCSCBSConnector
    from shared.cbs_connector.flexcube import FlexCubeCBSConnector

    _CONNECTOR_CLASSES = {
        "finacle": FinacleCBSConnector,
        "bancs": BaNCSCBSConnector,
        "flexcube": FlexCubeCBSConnector,
    }
    try:
        connector_type = config_service.get_platform("cbs.connector.type")
        base_url = config_service.get_platform("cbs.base_url")
        cls = _CONNECTOR_CLASSES.get(connector_type.lower())
        if cls is None:
            log.warning("worker_activities.cbs_connector_unknown_type", connector_type=connector_type)
            return None
        connector = cls(base_url=base_url, bank_id=bank_id)
        connector.connect()  # sync — all three CBS connectors expose a sync connect()
        log.info("worker_activities.cbs_connector_ready", connector_type=connector_type)
        return connector
    except Exception as exc:
        log.warning("worker_activities.cbs_connector_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_redis_client(config_service: Any) -> Any:
    try:
        import redis.asyncio as aioredis
        redis_url = await config_service.get_secret("redis.cts.url")
        client = aioredis.from_url(redis_url, decode_responses=False)
        await client.ping()
        log.info("worker_activities.redis_client_ready")
        return client
    except Exception as exc:
        log.warning("worker_activities.redis_client_unavailable", error=str(exc))
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
        client.connect(host=host, port=port, bank_id=bank_id, username=username, password=password)  # sync — immudb-py is sync
        log.info("worker_activities.immudb_client_ready")
        # write_audit.py (and every other caller) expects an async
        # .write(collection=, event_type=, bank_id=, ...) — the raw client
        # only has a sync write_event() with collection fixed at connect
        # time. Wrap it so the interface every activity already calls
        # actually exists.
        return AsyncImmudbWriter(client)
    except Exception as exc:
        log.warning("worker_activities.immudb_client_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_event_producer(config_service: Any, bank_id: str) -> Any:
    try:
        from shared.event_bus.producer import EventProducer
        bootstrap_servers = await config_service.get_secret("kafka.bootstrap_servers")
        producer = EventProducer(bootstrap_servers=bootstrap_servers, bank_id=bank_id, module="cts")
        producer.connect()  # sync — kafka-python is sync
        log.info("worker_activities.event_producer_ready")
        return producer
    except Exception as exc:
        log.warning("worker_activities.event_producer_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_ngch_adapter(config_service: Any, bank_id: str) -> Any:
    try:
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        base_url = config_service.get_platform("ngch.rest_base_url")
        adapter = NGCHAdapter(bank_id=bank_id, base_url=base_url)
        await adapter.connect(config_service=config_service)
        log.info("worker_activities.ngch_adapter_ready")
        return adapter
    except Exception as exc:
        log.warning("worker_activities.ngch_adapter_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_opa_client(config_service: Any) -> Any:
    try:
        import httpx
        from shared.opa_client import OPAClient
        opa_url = config_service.get_platform("opa.url")
        opa_client = OPAClient(opa_url=opa_url, http_client=httpx.AsyncClient(timeout=2.0))
        log.info("worker_activities.opa_client_ready")
        return opa_client
    except Exception as exc:
        log.warning("worker_activities.opa_client_unavailable", error=str(exc))
        return None


async def _build_cascade_orchestrator(config_service: Any, bank_id: str) -> Any:
    """One CascadeOrchestrator serves ocr_extract, detect_alteration, and
    run_vision_presentment_check — l1/l2 are generic vLLM-compatible
    clients; which model/queue is used is selected per-call inside the
    orchestrator (see shared/ai/model_cascade.py)."""
    try:
        from openai import AsyncOpenAI
        from shared.ai.model_cascade import CascadeOrchestrator

        l1_base_url = config_service.get_platform("vllm.l1_url")
        l2_base_url = config_service.get_platform("vllm.l2_url")
        l1_client = AsyncOpenAI(base_url=l1_base_url, api_key="astra-internal")
        l2_client = AsyncOpenAI(base_url=l2_base_url, api_key="astra-internal")
        ai_config = await config_service.get_ai_config(bank_id)
        orchestrator = CascadeOrchestrator(
            l1_client=l1_client, l2_client=l2_client, config=ai_config, bank_id=bank_id,
        )
        log.info("worker_activities.cascade_orchestrator_ready")
        return orchestrator
    except Exception as exc:
        log.warning("worker_activities.cascade_orchestrator_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_fraud_vllm_client(config_service: Any) -> Any:
    """score_fraud's vllm_client is only used for a post-hoc natural-
    language rationale (Llama 3.3 70B, cts-reasoning queue) — separate
    from the L1/L2 vision/OCR cascade and from the XGBoost score itself.

    apps/ai-server/ was a hyphenated directory on disk with a broken,
    Windows-incompatible git symlink at apps/ai_server (see git history:
    "chore: track apps/ai_server symlink for Python import compatibility")
    — someone already hit this and worked around it with a symlink that
    doesn't survive checkout on filesystems/configs without symlink
    support, silently falling back to a placeholder text file instead.
    Fixed for real: apps/ai_server is now the one real underscored
    directory (git mv, no symlink), with cicd.md's lint path and Docker
    build context updated to match. headroom_client.py's own
    `from headroom import compress` was also a hard top-level import with
    no fallback — headroom-ai[ml] needs a Rust toolchain to build and
    isn't installed here; wrapped in try/except with a passthrough
    fallback, matching the class's own already-established
    degrade-on-compression-failure behaviour.
    """
    try:
        from apps.ai_server.headroom_client import HeadroomVLLMClient
        base_url = await config_service.get("vllm.url")
        client = HeadroomVLLMClient(base_url=base_url)
        log.info("worker_activities.fraud_vllm_client_ready")
        return client
    except Exception as exc:
        log.warning("worker_activities.fraud_vllm_client_unavailable", error=str(exc))
        return None


async def _get_pii_pepper(config_service: Any, bank_id: str) -> str:
    try:
        return await config_service.get_secret("pii_hash_pepper")
    except Exception as exc:
        log.warning("worker_activities.pii_pepper_unavailable", bank_id=bank_id, error=str(exc))
        return ""


def _build_signature_vault(bank_id: str, pepper: str, redis_client: Any) -> Any:
    if not pepper:
        log.warning("worker_activities.signature_vault_skipped_no_pepper", bank_id=bank_id)
        return None
    try:
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id=bank_id, pepper=pepper)
        vault.connect(redis_client=redis_client)  # sync
        log.info("worker_activities.signature_vault_ready")
        return vault
    except Exception as exc:
        log.warning("worker_activities.signature_vault_unavailable", bank_id=bank_id, error=str(exc))
        return None


def _build_pps_vault(bank_id: str, pepper: str, redis_client: Any) -> Any:
    if not pepper:
        log.warning("worker_activities.pps_vault_skipped_no_pepper", bank_id=bank_id)
        return None
    try:
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id=bank_id, pepper=pepper)
        vault.connect(redis_client=redis_client)  # sync
        log.info("worker_activities.pps_vault_ready")
        return vault
    except Exception as exc:
        log.warning("worker_activities.pps_vault_unavailable", bank_id=bank_id, error=str(exc))
        return None


def _build_hsm_signer(config_service: Any, bank_id: str) -> Any:
    """
    Construct VaultTransitSigner for HSM-signing audit events before Immudb write.

    Uses Vault Transit engine so the signing key never leaves Vault — satisfying
    CLAUDE.md §11 "no software-held private keys". In production, Vault's backend
    is a FIPS 140-2 Level 3 HSM.

    Key name read from config_service (hsm.transit_key_name) so banks can use
    their own Vault Transit key without a code change. VAULT_ADDR and VAULT_TOKEN
    are the only two env vars allowed in application code (secrets-vault.md §IV) —
    they are injected by the Vault agent sidecar at pod startup.
    """
    try:
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        key_name = config_service.get_platform("hsm.transit_key_name")
        signer = VaultTransitSigner.from_env(key_name=key_name)
        log.info("worker_activities.hsm_signer_ready", bank_id=bank_id, key_name=key_name)
        return signer
    except Exception as exc:
        log.warning("worker_activities.hsm_signer_unavailable", bank_id=bank_id, error=str(exc))
        return None


async def _build_bloom_client(redis_client: Any, bank_id: str, config_service: Any) -> Any:
    try:
        from modules.cts.vaults.canceled_leaf_bloom import CanceledLeafBloom
        try:
            expected_items = await config_service.get("vault.bloom_expected_items")
        except Exception:
            expected_items = 100_000  # CanceledLeafBloom's own Layer 1 default
        try:
            false_positive_rate = await config_service.get("vault.bloom_false_positive_rate")
        except Exception:
            false_positive_rate = 0.001  # CanceledLeafBloom's own Layer 1 default
        client = CanceledLeafBloom(
            redis_client=redis_client,
            bank_id=bank_id,
            expected_items=expected_items,
            false_positive_rate=false_positive_rate,
        )
        client.initialize()  # sync, idempotent — BF.RESERVE with the configured capacity/fpr
        log.info("worker_activities.bloom_client_ready")
        return client
    except Exception as exc:
        log.warning("worker_activities.bloom_client_unavailable", bank_id=bank_id, error=str(exc))
        return None
