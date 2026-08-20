"""
InstrumentDigest payload models.

StepResult    — one entry per pipeline step that ran (or was skipped).
InstrumentDigest — complete processing record written as a single payload to:
  - YugabyteDB  cts.agent_decisions.steps_digest  (JSONB, queryable)
  - Immudb      one HSM-signed entry per instrument  (tamper-evident)

The workflow accumulator in cheque_workflow.py / outward_scan_workflow.py
appends a StepResult after each activity call, then passes the full list
into finalise() which constructs InstrumentDigest and persists it.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from modules.cts.pipeline.registry import REGISTRY_VERSION


class StepResult(BaseModel):
    """Result of one pipeline step for a single instrument."""
    model_config = ConfigDict(frozen=True)

    step_id:     str                    # matches PipelineStep.step_id in registry
    outcome:     str                    # "PASS" | "FAIL" | "SKIPPED" | "DEGRADED"
    reason:      Optional[str]  = None  # machine code: "CBS_CONFIRMED", "LOW_CONFIDENCE", …
    score:       Optional[float] = None # dominant score for this step (ocr_confidence, sig_match, fraud_score)
    duration_ms: Optional[int]  = None  # wall-clock time for this activity
    extra:       dict[str, Any]  = {}   # step-specific payload (violations list, shap keys, etc.)


class InstrumentDigest(BaseModel):
    """
    Complete processing record for one instrument — written once at finalise().

    steps[] is ordered by registry seq. Steps that were skipped (conditional
    steps whose condition was not met) appear with outcome="SKIPPED" so the
    passbook always renders a full fixed-length card regardless of path taken.
    """
    model_config = ConfigDict(frozen=True)

    instrument_id:    str
    bank_id:          str
    pipeline:         str               # "INWARD" | "OUTWARD"
    workflow_id:      str
    started_at:       float             # Unix timestamp
    decided_at:       float             # Unix timestamp
    final_decision:   str               # "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW" | "ACCEPTED" | "CTS_REJECTED" | …
    steps:            list[StepResult]  # ordered by registry seq
    shap_values:      dict[str, Any] = {}
    registry_version: str = REGISTRY_VERSION


def build_digest(
    *,
    instrument_id: str,
    bank_id: str,
    pipeline: str,
    workflow_id: str,
    started_at: float,
    decided_at: float,
    final_decision: str,
    accumulated_steps: list[StepResult],
    shap_values: dict[str, Any] | None = None,
) -> InstrumentDigest:
    """
    Build a complete InstrumentDigest, padding any registry steps that were
    not reached with outcome="SKIPPED". This ensures the passbook always
    renders a full fixed-length card regardless of which exit path fired.
    """
    from modules.cts.pipeline.registry import steps_for

    ran_ids = {s.step_id for s in accumulated_steps}
    padded: list[StepResult] = list(accumulated_steps)

    for step_def in steps_for(pipeline):
        if step_def.step_id not in ran_ids:
            padded.append(StepResult(
                step_id=step_def.step_id,
                outcome="SKIPPED",
            ))

    # Re-sort by registry seq so order is always canonical
    seq_map = {s.step_id: s.seq for s in steps_for(pipeline)}
    padded.sort(key=lambda r: seq_map.get(r.step_id, 999))

    return InstrumentDigest(
        instrument_id=instrument_id,
        bank_id=bank_id,
        pipeline=pipeline,
        workflow_id=workflow_id,
        started_at=started_at,
        decided_at=decided_at,
        final_decision=final_decision,
        steps=padded,
        shap_values=shap_values or {},
        registry_version=REGISTRY_VERSION,
    )
