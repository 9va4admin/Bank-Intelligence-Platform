"""
OCR activity — extract cheque fields via GOT-OCR2.0 (vLLM, cts-ocr queue).

Fields: MICR line, amount in figures, amount in words, date, payee, drawer.
Confidence below min_confidence → HUMAN_REVIEW.
vLLM unavailable → HUMAN_REVIEW (degraded), never crashes workflow.
"""
import io
import json
from typing import Any, Literal, Optional

import httpx
import structlog
from PIL import Image
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.preprocessing.zone_extractor import (
    ALWAYS_LATIN,
    SCRIPT_ADAPTIVE,
    detect_script,
    extract_zone,
    zone_to_data_uri,
)
from modules.cts.sub_member.models import PrincipalTag
from modules.cts.sub_member.router import MICRPrefixRouter
from modules.cts.workflows.activities.amount_words_parser import amounts_match
from shared.ai.model_cascade import CascadeOrchestrator
from shared.utils.masking import mask_amount

log = structlog.get_logger()

OCRMode = Literal["FULL_IMAGE", "PARTIAL_IMAGE"]


class OCRActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str


_OCR_PROMPT = """
Extract all printed fields from this cheque image. Return JSON only, no explanation:
{
  "micr_line": {"value": "...", "confidence": 0.0},
  "amount_figures": {"value": "...", "confidence": 0.0},
  "amount_words": {"value": "...", "confidence": 0.0},
  "date": {"value": "...", "confidence": 0.0},
  "payee": {"value": "...", "confidence": 0.0},
  "ifsc_code": {"value": "...", "confidence": 0.0}
}
If a field is illegible or not present, set value to null and confidence to 0.0.
Confidence range: 0.0 (illegible) to 1.0 (perfectly clear).
ifsc_code: the bank IFSC code printed on the cheque face (e.g. "SBIN0001234").
"""

# PARTIAL_IMAGE mode — one prompt per zone crop (single-field response)
_ZONE_PROMPTS: dict[str, str] = {
    "date": (
        'Extract the cheque date from this field crop. '
        'Return JSON only: {"value": "DD/MM/YYYY", "confidence": 0.0}'
    ),
    "payee_name": (
        'Extract the payee name from this cheque field. '
        'Return JSON only: {"value": "...", "confidence": 0.0}'
    ),
    "amount_words": (
        'Extract the amount written in words (e.g. "Twenty Two Lakhs Fifty Five Thousand"). '
        'Return JSON only: {"value": "...", "confidence": 0.0}'
    ),
    "amount_figures": (
        'Extract the numeric cheque amount (digits only). '
        'Return JSON only: {"value": "...", "confidence": 0.0}'
    ),
    "micr_band": (
        'Extract the MICR line text (cheque number, sort code, account number). '
        'Return JSON only: {"value": "...", "confidence": 0.0}'
    ),
}

# Zone fields processed in PARTIAL_IMAGE mode and their order
_PARTIAL_FIELDS = ("date", "payee_name", "amount_words", "amount_figures", "micr_band")


class OCRActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "PROCEED" | "HUMAN_REVIEW"
    micr_line: Optional[str] = None
    amount_figures: Optional[str] = None
    amount_words: Optional[str] = None
    date: Optional[str] = None
    payee: Optional[str] = None
    ifsc_code: Optional[str] = None     # IFSC printed on cheque face (item 3 — IFSC cross-check)
    overall_confidence: float = 0.0
    low_confidence_reason: Optional[str] = None
    degraded: bool = False
    cascade_level: int = 2              # 1 = L1 used (7B fast), 2 = L2 used (full model)
    principal_tag: Optional[str] = None   # "DIRECT" | "SUB_MEMBER"
    sub_member_id: Optional[str] = None   # populated when principal_tag == "SUB_MEMBER"
    amount_mismatch: bool = False         # True when figures and words disagree


@activity.defn
async def ocr_extract(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
    config_service,
    routing_table: Optional[dict] = None,
) -> OCRActivityResult:
    """
    Extract cheque fields. Mode is controlled by ai_config["ocr.mode"]:

      FULL_IMAGE (default) — sends the complete cheque image to GOT-OCR2 via vLLM.
                             Single inference call extracts all fields at once.

      PARTIAL_IMAGE        — crops each CTS-2010 field zone independently,
                             detects script per zone (Indic vs Latin), routes to:
                               ALWAYS_LATIN zones   → GOT-OCR2 (cts-ocr queue)
                               SCRIPT_ADAPTIVE zones → IndicOCR if Indic, else GOT-OCR2
    """
    ai_config = await config_service.get_ai_config(inp.bank_id)
    mode: OCRMode = ai_config.get("ocr.mode", "FULL_IMAGE")

    if mode == "PARTIAL_IMAGE":
        return await _run_partial_image(inp, orchestrator, ai_config, routing_table)
    return await _run_full_image(inp, orchestrator, ai_config, routing_table)


# ── FULL_IMAGE mode ───────────────────────────────────────────────────────────

async def _run_full_image(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
    ai_config: dict,
    routing_table: Optional[dict],
) -> OCRActivityResult:
    """Send the complete cheque image to GOT-OCR2; extract all fields in one call."""
    min_confidence = ai_config["ai.ocr.min_confidence"]
    resolved_cascade_level = 2

    try:
        cascade_result = await orchestrator.call_ocr(
            image_url=inp.image_url,
            prompt=_OCR_PROMPT,
            cheque_amount=0.0,
        )
        data = json.loads(cascade_result.content)
        resolved_cascade_level = cascade_result.cascade_level
    except Exception as exc:
        log.warning("ocr_activity.model_unavailable", instrument_id=inp.instrument_id, error=str(exc))
        return OCRActivityResult(outcome="HUMAN_REVIEW", degraded=True, low_confidence_reason="MODEL_UNAVAILABLE")

    _PRIMARY_FIELDS = {"micr_line", "amount_figures", "amount_words", "date", "payee"}
    primary_data = {k: v for k, v in data.items() if k in _PRIMARY_FIELDS}

    confidences = [v["confidence"] for v in primary_data.values() if isinstance(v, dict) and "confidence" in v]
    overall = sum(confidences) / len(confidences) if confidences else 0.0
    low_fields = [k for k, v in primary_data.items() if isinstance(v, dict) and v.get("confidence", 1.0) < min_confidence]

    micr_line = data.get("micr_line", {}).get("value")
    principal_tag, sub_member_id = _route_micr(micr_line, routing_table, inp.instrument_id)

    if low_fields:
        log.info("ocr_activity.low_confidence", instrument_id=inp.instrument_id, low_fields=low_fields)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=data.get("amount_figures", {}).get("value"),
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
            cascade_level=resolved_cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
        )

    amount_figures_val = data.get("amount_figures", {}).get("value")
    amount_words_val = data.get("amount_words", {}).get("value")

    match = amounts_match(figures=amount_figures_val, words=amount_words_val)
    if match is False:
        log.info("ocr_activity.amount_mismatch", instrument_id=inp.instrument_id)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amount_figures_val,
            amount_words=amount_words_val,
            overall_confidence=overall,
            low_confidence_reason="amount_figures_words_mismatch",
            cascade_level=resolved_cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            amount_mismatch=True,
        )

    ifsc_entry = data.get("ifsc_code", {})
    ifsc_raw = ifsc_entry.get("value") if isinstance(ifsc_entry, dict) else None
    ifsc_conf = ifsc_entry.get("confidence", 0.0) if isinstance(ifsc_entry, dict) else 0.0
    ifsc_code = (
        ifsc_raw.strip().upper()
        if isinstance(ifsc_raw, str) and ifsc_raw and ifsc_conf >= 0.3
        else None
    )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=micr_line,
        amount_figures=amount_figures_val,
        amount_words=amount_words_val,
        date=data.get("date", {}).get("value"),
        payee=data.get("payee", {}).get("value"),
        ifsc_code=ifsc_code,
        overall_confidence=overall,
        cascade_level=resolved_cascade_level,
        principal_tag=principal_tag,
        sub_member_id=sub_member_id,
    )


# ── PARTIAL_IMAGE mode ────────────────────────────────────────────────────────

async def _run_partial_image(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
    ai_config: dict,
    routing_table: Optional[dict],
) -> OCRActivityResult:
    """
    Zone-based OCR: crop each CTS-2010 field, detect script, route to the
    right model.

    ALWAYS_LATIN fields (date, amount_figures, micr_band) go straight to GOT-OCR2.
    SCRIPT_ADAPTIVE fields (payee_name, amount_words, bank_name) try IndicOCR
    first; fall back to GOT-OCR2 when text is Latin or IndicOCR is unavailable.
    """
    min_confidence = ai_config["ai.ocr.min_confidence"]
    indic_ocr_url = ai_config.get("services.indic_ocr.url", "http://indic-ocr:8021")
    min_indic_conf = ai_config.get("ai.ocr.min_indic_confidence", 0.60)

    # ── 1. Fetch full cheque image ────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(inp.image_url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        log.warning("ocr_partial.image_fetch_failed", instrument_id=inp.instrument_id, error=str(exc))
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            degraded=True,
            low_confidence_reason="IMAGE_FETCH_FAILED",
        )

    # ── 2. Per-field extraction ───────────────────────────────────────────────
    # field_name → (extracted_text, confidence, source)
    fields: dict[str, tuple[Optional[str], float, str]] = {}

    for field in _PARTIAL_FIELDS:
        try:
            zone = extract_zone(img, field)
        except Exception as exc:
            log.warning("ocr_partial.zone_extract_failed", field=field, error=str(exc))
            fields[field] = (None, 0.0, "zone_failed")
            continue

        if field in ALWAYS_LATIN:
            text, conf, src = await _got_ocr_zone(zone, field, orchestrator)
        else:
            text, conf, src = await _script_route_zone(
                zone, field, orchestrator, indic_ocr_url, min_indic_conf
            )

        log.info("ocr_partial.field_extracted", field=field, source=src, confidence=conf,
                 instrument_id=inp.instrument_id)
        fields[field] = (text, conf, src)

    # ── 3. Map zone field names → OCRActivityResult field names ───────────────
    micr_line       = fields.get("micr_band",      (None, 0.0, ""))[0]
    amount_figures  = fields.get("amount_figures",  (None, 0.0, ""))[0]
    amount_words    = fields.get("amount_words",    (None, 0.0, ""))[0]
    date_val        = fields.get("date",            (None, 0.0, ""))[0]
    payee_val       = fields.get("payee_name",      (None, 0.0, ""))[0]

    # ── 4. Confidence gate ────────────────────────────────────────────────────
    all_confs = [c for _, c, _ in fields.values()]
    overall = sum(all_confs) / len(all_confs) if all_confs else 0.0

    # Primary fields for confidence gate — micr_band excluded (often hardware-read)
    _PRIMARY = ("date", "payee_name", "amount_words", "amount_figures")
    low_fields = [f for f in _PRIMARY if fields.get(f, (None, 0.0, ""))[1] < min_confidence]

    principal_tag, sub_member_id = _route_micr(micr_line, routing_table, inp.instrument_id)

    if low_fields:
        log.info("ocr_partial.low_confidence", instrument_id=inp.instrument_id, low_fields=low_fields)
        # Include all extracted values so human reviewers can see the AI's best attempt.
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amount_figures,
            amount_words=amount_words,
            date=date_val,
            payee=payee_val,
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
        )

    # ── 5. Amount cross-check ─────────────────────────────────────────────────
    match = amounts_match(figures=amount_figures, words=amount_words)
    if match is False:
        log.info("ocr_partial.amount_mismatch", instrument_id=inp.instrument_id)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amount_figures,
            amount_words=amount_words,
            overall_confidence=overall,
            low_confidence_reason="amount_figures_words_mismatch",
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            amount_mismatch=True,
        )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=micr_line,
        amount_figures=amount_figures,
        amount_words=amount_words,
        date=date_val,
        payee=payee_val,
        overall_confidence=overall,
        principal_tag=principal_tag,
        sub_member_id=sub_member_id,
    )


async def _got_ocr_zone(
    zone: Image.Image,
    field: str,
    orchestrator: CascadeOrchestrator,
) -> tuple[Optional[str], float, str]:
    """Encode zone as data URI and call GOT-OCR2 via vLLM cascade."""
    data_uri = zone_to_data_uri(zone)
    prompt = _ZONE_PROMPTS.get(field, f'Extract {field}. Return JSON: {{"value": "...", "confidence": 0.0}}')
    try:
        result = await orchestrator.call_ocr(image_url=data_uri, prompt=prompt, cheque_amount=0.0)
        data = json.loads(result.content)
        return data.get("value"), float(data.get("confidence", 0.0)), "got_ocr2"
    except Exception as exc:
        log.warning("ocr_partial.got_ocr_zone_failed", field=field, error=str(exc))
        return None, 0.0, "got_ocr2_failed"


async def _script_route_zone(
    zone: Image.Image,
    field: str,
    orchestrator: CascadeOrchestrator,
    indic_ocr_url: str,
    min_indic_conf: float,
) -> tuple[Optional[str], float, str]:
    """
    Try IndicOCR on the zone crop first.
    If the result contains Indic-script characters AND confidence >= min_indic_conf
    → use IndicOCR result.
    Otherwise (Latin text, low confidence, or service down) → GOT-OCR2.
    """
    try:
        buf = io.BytesIO()
        zone.convert("RGB").save(buf, format="JPEG", quality=90)
        buf.seek(0)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{indic_ocr_url}/ocr",
                files={"file": ("zone.jpg", buf, "image/jpeg")},
            )
            resp.raise_for_status()
            data = resp.json()

        indic_text = data.get("text", "")
        indic_conf = float(data.get("confidence", 0.0))

        if detect_script(indic_text) == "indic" and indic_conf >= min_indic_conf:
            return indic_text, indic_conf, "indic_ocr"
    except Exception as exc:
        log.warning("ocr_partial.indic_ocr_unavailable", field=field, error=str(exc))

    # Fall through: Latin text detected, low confidence, or IndicOCR is down → GOT-OCR2
    return await _got_ocr_zone(zone, field, orchestrator)


def _route_micr(
    micr_line: Optional[str],
    routing_table: Optional[dict],
    instrument_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Identify principal tag from MICR line using MICRPrefixRouter.
    Returns (principal_tag_str, sub_member_id_str).
    Defaults to DIRECT when no micr_line or no routing_table is provided.
    """
    if not micr_line or not routing_table:
        return PrincipalTag.DIRECT.value, None

    try:
        router = MICRPrefixRouter(routing_table)
        tag, smb = router.identify(micr_line)
        sub_member_id = smb.sub_member_id if smb is not None else None
        return tag.value, sub_member_id
    except Exception as exc:
        log.warning(
            "ocr_activity.micr_routing_failed",
            instrument_id=instrument_id,
            error=str(exc),
        )
        return PrincipalTag.DIRECT.value, None
