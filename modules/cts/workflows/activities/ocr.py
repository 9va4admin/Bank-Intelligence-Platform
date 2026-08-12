"""
OCR activity — adaptive pipeline for cheque field extraction.

Flow (single entry point, no mode config):
  1. Full image → GOT-OCR2.0 via vLLM (one call — handles all Latin cheques).
  2. Inspect SCRIPT_ADAPTIVE fields (payee_name, amount_words, bank_name) from
     the GOT-OCR2 result for Indic-script content via detect_script().
  3. If Indic detected AND IndicOCR is configured → fetch image, crop the Indic
     zones, POST to IndicOCR service, override the field with the higher-accuracy
     result.  Only the fields that need it; Latin cheques stay at step 1 cost.
  4. Confidence gate + amount cross-check → HUMAN_REVIEW or PROCEED.

Thresholds always from config_service — never hardcoded.
vLLM/IndicOCR unavailable → HUMAN_REVIEW (degraded), never crashes workflow.
"""
import io
import json
from typing import Any, Optional

import httpx
import structlog
from PIL import Image
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.preprocessing.zone_extractor import (
    detect_script,
    extract_zone,
    identify_indic_script,
)
from modules.cts.sub_member.models import PrincipalTag
from modules.cts.sub_member.router import MICRPrefixRouter
from modules.cts.workflows.activities.amount_words_parser import amounts_match
from shared.ai.model_cascade import CascadeOrchestrator

log = structlog.get_logger()


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

# SCRIPT_ADAPTIVE zone → field name mapping used when IndicOCR re-runs a zone.
# IndicOCR /ocr_zones returns these keys; we map them back to OCRActivityResult fields.
_INDIC_ZONE_TO_RESULT_FIELD: dict[str, str] = {
    "payee_name":   "payee",
    "amount_words": "amount_words",
    "bank_name":    "bank_name",
}

# GOT-OCR2 result field → zone name (for fetching the crop to send to IndicOCR)
_RESULT_FIELD_TO_ZONE: dict[str, str] = {
    "payee":        "payee_name",
    "amount_words": "amount_words",
}


class OCRActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "PROCEED" | "HUMAN_REVIEW"
    micr_line: Optional[str] = None
    amount_figures: Optional[str] = None
    amount_words: Optional[str] = None
    date: Optional[str] = None
    payee: Optional[str] = None
    ifsc_code: Optional[str] = None
    overall_confidence: float = 0.0
    low_confidence_reason: Optional[str] = None
    degraded: bool = False
    cascade_level: int = 2
    principal_tag: Optional[str] = None
    sub_member_id: Optional[str] = None
    amount_mismatch: bool = False
    indic_refined_fields: list[str] = []   # which fields were re-run via IndicOCR


@activity.defn
async def ocr_extract(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
    config_service: Any,
    routing_table: Optional[dict] = None,
) -> OCRActivityResult:
    """
    Extract cheque fields via an adaptive two-stage pipeline.

    Stage 1 (always): full cheque image → GOT-OCR2 via vLLM cascade.
    Stage 2 (only when needed): Indic script detected in SCRIPT_ADAPTIVE fields
    → zone crop → IndicOCR service → replace field with higher-accuracy result.

    Latin cheques: one GOT-OCR2 call, same latency as before.
    Indic cheques: one GOT-OCR2 call + targeted zone call(s) for Indic fields only.
    """
    ai_config = await config_service.get_ai_config(inp.bank_id)
    min_confidence: float = ai_config["ai.ocr.min_confidence"]
    indic_ocr_url: str = ai_config.get("services.indic_ocr.url", "")
    indic_min_confidence: float = float(ai_config.get("ai.ocr.min_indic_confidence", 0.60))

    # ── Stage 1: Full image → GOT-OCR2 ───────────────────────────────────────
    raw = await _extract_got_ocr2(inp, orchestrator)
    if raw is None:
        return OCRActivityResult(
            outcome="HUMAN_REVIEW", degraded=True,
            low_confidence_reason="MODEL_UNAVAILABLE",
        )

    fields, cascade_level = raw

    # ── Stage 2: Indic zone refinement (only when triggered) ─────────────────
    indic_refined: list[str] = []
    if indic_ocr_url:
        indic_refined = await _refine_indic_zones(
            inp, fields, indic_ocr_url, min_confidence, indic_min_confidence
        )

    # ── Stage 3: Confidence gate + amount cross-check ─────────────────────────
    return _build_result(fields, min_confidence, cascade_level, indic_refined, routing_table, inp)


# ── Stage 1 ───────────────────────────────────────────────────────────────────

async def _extract_got_ocr2(
    inp: OCRActivityInput,
    orchestrator: CascadeOrchestrator,
) -> Optional[tuple[dict[str, tuple[Optional[str], float]], int]]:
    """
    Call GOT-OCR2 on the full cheque image.
    Returns (fields_dict, cascade_level) or None on model error.
    fields_dict: { field_name: (text_or_None, confidence) }
    """
    try:
        cascade_result = await orchestrator.call_ocr(
            image_url=inp.image_url,
            prompt=_OCR_PROMPT,
            cheque_amount=0.0,
        )
        data = json.loads(cascade_result.content)
    except Exception as exc:
        log.warning("ocr.got_ocr2_failed", instrument_id=inp.instrument_id, error=str(exc))
        return None

    def _field(key: str) -> tuple[Optional[str], float]:
        entry = data.get(key, {})
        if not isinstance(entry, dict):
            return None, 0.0
        val = entry.get("value")
        conf = float(entry.get("confidence", 0.0))
        return (val if val else None), conf

    fields: dict[str, tuple[Optional[str], float]] = {
        "micr_line":      _field("micr_line"),
        "amount_figures": _field("amount_figures"),
        "amount_words":   _field("amount_words"),
        "date":           _field("date"),
        "payee":          _field("payee"),
        "ifsc_code":      _field("ifsc_code"),
    }
    return fields, cascade_result.cascade_level


# ── Stage 2 ───────────────────────────────────────────────────────────────────

async def _refine_indic_zones(
    inp: OCRActivityInput,
    fields: dict[str, tuple[Optional[str], float]],
    indic_ocr_url: str,
    min_confidence: float,
    indic_min_confidence: float,
) -> list[str]:
    """
    For each SCRIPT_ADAPTIVE result field that contains Indic text (or has low
    confidence), fetch the cheque image, crop the zone, and call IndicOCR.
    Mutates `fields` in place with the refined value when IndicOCR wins.
    Returns list of field names that were successfully refined.
    """
    # Determine which fields need IndicOCR refinement
    needs_refine: list[tuple[str, str, str]] = []   # (result_field, zone_name, script)
    for result_field, zone_name in _RESULT_FIELD_TO_ZONE.items():
        text, conf = fields.get(result_field, (None, 0.0))
        script = identify_indic_script(text or "")
        if script is not None or (text is None and conf < min_confidence):
            needs_refine.append((result_field, zone_name, script or "devanagari"))

    if not needs_refine:
        return []

    # Fetch image once for all zones that need it
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(inp.image_url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        log.warning("ocr.indic_image_fetch_failed", instrument_id=inp.instrument_id, error=str(exc))
        return []

    refined: list[str] = []
    for result_field, zone_name, script in needs_refine:
        try:
            zone = extract_zone(img, zone_name)
            buf = io.BytesIO()
            zone.convert("RGB").save(buf, format="JPEG", quality=90)
            buf.seek(0)

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{indic_ocr_url}/ocr",
                    files={"file": ("zone.jpg", buf, "image/jpeg")},
                    params={"script": script},
                )
                resp.raise_for_status()
                data = resp.json()

            indic_text: str = data.get("text", "") or ""
            indic_conf: float = float(data.get("confidence", 0.0))

            if detect_script(indic_text) == "indic" and indic_conf >= indic_min_confidence:
                fields[result_field] = (indic_text, indic_conf)
                refined.append(result_field)
                log.info("ocr.indic_refined",
                         instrument_id=inp.instrument_id, field=result_field,
                         script=script, confidence=indic_conf)

        except Exception as exc:
            log.warning("ocr.indic_zone_failed",
                        instrument_id=inp.instrument_id, field=result_field, error=str(exc))

    return refined


# ── Stage 3 ───────────────────────────────────────────────────────────────────

def _build_result(
    fields: dict[str, tuple[Optional[str], float]],
    min_confidence: float,
    cascade_level: int,
    indic_refined: list[str],
    routing_table: Optional[dict],
    inp: OCRActivityInput,
) -> OCRActivityResult:
    """Apply confidence gate, MICR routing, amount cross-check, build final result."""
    _PRIMARY = ("date", "payee", "amount_words", "amount_figures")
    low_fields = [
        f for f in _PRIMARY
        if fields.get(f, (None, 0.0))[1] < min_confidence
    ]

    micr_line    = fields.get("micr_line",      (None, 0.0))[0]
    amt_figures  = fields.get("amount_figures",  (None, 0.0))[0]
    amt_words    = fields.get("amount_words",    (None, 0.0))[0]
    date_val     = fields.get("date",            (None, 0.0))[0]
    payee_val    = fields.get("payee",           (None, 0.0))[0]
    ifsc_raw     = fields.get("ifsc_code",       (None, 0.0))
    ifsc_code    = (
        ifsc_raw[0].strip().upper()
        if isinstance(ifsc_raw[0], str) and ifsc_raw[0] and ifsc_raw[1] >= 0.3
        else None
    )

    all_confs = [c for _, c in fields.values()]
    overall = sum(all_confs) / len(all_confs) if all_confs else 0.0

    principal_tag, sub_member_id = _route_micr(micr_line, routing_table, inp.instrument_id)

    if low_fields:
        log.info("ocr.low_confidence", instrument_id=inp.instrument_id, low_fields=low_fields)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amt_figures,
            amount_words=amt_words,
            date=date_val,
            payee=payee_val,
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
            cascade_level=cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            indic_refined_fields=indic_refined,
        )

    match = amounts_match(figures=amt_figures, words=amt_words)
    if match is False:
        log.info("ocr.amount_mismatch", instrument_id=inp.instrument_id)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amt_figures,
            amount_words=amt_words,
            overall_confidence=overall,
            low_confidence_reason="amount_figures_words_mismatch",
            cascade_level=cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            amount_mismatch=True,
            indic_refined_fields=indic_refined,
        )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=micr_line,
        amount_figures=amt_figures,
        amount_words=amt_words,
        date=date_val,
        payee=payee_val,
        ifsc_code=ifsc_code,
        overall_confidence=overall,
        cascade_level=cascade_level,
        principal_tag=principal_tag,
        sub_member_id=sub_member_id,
        indic_refined_fields=indic_refined,
    )


def _route_micr(
    micr_line: Optional[str],
    routing_table: Optional[dict],
    instrument_id: str,
) -> tuple[Optional[str], Optional[str]]:
    if not micr_line or not routing_table:
        return PrincipalTag.DIRECT.value, None
    try:
        router = MICRPrefixRouter(routing_table)
        tag, smb = router.identify(micr_line)
        return tag.value, (smb.sub_member_id if smb is not None else None)
    except Exception as exc:
        log.warning("ocr.micr_routing_failed", instrument_id=instrument_id, error=str(exc))
        return PrincipalTag.DIRECT.value, None
