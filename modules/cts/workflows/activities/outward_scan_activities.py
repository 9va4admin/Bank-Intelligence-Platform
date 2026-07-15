"""
OutwardScanWorkflow activities — CTS-2010 compliance, lot assignment, Vision
LLM presentment cross-check.

capture_image and MICR extraction are NOT here: by the time OutwardScanWorkflow
starts, image_front_url/image_rear_url already point at uploaded images (the
scanner drop-folder → MinIO upload happens in an upstream trigger service, out
of this workflow's scope), and MICR/amount extraction reuses the existing
ocr_extract activity (modules/cts/workflows/activities/ocr.py) rather than a
second bespoke OCR path.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.compliance.models import InstrumentComplianceRecord
from shared.ai.model_cascade import CascadeOrchestrator

log = structlog.get_logger()


def _numeric_amounts_match(a: str, b: str, tolerance: Decimal = Decimal("0.01")) -> bool:
    """Compare two numeric amount strings (both 'figures', e.g. scanner vs
    Vision reads of the same printed number) — not to be confused with
    amount_words_parser.amounts_match(), which compares figures against an
    English words rendering and expects a completely different input shape."""
    try:
        return abs(Decimal(a.replace(",", "")) - Decimal(b.replace(",", ""))) <= tolerance
    except (InvalidOperation, AttributeError):
        return False


# ---------------------------------------------------------------------------
# validate_cts2010
# ---------------------------------------------------------------------------

class CTS2010ValidationInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    cheque_number: str
    front_dpi: Optional[int] = None
    rear_dpi: Optional[int] = None
    front_colour_depth: Optional[int] = None
    rear_colour_depth: Optional[int] = None
    front_file_size_kb: Optional[float] = None
    rear_file_size_kb: Optional[float] = None
    front_iqa_score: Optional[float] = None
    rear_iqa_score: Optional[float] = None
    micr_band_score: Optional[float] = None


class CTS2010ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    is_compliant: bool
    violations: list[str]


_REQUIRED_METRICS = (
    "front_dpi", "rear_dpi", "front_colour_depth", "rear_colour_depth",
    "front_file_size_kb", "rear_file_size_kb",
    "front_iqa_score", "rear_iqa_score", "micr_band_score",
)


@activity.defn
async def validate_cts2010(inp: CTS2010ValidationInput) -> CTS2010ValidationResult:
    """
    Wraps modules.cts.compliance.models.InstrumentComplianceRecord (the real,
    already-implemented CTS2010Standard evaluator) with the Temporal activity
    boundary.

    Fails closed: if any required image metric is missing (None), this is not
    treated as a pass — a compliance certificate cannot be issued without the
    data to certify it. Returns is_compliant=False with a single
    MISSING_IMAGE_METRICS violation rather than fabricating a value.
    """
    missing = [f for f in _REQUIRED_METRICS if getattr(inp, f) is None]
    if missing:
        log.warning(
            "validate_cts2010.missing_metrics",
            instrument_id=inp.instrument_id,
            missing=missing,
        )
        return CTS2010ValidationResult(is_compliant=False, violations=["MISSING_IMAGE_METRICS"])

    record = InstrumentComplianceRecord(
        instrument_id=inp.instrument_id,
        cheque_number=inp.cheque_number,
        lot_number="",  # not yet assigned at validation time — informational only, unused by _evaluate()
        front_dpi=inp.front_dpi,
        front_colour_depth=inp.front_colour_depth,
        front_file_size_kb=inp.front_file_size_kb,
        front_iqa_score=inp.front_iqa_score,
        rear_dpi=inp.rear_dpi,
        rear_colour_depth=inp.rear_colour_depth,
        rear_file_size_kb=inp.rear_file_size_kb,
        rear_iqa_score=inp.rear_iqa_score,
        micr_band_score=inp.micr_band_score,
    )

    log.info(
        "validate_cts2010.evaluated",
        instrument_id=inp.instrument_id,
        is_compliant=record.is_compliant,
        violations=record.failure_reasons,
    )
    return CTS2010ValidationResult(
        is_compliant=record.is_compliant,
        violations=record.failure_reasons,
    )


# ---------------------------------------------------------------------------
# create_lot_entry
# ---------------------------------------------------------------------------

class LotAssignmentInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    # Needed so worker-level DI can select the correct per-session LotManager
    # instance out of a registry (see BoundCTSActivities.create_lot_entry) —
    # a fresh LotManager per activity call would never produce sequential lot
    # numbers across a real session's many instruments.
    bank_ifsc: str = ""
    session_id: str = ""


class LotAssignmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str


@activity.defn
async def create_lot_entry(inp: LotAssignmentInput, lot_manager: Any = None) -> LotAssignmentResult:
    """
    Assigns instrument_id to a lot via LotManager.auto_assign().

    lot_manager is worker-level DI: LotManager (modules/cts/lot/manager.py) is
    a stateful, in-memory, per-clearing-session object — a fresh instance per
    activity call would never produce sequential lot numbers across a real
    session's many instruments. BoundCTSActivities.create_lot_entry
    (modules/cts/worker_activities.py) selects the correct persistent
    instance per (bank_ifsc, session_id) from a registry before calling this.
    """
    lot_number = lot_manager.auto_assign(inp.instrument_id)
    log.info(
        "create_lot_entry.assigned",
        instrument_id=inp.instrument_id,
        lot_number=lot_number,
    )
    return LotAssignmentResult(lot_number=lot_number)


# ---------------------------------------------------------------------------
# run_vision_presentment_check
# ---------------------------------------------------------------------------

_PRESENTMENT_PROMPT = """
Read the amount in figures printed on this cheque image. Respond in JSON only:
{"amount_figures": "..."}
If illegible, set amount_figures to null.
"""


class VisionPresentmentCheckInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    image_front_url: str
    scanner_amount_str: str
    cheque_amount: float
    bank_id: str


class VisionPresentmentCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    has_mismatch: bool
    mismatch_fields: list[str]
    vision_amount_str: Optional[str]


@activity.defn
async def run_vision_presentment_check(
    inp: VisionPresentmentCheckInput,
    orchestrator: Optional[CascadeOrchestrator] = None,
) -> VisionPresentmentCheckResult:
    """
    Presentment-side sanity cross-check: Vision LLM re-reads the amount from
    the cheque image and compares against what the scanner already read.
    Scanner is authoritative for presentment (see outward_scan_workflow.py
    module docstring) — Vision is a cross-check only, run LAST after lot
    assignment so most cheques never need it.

    orchestrator is worker-level DI (out of this fix's scope, same precedent
    as detect_alteration's vllm_client in cheque_workflow.py). Without a real
    orchestrator injected, this activity cannot run for real — that is
    correct and matches every other AI-calling activity in this codebase.
    """
    import json

    result = await orchestrator.call_vision(
        image_url=inp.image_front_url,
        prompt=_PRESENTMENT_PROMPT,
        cheque_amount=inp.cheque_amount,
    )

    try:
        parsed = json.loads(result.content)
        vision_amount_str = parsed.get("amount_figures")
    except (json.JSONDecodeError, AttributeError):
        vision_amount_str = None

    if vision_amount_str is None:
        # Vision couldn't read it at all — cannot confirm a match, but this is
        # not the same as a confirmed mismatch either. Degrade to no-mismatch
        # (scanner remains authoritative for presentment) rather than holding
        # every cheque Vision merely failed to read.
        log.warning(
            "run_vision_presentment_check.vision_unreadable",
            instrument_id=inp.instrument_id,
        )
        return VisionPresentmentCheckResult(
            has_mismatch=False, mismatch_fields=[], vision_amount_str=None,
        )

    has_mismatch = not _numeric_amounts_match(inp.scanner_amount_str, vision_amount_str)

    log.info(
        "run_vision_presentment_check.compared",
        instrument_id=inp.instrument_id,
        scanner_amount=inp.scanner_amount_str,
        vision_amount=vision_amount_str,
        has_mismatch=has_mismatch,
        cascade_level=result.cascade_level,
    )

    return VisionPresentmentCheckResult(
        has_mismatch=has_mismatch,
        mismatch_fields=["amount_figures"] if has_mismatch else [],
        vision_amount_str=vision_amount_str,
    )
