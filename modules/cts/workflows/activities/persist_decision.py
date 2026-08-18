"""Persist the terminal CTS agent decision to cts.agent_decisions.

Stores every decision outcome, scoring signals, OCR provenance, and timing so
the operations team and MLflow pipelines can audit and retrain from production
decisions without querying the immutable Immudb audit trail.

Column 'shap_values' and 'ocr_engines_used' are stored as JSON text; all
other fields are native types. 'processing_duration_ms' is computed here
from (completed_at − started_at) to keep the INSERT idempotent.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from temporalio import activity

log = structlog.get_logger()
_pylog = logging.getLogger(__name__)  # stdlib sink so pytest caplog can capture warnings
tracer = trace.get_tracer(__name__)


class PersistDecisionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    workflow_id: str
    decision: str
    decision_reason: str
    fraud_score: float
    shap_values: dict
    processing_started_at: float
    processing_completed_at: float
    ocr_confidence: Optional[float] = None
    alteration_detected: bool = False
    signature_match_score: float = 0.0
    signature_verdict: str = "UNKNOWN"
    pps_checked: bool = False
    pps_verdict: str = "UNKNOWN"
    cbs_balance_status: str = "UNKNOWN"
    degraded_mode: bool = False
    ocr_engines_used: List[str] = []
    indic_ocr_kill_switch_active: bool = False
    iet_margin_seconds: int = 0


class PersistDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool


_SQL = """
INSERT INTO cts.agent_decisions (
    instrument_id, bank_id, workflow_id, decision, decision_reason,
    fraud_score, shap_values, processing_started_at, processing_completed_at,
    processing_duration_ms, ocr_confidence, alteration_detected,
    signature_match_score, signature_verdict, pps_checked, pps_verdict,
    cbs_balance_status, degraded_mode, ocr_engines_used,
    indic_ocr_kill_switch_active, iet_margin_seconds
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8::timestamptz, $9::timestamptz,
    $10, $11, $12,
    $13, $14, $15, $16,
    $17, $18, $19,
    $20, $21
)
ON CONFLICT (workflow_id) DO NOTHING
""".strip()


@activity.defn(name="persist_agent_decision")
async def persist_agent_decision(
    inp: PersistDecisionInput,
    db_conn: Any = None,
) -> PersistDecisionResult:
    with tracer.start_as_current_span("activity.persist_agent_decision") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("decision", inp.decision)

        if db_conn is None:
            _pylog.warning("persist_agent_decision db_conn unavailable for %s", inp.workflow_id)
            log.warning(
                "persist_agent_decision.db_conn_unavailable",
                bank_id=inp.bank_id,
                workflow_id=inp.workflow_id,
            )
            return PersistDecisionResult(success=False)

        duration_ms = round((inp.processing_completed_at - inp.processing_started_at) * 1000)

        try:
            await db_conn.execute(
                _SQL,
                inp.instrument_id,
                inp.bank_id,
                inp.workflow_id,
                inp.decision,
                inp.decision_reason,
                inp.fraud_score,
                json.dumps(inp.shap_values),
                inp.processing_started_at,
                inp.processing_completed_at,
                duration_ms,
                inp.ocr_confidence,
                inp.alteration_detected,
                inp.signature_match_score,
                inp.signature_verdict,
                inp.pps_checked,
                inp.pps_verdict,
                inp.cbs_balance_status,
                inp.degraded_mode,
                json.dumps(inp.ocr_engines_used),
                inp.indic_ocr_kill_switch_active,
                inp.iet_margin_seconds,
            )
        except Exception as exc:
            log.warning(
                "persist_agent_decision.db_error",
                bank_id=inp.bank_id,
                workflow_id=inp.workflow_id,
                error=str(exc),
            )
            return PersistDecisionResult(success=False)

        log.info(
            "persist_agent_decision.stored",
            bank_id=inp.bank_id,
            workflow_id=inp.workflow_id,
            decision=inp.decision,
            duration_ms=duration_ms,
        )
        return PersistDecisionResult(success=True)
