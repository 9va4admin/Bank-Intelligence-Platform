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

    # ── Immudb writer ────────────────────────────────────────────────────────
    try:
        from shared.audit.immudb_writer import AsyncImmudbWriter
        from shared.audit.immudb_client import ImmudbClient

        raw_client = ImmudbClient()
        raw_client.connect(collection=f"msv_{bank_id}")
        immudb_client = AsyncImmudbWriter(raw_client)
        log.info("msv.worker.immudb_ready", bank_id=bank_id)
    except Exception as exc:
        log.warning("msv.worker.immudb_unavailable", bank_id=bank_id, error=str(exc))

    # ── CBS connector ────────────────────────────────────────────────────────
    try:
        from shared.cbs_connector.factory import build_cbs_connector  # type: ignore
        cbs_type = (
            config_service.get_platform("cbs_connector_type")
            if config_service
            else "finacle"
        )
        cbs_connector = build_cbs_connector(cbs_type, bank_id=bank_id)
        log.info("msv.worker.cbs_ready", bank_id=bank_id, cbs_type=cbs_type)
    except Exception as exc:
        log.warning("msv.worker.cbs_unavailable", bank_id=bank_id, error=str(exc))

    # ── SignatureOrchestrator (needs detector + embedding model + registry + BRE) ─
    try:
        from modules.msv.orchestrator import SignatureOrchestrator
        from modules.msv.ai.signature_detector import SignatureDetector
        from modules.msv.ai.embedding_model import SignatureEmbeddingModel
        from modules.msv.vaults.signatory_registry import SignatoryRegistry
        from modules.msv.mandates.bre_engine import BREEngine

        detector = SignatureDetector()
        embedding_model = SignatureEmbeddingModel()
        registry = SignatoryRegistry()
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
        enroller = AccountEnroller()
        log.info("msv.worker.enroller_ready", bank_id=bank_id)
    except Exception as exc:
        log.warning("msv.worker.enroller_unavailable", bank_id=bank_id, error=str(exc))

    return BoundMSVActivities(
        orchestrator=orchestrator,
        immudb_client=immudb_client,
        cbs_connector=cbs_connector,
        enroller=enroller,
    )
