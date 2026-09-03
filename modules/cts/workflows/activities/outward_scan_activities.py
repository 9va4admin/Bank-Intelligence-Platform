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
from modules.cts.workflows.activities.amount_words_parser import amounts_match
from shared.ai.model_cascade import CascadeOrchestrator

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


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
    bank_id: str
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


_FRONT_REQUIRED_METRICS = (
    "front_dpi", "front_colour_depth", "front_file_size_kb", "front_iqa_score", "micr_band_score",
)
_REAR_METRICS = (
    "rear_dpi", "rear_colour_depth", "rear_file_size_kb", "rear_iqa_score",
)


@activity.defn
async def validate_cts2010(inp: CTS2010ValidationInput) -> CTS2010ValidationResult:
    """
    Wraps modules.cts.compliance.models.InstrumentComplianceRecord (the real,
    already-implemented CTS2010Standard evaluator) with the Temporal activity
    boundary.

    Fails closed: if any required front metric is missing (None), returns
    MISSING_IMAGE_METRICS. Rear metrics are only required when the bank has
    rear_image_required=true in Layer 3 config (default: false — blank reverse
    is standard practice and must not cause a compliance failure).
    """
    with tracer.start_as_current_span("activity.validate_cts2010") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        from shared.config.config_service import config_service  # avoid circular at module load

        cts_cfg = await config_service.get_cts_config(inp.bank_id)
        rear_image_required: bool = str(cts_cfg.get("rear_image_required", "false")).lower() == "true"

        required_metrics = list(_FRONT_REQUIRED_METRICS)
        if rear_image_required:
            required_metrics.extend(_REAR_METRICS)

        missing = [f for f in required_metrics if getattr(inp, f) is None]
        if missing:
            log.warning(
                "validate_cts2010.missing_metrics",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
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
            rear_dpi=inp.rear_dpi or 0,
            rear_colour_depth=inp.rear_colour_depth or 0,
            rear_file_size_kb=inp.rear_file_size_kb or 0.0,
            rear_iqa_score=inp.rear_iqa_score or 0.0,
            micr_band_score=inp.micr_band_score,
            rear_image_required=rear_image_required,
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
    with tracer.start_as_current_span("activity.create_lot_entry") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
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
    with tracer.start_as_current_span("activity.run_vision_presentment_check") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
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


    # ---------------------------------------------------------------------------
    # vision_extract_and_check  (CR-120 path — replaces ocr_extract + run_vision_presentment_check)
    # ---------------------------------------------------------------------------

def _build_outward_vision_prompt(micr_hardware_raw: Optional[str]) -> str:
    """
    Single Qwen2-VL prompt that extracts all cheque fields AND checks for
    alteration in one pass. If the scanner provided a hardware MICR reading,
    include it so the model can cross-validate its visual MICR read against
    the hardware reading (MICR band visible in image anyway).
    """
    micr_section = ""
    if micr_hardware_raw:
        micr_section = f"""
Additionally, visually read the MICR band at the bottom of the cheque.
The hardware MICR reader reports: {micr_hardware_raw}
Compare your visual reading against this hardware reading and report any discrepancy.
Add these fields to your response:
  "micr_visual": {{"value": "...", "confidence": 0.0}},
  "micr_matches_hardware": true
"""

    return f"""Analyse this cheque image. Extract all printed fields and check for alteration.

Examine:
- amount_figures: amount in digits (e.g. "1,25,000.00")
- amount_words: amount written in words (e.g. "One Lakh Twenty Five Thousand Only")
- payee: name on "Pay" line
- date: date on cheque (DD/MM/YYYY preferred)
- alteration_detected: any overwriting, erasure, correction fluid, or ink difference on any field
- alteration_risk: overall tamper risk (0.0 = clean, 1.0 = definite tamper)
- tampered_fields: list of field names that appear tampered
{micr_section}
Return JSON only, no explanation:
{{
  "amount_figures": {{"value": "...", "confidence": 0.0}},
  "amount_words": {{"value": "...", "confidence": 0.0}},
  "payee": {{"value": "...", "confidence": 0.0}},
  "date": {{"value": "...", "confidence": 0.0}},
  "alteration_detected": false,
  "alteration_risk": 0.0,
  "tampered_fields": []
}}

Confidence: 0.0 (illegible) to 1.0 (perfectly clear).
Set value to null and confidence to 0.0 for any illegible field.
"""


class VisionExtractAndCheckInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    image_front_url: str
    bank_id: str
    micr_hardware_raw: Optional[str] = None   # from CR-120 hardware MICR reader


class VisionExtractAndCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                           # "PROCEED" | "HUMAN_REVIEW" | "MISMATCH"
    amount_figures: Optional[str] = None
    amount_words: Optional[str] = None
    payee: Optional[str] = None
    date: Optional[str] = None
    alteration_detected: bool = False
    alteration_risk: float = 0.0
    tampered_fields: list[str] = []
    micr_validated: bool = False           # hardware MICR matched visual read
    micr_mismatch: bool = False            # hardware MICR disagreed with visual read
    mismatch_fields: list[str] = []        # for MismatchResolutionWorkflow compatibility
    overall_confidence: float = 0.0
    degraded: bool = False


@activity.defn
async def vision_extract_and_check(
    inp: VisionExtractAndCheckInput,
    orchestrator: Optional[CascadeOrchestrator] = None,
    config_service=None,
) -> VisionExtractAndCheckResult:
    """
    CR-120 outward path: single Qwen2-VL call that extracts all cheque fields
    and checks for alteration in one pass.

    Replaces the separate ocr_extract (GOT-OCR2) + run_vision_presentment_check
    (Qwen2-VL) steps on the outward workflow. On the inward path, ocr_extract
    is unchanged — the IET 600ms constraint still benefits from the L1/L2 cascade.

    Cross-checks performed:
    1. amount_figures vs amount_words — classic fraud indicator if they disagree
    2. hardware MICR vs visual MICR read — flags tampering of MICR band
    3. alteration_detected — any field showing signs of physical tampering

    Outcome routing:
    - PROCEED       → all checks pass, lot assignment can proceed
    - MISMATCH      → amount figures/words disagree → MismatchResolutionWorkflow
    - HUMAN_REVIEW  → low confidence, model unavailable, or alteration detected
    """
    with tracer.start_as_current_span("activity.vision_extract_and_check") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        import json

        ai_config = await config_service.get_ai_config(inp.bank_id) if config_service else {}
        min_confidence: float = ai_config.get("ai.ocr.min_confidence", 0.85)
        alteration_threshold: float = ai_config.get("ai.alteration.risk_threshold", 0.60)

        prompt = _build_outward_vision_prompt(inp.micr_hardware_raw)

        try:
            cascade_result = await orchestrator.call_vision(
                image_url=inp.image_front_url,
                prompt=prompt,
                cheque_amount=0.0,
            )
            data = json.loads(cascade_result.content)
        except Exception as exc:
            log.warning(
                "vision_extract_and_check.model_unavailable",
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            return VisionExtractAndCheckResult(outcome="HUMAN_REVIEW", degraded=True)

        # Extract fields
        amount_figures = (data.get("amount_figures") or {}).get("value")
        amount_words   = (data.get("amount_words")   or {}).get("value")
        payee          = (data.get("payee")          or {}).get("value")
        date           = (data.get("date")           or {}).get("value")

        confidences = [
            v["confidence"]
            for v in data.values()
            if isinstance(v, dict) and "confidence" in v
        ]
        overall = sum(confidences) / len(confidences) if confidences else 0.0

        low_fields = [
            k for k, v in data.items()
            if isinstance(v, dict) and v.get("confidence", 1.0) < min_confidence
        ]
        if low_fields:
            log.info(
                "vision_extract_and_check.low_confidence",
                instrument_id=inp.instrument_id,
                low_fields=low_fields,
            )
            return VisionExtractAndCheckResult(
                outcome="HUMAN_REVIEW",
                amount_figures=amount_figures,
                amount_words=amount_words,
                payee=payee,
                date=date,
                overall_confidence=overall,
            )

        # Alteration check
        alteration_detected: bool  = bool(data.get("alteration_detected", False))
        alteration_risk: float     = float(data.get("alteration_risk", 0.0))
        tampered_fields: list[str] = list(data.get("tampered_fields", []))

        if alteration_detected or alteration_risk >= alteration_threshold:
            log.info(
                "vision_extract_and_check.alteration",
                instrument_id=inp.instrument_id,
                alteration_risk=alteration_risk,
                tampered_fields=tampered_fields,
            )
            return VisionExtractAndCheckResult(
                outcome="HUMAN_REVIEW",
                amount_figures=amount_figures,
                amount_words=amount_words,
                payee=payee,
                date=date,
                alteration_detected=True,
                alteration_risk=alteration_risk,
                tampered_fields=tampered_fields,
                overall_confidence=overall,
            )

        # Hardware MICR cross-validation (when scanner provided MICR)
        micr_validated = False
        micr_mismatch  = False
        if inp.micr_hardware_raw and "micr_visual" in data:
            micr_validated = True
            micr_mismatch  = not bool(data.get("micr_matches_hardware", True))
            if micr_mismatch:
                log.info(
                    "vision_extract_and_check.micr_mismatch",
                    instrument_id=inp.instrument_id,
                )
                return VisionExtractAndCheckResult(
                    outcome="HUMAN_REVIEW",
                    amount_figures=amount_figures,
                    amount_words=amount_words,
                    payee=payee,
                    date=date,
                    micr_validated=micr_validated,
                    micr_mismatch=True,
                    overall_confidence=overall,
                )

        # Figures vs words cross-check
        match = amounts_match(figures=amount_figures, words=amount_words)
        if match is False:
            log.info(
                "vision_extract_and_check.amount_mismatch",
                instrument_id=inp.instrument_id,
            )
            return VisionExtractAndCheckResult(
                outcome="MISMATCH",
                amount_figures=amount_figures,
                amount_words=amount_words,
                payee=payee,
                date=date,
                mismatch_fields=["amount_figures", "amount_words"],
                micr_validated=micr_validated,
                overall_confidence=overall,
            )

        return VisionExtractAndCheckResult(
            outcome="PROCEED",
            amount_figures=amount_figures,
            amount_words=amount_words,
            payee=payee,
            date=date,
            alteration_detected=False,
            alteration_risk=alteration_risk,
            tampered_fields=[],
            micr_validated=micr_validated,
            micr_mismatch=False,
            mismatch_fields=[],
            overall_confidence=overall,
        )


    # ── Payee / beneficiary account validation (outward) ─────────────────────────


class PayeeValidationInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    payee_account_number: str           # from deposit slip (kiosk entry / teller counter / rear OCR)
    payee_name_from_slip: Optional[str] = None   # name customer wrote on slip / back of cheque
    name_match_threshold: Optional[float] = None  # always set via config_service in activity


class PayeeValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str        # PROCEED | ACCOUNT_NOT_FOUND | NAME_MISMATCH | ACCOUNT_INACTIVE | CBS_UNAVAILABLE
    account_status: Optional[str] = None
    name_match_score: Optional[float] = None
    name_match_confidence: str = "UNKNOWN"
    payee_display: Optional[str] = None   # "R***" — for UI and audit log
    vault_hit: bool = False               # True if Account Vault had the entry (no CBS call on status check)
    degraded: bool = False


_INACTIVE_STATUSES = {"FROZEN", "CLOSED", "NPA", "DORMANT"}


@activity.defn
async def validate_payee_account(
    inp: PayeeValidationInput,
    account_vault=None,     # worker-level DI: AccountVault instance
    cbs_connector=None,     # worker-level DI: CBSConnector instance
    config_service=None,    # worker-level DI: ConfigService instance
) -> PayeeValidationResult:
    """
    Outward CTS — validate the payee's (beneficiary's) KBL account before presenting to NGCH.

    Lookup order:
      1. Account Vault (Redis → YugabyteDB) — existence + status check (sub-millisecond)
           HIT + INACTIVE  → ACCOUNT_INACTIVE immediately (no CBS call)
           HIT + ACTIVE    → CBS call for name match only
           MISS            → CBS full call (existence + status + name)
      2. CBS — name fuzzy match against account holder name stored in CBS
           On CBS miss after vault hit: treat as CBS_UNAVAILABLE (vault says account exists)
      3. On CBS call → cache account_status + holder_name_display into Account Vault
    """
    with tracer.start_as_current_span("activity.validate_payee_account") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        cts_config = await config_service.get_cts_config(inp.bank_id) if config_service else {}
        threshold: float = float(cts_config.get("payee_name_match_threshold", inp.name_match_threshold or 0.80))

        # ── Step 1: Account Vault lookup ─────────────────────────────────────────
        vault_hit = False
        vault_status: Optional[str] = None

        if account_vault is not None:
            vault_result = await account_vault.lookup(inp.payee_account_number, inp.bank_id)
            if vault_result.outcome == "FOUND" and vault_result.profile:
                vault_hit = True
                vault_status = vault_result.profile.account_status
                if vault_status in _INACTIVE_STATUSES:
                    log.info(
                        "validate_payee_account.vault_inactive",
                        instrument_id=inp.instrument_id,
                        account_last4=inp.payee_account_number[-4:],
                        account_status=vault_status,
                    )
                    return PayeeValidationResult(
                        outcome="ACCOUNT_INACTIVE",
                        account_status=vault_status,
                        payee_display=vault_result.profile.holder_name_display or "***",
                        vault_hit=True,
                    )

        # ── Step 2: CBS call — name match (and full check on vault miss) ─────────
        if cbs_connector is None:
            log.warning(
                "validate_payee_account.no_cbs_connector",
                instrument_id=inp.instrument_id,
            )
            return PayeeValidationResult(
                outcome="CBS_UNAVAILABLE", degraded=True, vault_hit=vault_hit,
            )

        try:
            from shared.cbs_connector.base import BeneficiaryValidationResult

            # If the deposit-slip name is in an Indic script, transliterate to Latin
            # before CBS comparison — the CBS connector's _name_match_score() uses
            # plain string comparison and cannot handle Devanagari, Tamil, etc.
            raw_inquiry = inp.payee_name_from_slip or ""
            inquiry_name = raw_inquiry
            if raw_inquiry:
                from modules.cts.preprocessing.payee_normalizer import (
                    _is_indic, strip_salutation, transliterate_by_script, _detect_script,
                )
                if _is_indic(raw_inquiry):
                    script = _detect_script(raw_inquiry) or "devanagari"
                    inquiry_name = transliterate_by_script(
                        strip_salutation(raw_inquiry), script
                    )
                    log.info(
                        "validate_payee_account.indic_transliterated",
                        instrument_id=inp.instrument_id,
                        script=script,
                    )

            cbs_result: BeneficiaryValidationResult = await cbs_connector.validate_beneficiary(
                account_number=inp.payee_account_number,
                inquiry_name=inquiry_name,
                bank_id=inp.bank_id,
                name_match_threshold=threshold,
            )
        except Exception as exc:
            log.warning(
                "validate_payee_account.cbs_error",
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            if vault_hit:
                # Vault says account exists (ACTIVE) but CBS is now unavailable — proceed degraded
                return PayeeValidationResult(
                    outcome="CBS_UNAVAILABLE",
                    account_status=vault_status,
                    payee_display="***",
                    vault_hit=True,
                    degraded=True,
                )
            return PayeeValidationResult(outcome="CBS_UNAVAILABLE", degraded=True)

        log.info(
            "validate_payee_account.cbs_result",
            instrument_id=inp.instrument_id,
            account_last4=inp.payee_account_number[-4:],
            outcome=cbs_result.outcome,
            name_match_score=cbs_result.name_match_score,
            vault_hit=vault_hit,
        )

        # ── Step 3: Cache CBS result into Account Vault ──────────────────────────
        if account_vault is not None and cbs_result.outcome not in ("ACCOUNT_NOT_FOUND", "CBS_UNAVAILABLE"):
            try:
                await account_vault.store_profile(
                    account_number=inp.payee_account_number,
                    profile={
                        "account_number_last4": inp.payee_account_number[-4:],
                        "account_type": "UNKNOWN",
                        "account_status": cbs_result.account_status.value if cbs_result.account_status else "ACTIVE",
                        "holder_name_display": cbs_result.payee_display or "***",
                    },
                    source="CBS_PAYEE_VALIDATE",
                )
            except Exception as exc:
                log.warning("validate_payee_account.vault_cache_failed", error=str(exc))

        return PayeeValidationResult(
            outcome=cbs_result.outcome,
            account_status=cbs_result.account_status.value if cbs_result.account_status else None,
            name_match_score=cbs_result.name_match_score,
            name_match_confidence=cbs_result.name_match_confidence,
            payee_display=cbs_result.payee_display,
            vault_hit=vault_hit,
            degraded=cbs_result.degraded,
        )


    # ── Rear-image / deposit-slip payee detail extraction ─────────────────────────


_REAR_OCR_PROMPT = """This is the REAR (back) of a cheque or a bank deposit slip.
Extract the depositor's account details written or printed on it.

Look for:
- account_number: the depositor's bank account number (digits only)
- ifsc_code: IFSC code (format: 4 letters + 0 + 6 digits, e.g. KARB0000001)
- depositor_name: the name written by the depositor
- mobile_number: 10-digit mobile number if present

Return JSON only:
{
  "account_number": {"value": "...", "confidence": 0.0},
  "ifsc_code": {"value": "...", "confidence": 0.0},
  "depositor_name": {"value": "...", "confidence": 0.0},
  "mobile_number": {"value": null, "confidence": 0.0}
}
Set value to null and confidence to 0.0 for any field not found.
"""


class RearPayeeExtractionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_rear_url: str       # rear cheque image or deposit slip scan


class RearPayeeExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    depositor_name: Optional[str] = None
    mobile_number: Optional[str] = None
    overall_confidence: float = 0.0
    degraded: bool = False


@activity.defn
async def extract_rear_payee_details(
    inp: RearPayeeExtractionInput,
    orchestrator=None,   # worker-level DI: CascadeOrchestrator
) -> RearPayeeExtractionResult:
    """
    OCR the back of the cheque or the deposit slip image to extract
    the payee's account number, IFSC, name, and mobile number.

    This replaces manual keyboarding at the teller counter — the customer's
    handwritten or printed deposit slip is scanned and the fields extracted.
    On OCR failure, degraded=True is set and the caller falls back to
    teller manual entry (the instrument is not rejected).
    """
    with tracer.start_as_current_span("activity.extract_rear_payee_details") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        import json

        if orchestrator is None:
            log.warning("extract_rear_payee_details.no_orchestrator", instrument_id=inp.instrument_id)
            return RearPayeeExtractionResult(degraded=True)

        try:
            result = await orchestrator.call_vision(
                image_url=inp.image_rear_url,
                prompt=_REAR_OCR_PROMPT,
                cheque_amount=0.0,
            )
            data = json.loads(result.content)
        except Exception as exc:
            log.warning(
                "extract_rear_payee_details.ocr_failed",
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            return RearPayeeExtractionResult(degraded=True)

        def _val(field: str) -> Optional[str]:
            entry = data.get(field) or {}
            return entry.get("value")

        def _conf(field: str) -> float:
            entry = data.get(field) or {}
            return float(entry.get("confidence", 0.0))

        confs = [_conf(f) for f in ("account_number", "ifsc_code", "depositor_name")]
        overall = sum(confs) / len(confs) if confs else 0.0

        log.info(
            "extract_rear_payee_details.done",
            instrument_id=inp.instrument_id,
            account_last4=(_val("account_number") or "")[-4:],
            overall_confidence=overall,
        )
        return RearPayeeExtractionResult(
            account_number=_val("account_number"),
            ifsc_code=_val("ifsc_code"),
            depositor_name=_val("depositor_name"),
            mobile_number=_val("mobile_number"),
            overall_confidence=overall,
        )


    # ── Cheque de-duplication activity ────────────────────────────────────────────

class ChequeDedupInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    micr_line: str          # full MICR line from OCR — MICR code extracted inside
    cheque_number: str      # 6-digit cheque serial from deposit slip or scanner
    presented_at: str       # ISO datetime string of this presentation


class ChequeDedupActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    is_duplicate: bool
    original_instrument_id: Optional[str] = None
    original_presented_at: Optional[str] = None


@activity.defn
async def check_cheque_dedup(inp: ChequeDedupInput) -> ChequeDedupActivityResult:
    """Check and register cheque presentation for duplicate detection.

    Extracts the 9-digit MICR code from the MICR line (chars 13–21, standard
    CTS-2010 MICR field layout) and uses it with the cheque number to build a
    Redis dedup key with 18-month TTL.

    FRESH  → first presentation, key registered.
    DUPLICATE → same cheque seen before; caller must reject and audit.
    """
    with tracer.start_as_current_span("activity.check_cheque_dedup") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        from shared.config.config_service import config_service
        from modules.cts.preprocessing.cheque_dedup import check_and_register_dedup

        try:
            redis_url = config_service.get("redis.cts.url")
            import aioredis
            redis = await aioredis.from_url(redis_url, decode_responses=False)
        except Exception as exc:
            # Redis unavailable: fail open with FRESH to avoid blocking clearing.
            # Audit trail in YugabyteDB provides compliance backstop.
            log.warning(
                "check_cheque_dedup.redis_unavailable",
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            return ChequeDedupActivityResult(is_duplicate=False)

        # MICR line layout (CTS-2010): positions 13–21 (1-indexed) = 9-digit bank/branch code.
        # Strip non-digit chars before slicing — scanner OCR sometimes inserts spaces.
        digits_only = "".join(c for c in inp.micr_line if c.isdigit())
        micr_code = digits_only[12:21] if len(digits_only) >= 21 else digits_only

        result = await check_and_register_dedup(
            bank_id=inp.bank_id,
            micr_code=micr_code,
            cheque_number=inp.cheque_number,
            instrument_id=inp.instrument_id,
            presented_at=inp.presented_at,
            redis=redis,
        )
        log.info(
            "check_cheque_dedup.result",
            instrument_id=inp.instrument_id,
            decision=result.decision,
            micr_suffix=micr_code[-4:] if micr_code else "",
            cheque_suffix=inp.cheque_number[-4:],
        )
        return ChequeDedupActivityResult(
            is_duplicate=(result.decision == "DUPLICATE"),
            original_instrument_id=result.existing_instrument_id,
            original_presented_at=result.existing_presented_at,
        )


    # ── Scan event recorder ────────────────────────────────────────────────────────

class RecordScanEventInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    scan_id: str
    instrument_id: Optional[str] = None
    branch_id: Optional[str] = None
    session_id: Optional[str] = None
    micr_suffix: Optional[str] = None
    payee_display: Optional[str] = None
    amount_range: Optional[str] = None
    outcome: str
    lot_id: Optional[str] = None
    mismatch_id: Optional[str] = None
    mismatch_fields: Optional[list[str]] = None
    reject_reason: Optional[str] = None


@activity.defn(name="record_outward_scan_event")
async def record_outward_scan_event(inp: RecordScanEventInput) -> None:
    with tracer.start_as_current_span("activity.record_outward_scan_event") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        from shared.config.config_service import config_service
        dsn = await config_service.get("db.cts.dsn")

        import asyncpg
        try:
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    """
                    INSERT INTO cts.outward_scan_events
                        (bank_id, branch_id, session_id, scan_id, instrument_id,
                         micr_suffix, payee_display, amount_range, outcome,
                         lot_id, mismatch_id, mismatch_fields, reject_reason)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    """,
                    inp.bank_id, inp.branch_id, inp.session_id, inp.scan_id,
                    inp.instrument_id, inp.micr_suffix, inp.payee_display,
                    inp.amount_range, inp.outcome, inp.lot_id, inp.mismatch_id,
                    inp.mismatch_fields, inp.reject_reason,
                )
            finally:
                await conn.close()
        except Exception as exc:
            log.warning("record_outward_scan_event.db_unavailable", scan_id=inp.scan_id, error=str(exc))
