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
import re
import io
import json
import platform
import os
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
from modules.cts.scanner.micr import MICRParser
from modules.cts.sub_member.models import PrincipalTag
from modules.cts.sub_member.router import MICRPrefixRouter
from modules.cts.workflows.activities.amount_words_parser import amounts_match
from shared.ai.hf_cloud_fallback import call_hf_vision, cloud_fallback_enabled
from shared.ai.model_cascade import CascadeOrchestrator

from shared.observability.otel_setup import get_tracer

from shared.storage.image_fetch import fetch_image_bytes
from shared.messages import get_message
log = structlog.get_logger()
tracer = get_tracer(__name__)


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
  "drawee_name": {"value": "...", "confidence": 0.0},
  "ifsc_code": {"value": "...", "confidence": 0.0},
  "account_number": {"value": "...", "confidence": 0.0},
  "instrument_category": {"value": "...", "confidence": 0.0}
}
If a field is illegible or not present, set value to null and confidence to 0.0.
Confidence range: 0.0 (illegible) to 1.0 (perfectly clear).
ifsc_code: the bank IFSC code printed on the cheque face (e.g. "SBIN0001234").

amount_words: the full amount in words. It often wraps onto a second line --
read EVERY line of the amount-in-words area and join them with a space into
one string ending at "only". Never return just the first line.

instrument_category: either "CHEQUE" or "DEMAND_DRAFT". Return "DEMAND_DRAFT"
only if the instrument has a printed "DEMAND DRAFT" header and/or a "D.D. NO."
box -- this is a separate pre-printed money-remittance instrument issued by
the bank itself, not a regular cheque written by a customer. Return "CHEQUE"
for anything else, including when uncertain -- CHEQUE is the default and the
safe answer.

account_number: the customer's account number printed on the cheque (separate
from the MICR band, and separate from micr_line -- never derive this by
guessing digit positions out of micr_line; real Indian CTS-2010 MICR bands
carry no account number at all, only cheque number + 9-digit sort code +
transaction code). Preserve leading zeros. Return null if not printed or not
legible -- never infer or truncate.

payee: The name HANDWRITTEN on the "Pay" line only, immediately after the
printed word "Pay". This is the RECIPIENT of the cheque, filled in by the
account holder when writing it. Do NOT confuse this with any PRINTED
company/business/person name found elsewhere on the cheque -- in
particular, a printed name appearing near the signature above "Partner /
Authorised Signatory" or after a printed "For" label identifies the
DRAWEE (the account holder who owns this cheque and is issuing it), which
is the opposite of the payee. If the handwriting on the Pay line is
illegible or in an unfamiliar script, return null for payee -- never
substitute the drawee's printed name or any other visible text as a guess.
Guessing a plausible-looking value is worse than returning null.

drawee_name: The PRINTED (not handwritten) account holder name, usually
appearing near the bottom-right signature area after a printed "For"
label (e.g. "For Asmita Construction") or directly above "Authorised
Signatory" / "Proprietor" / "Partner". This is the person or company that
OWNS this cheque and account -- never the payee. If no such printed name
is visible, return null.
"""

_DD_OCR_PROMPT = """
This image is an Indian bank DEMAND DRAFT (a pre-printed instrument issued by a bank, NOT a
customer-written cheque). Return JSON only, no explanation:
{
  "has_dd_header": {"value": true, "confidence": 0.0},
  "dd_number": {"value": "...", "confidence": 0.0},
  "dd_date": {"value": "...", "confidence": 0.0},
  "payee": {"value": "...", "confidence": 0.0},
  "remitter_name": {"value": "...", "confidence": 0.0},
  "issuing_branch": {"value": "...", "confidence": 0.0},
  "drawee_branch": {"value": "...", "confidence": 0.0},
  "amount_figures": {"value": "...", "confidence": 0.0},
  "amount_words": {"value": "...", "confidence": 0.0},
  "micr_line": {"value": "...", "confidence": 0.0}
}
If a field is illegible or not present, set value to null and confidence to 0.0. Never guess.

has_dd_header: true only if the words "DEMAND DRAFT" and/or a "D.D. NO." box are printed on this
instrument; false otherwise (for example a normal cheque with a "Pay" line).

payee: the name printed after the words "ON DEMAND PAY" (Hindi: "मांगे जाने पर"), i.e. the
beneficiary the draft is payable to. It is usually machine-printed. Do NOT return the text of the
"Issuing Branch" label, the Hindi/English caption lines, rubber-stamp text (bank collection stamps
such as "RESERVE BANK OF INDIA ...", branch round-stamps), or officer/staff names near the
signatures. If the line is not legible return null.

remitter_name: the purchaser/applicant name printed on the line that starts with "DD" followed by
the DD number (for example "DD 930183   KARTHIK V"), to the right of the number. null if absent.

issuing_branch: the branch name printed just under the bank name at the top left, above the
caption "(Issuing Branch)". drawee_branch: the branch name printed above the caption
"(Drawee Branch)" / "(अदाकर्ता शाखा)" near the bottom. Return the name only, never the caption.

dd_date: the date from the DDMMYYYY boxes at the top right. dd_number: the number in the "D.D. NO." box.
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
    drawee_name: Optional[str] = None             # printed "For <name>" near signature — account owner, not payee
    ifsc_code: Optional[str] = None
    cheque_number: Optional[str] = None           # parsed from micr_line, MICRParser.parse_ocr_text
    bank_branch_code: Optional[str] = None        # parsed from micr_line
    account_number: Optional[str] = None          # printed on the cheque face — a real OCR field,
                                                    # never derived from micr_line (see _OCR_PROMPT)
    instrument_category: str = "CHEQUE"            # "CHEQUE" | "DEMAND_DRAFT" — defaults CHEQUE,
                                                    # the safe fallback for silent/invalid model answers
    # DD-only fields (None for cheques) — filled by the DD-specific second pass
    remitter_name: Optional[str] = None            # purchaser/applicant printed after "DD <number>"
    issuing_branch: Optional[str] = None
    drawee_branch: Optional[str] = None
    overall_confidence: float = 0.0
    low_confidence_reason: Optional[str] = None
    # Structured form of low_confidence_reason's field list — cheque_workflow.py's
    # multisignal-rescue check needs to test set membership, not parse a log string.
    low_confidence_fields: list[str] = []
    degraded: bool = False
    cascade_level: int = 2
    principal_tag: Optional[str] = None
    sub_member_id: Optional[str] = None
    amount_mismatch: bool = False
    indic_refined_fields: list[str] = []        # which fields were re-run via IndicOCR
    # ── engine provenance (written to ImmuDB via CTS_INSTRUMENT_PASSPORT) ──
    ocr_engines_used: list[str] = []            # ordered: engines that actually ran
    indic_ocr_kill_switch_active: bool = False  # True when cts.indic_ocr.kill_mode=KC
    payee_reread_status: Optional[str] = None     # AGREE | DISAGREE | UNAVAILABLE | None (not applicable)
    payee_candidates: list[str] = []              # both readings when the two reads disagree (for the reviewer)
    micr_reread_status: Optional[str] = None      # AGREE | DISAGREE | UNAVAILABLE | PRIMARY_UNREAD
    micr_candidates: list[str] = []               # both readings of the cheque number / sort code when they disagree
    amount_reread_status: Optional[str] = None    # AGREE | DISAGREE | UNAVAILABLE | PRIMARY_UNREAD
    amount_candidates: list[str] = []


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
    with tracer.start_as_current_span("activity.ocr_extract") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        ai_config = await config_service.get_ai_config(inp.bank_id)
        min_confidence: float = ai_config["ai.ocr.min_confidence"]
        # NOT one of get_ai_config()'s fixed 8 keys — must be fetched directly,
        # or it silently resolves to "" forever and IndicOCR never runs even
        # when the service is genuinely up (real bug, fixed 2026-09-18).
        # Fail-open on config errors — same as the kill-switch lookup below;
        # a bad config read must not block OCR entirely.
        try:
            indic_ocr_url: str = await config_service.get("services.indic_ocr.url")
        except Exception:
            indic_ocr_url = ""
        indic_min_confidence: float = float(ai_config.get("ai.ocr.min_indic_confidence", 0.60))

        # ── Stage 1: Full image → GOT-OCR2 (GPU) or Tesseract (CPU fallback) ───
        raw = await _extract_got_ocr2(inp, orchestrator)
        if raw is None:
            # vLLM unavailable — try a real cloud vision fallback (config-gated,
            # off by default: see shared/ai/hf_cloud_fallback.py) before the
            # much weaker Tesseract-only path.
            raw = await _extract_hf_cloud(inp, config_service)
        if raw is None:
            raw = await _extract_tesseract(inp)
        if raw is None:
            return OCRActivityResult(
                outcome="HUMAN_REVIEW", degraded=True,
                low_confidence_reason="MODEL_UNAVAILABLE",
                ocr_engines_used=["got-ocr2.0:unavailable", "tesseract:unavailable"],
            )

        fields, cascade_level = raw

        # cascade_level == -1 signals Tesseract ran; -2 signals HF cloud fallback ran
        if cascade_level == -1:
            engines_used = ["tesseract:cpu-fallback"]
        elif cascade_level == -2:
            engines_used = ["hf-cloud:qwen2.5-vl-72b"]
        else:
            engines_used = [f"got-ocr2.0:cascade-{cascade_level}"]

        # ── Instrument type + DD second pass ──────────────────────────────────────
        _mc = fields.get("instrument_category", (None, 0.0))[0]
        model_cat = _mc if _mc in ("CHEQUE", "DEMAND_DRAFT") else "CHEQUE"
        header_ocr = await _header_says_dd(inp.image_url)
        dd_fields = None
        if model_cat == "DEMAND_DRAFT" or header_ocr is True:
            dd_fields = await _dd_pass(inp, orchestrator, config_service)
        dd_header = None
        if dd_fields is not None:
            hv = dd_fields["has_dd_header"][0]
            dd_header = hv if isinstance(hv, bool) else (str(hv).lower() == "true" if hv is not None else None)
        final_cat, unanimous, cat_signals = _resolve_category(model_cat, header_ocr, dd_header)
        fields["instrument_category"] = (final_cat, 1.0)
        remitter = issuing = drawee_branch = None
        amount_disagreement = None
        if final_cat == "DEMAND_DRAFT" and dd_fields is not None:
            s1_figures = fields.get("amount_figures", (None, 0.0))[0]
            for dst, src in (("payee", "payee"), ("amount_figures", "amount_figures"),
                             ("amount_words", "amount_words"), ("date", "dd_date")):
                val, conf = dd_fields[src]
                if dst == "date" and val and not _is_plausible_date(val):
                    continue   # e.g. the DD number read as a date -> keep stage-1 value / flag it
                if val:
                    fields[dst] = (val, conf)
            dd_figures = dd_fields["amount_figures"][0]
            if s1_figures and dd_figures and _amount_value(s1_figures) != _amount_value(dd_figures):
                amount_disagreement = f"dd_amount_read_disagreement: {s1_figures} vs {dd_figures}"
            db, dbc = dd_fields["drawee_branch"]
            if db:
                fields["drawee_name"] = (db, dbc)
            remitter = dd_fields["remitter_name"][0]
            issuing = dd_fields["issuing_branch"][0]
            drawee_branch = db
            engines_used.append("dd-pass")

        # ── IndicOCR kill switch ──────────────────────────────────────────────────
        # Fail-open: missing / unreadable config key = NONE (do not block OCR).
        indic_ks_active = False
        try:
            indic_ks_raw = await config_service.get("cts.indic_ocr.kill_mode")
            if indic_ks_raw == "KC":
                indic_ks_active = True
                log.warning("ocr.indic_ocr_kill_switch_active",
                            instrument_id=inp.instrument_id, bank_id=inp.bank_id)
        except Exception:
            pass

        # ── Stage 2: Indic zone refinement (skipped when KC or URL absent) ───────
        indic_refined: list[str] = []
        if indic_ocr_url and not indic_ks_active:
            indic_refined, indic_backend = await _refine_indic_zones(
                inp.image_url, inp.instrument_id, fields,
                indic_ocr_url, min_confidence, indic_min_confidence,
                bank_id=inp.bank_id, config_service=config_service,
            )
            if indic_refined:
                engines_used.append(indic_backend)
        elif indic_ks_active:
            log.info("ocr.indic_stage2_skipped_kill_switch",
                     instrument_id=inp.instrument_id, bank_id=inp.bank_id)

        # ── Stage 3: Confidence gate + amount cross-check ─────────────────────────
        # cts.micr_bank_code (Layer 3, per bank): the drawee bank's own 3-digit MICR bank code,
        # used to anchor the 9-digit sort code. Absent/malformed -> legacy fixed slice.
        micr_bank_code = None
        try:
            _bc = await config_service.get("cts.micr_bank_code")
            if isinstance(_bc, str) and _bc.isdigit() and len(_bc) == 3:
                micr_bank_code = _bc
        except Exception:
            pass
        result = _build_result(
            fields, min_confidence, cascade_level, indic_refined,
            routing_table, inp, engines_used, indic_ks_active,
            micr_bank_code=micr_bank_code,
        )
        updates: dict = {"remitter_name": remitter, "issuing_branch": issuing, "drawee_branch": drawee_branch}
        # The independent second reads (payee, MICR band, amount) are separate cloud/GPU calls: run them
        # concurrently so the activity's wall-clock is the slowest one, not their sum.
        _need_payee = final_cat == "CHEQUE" and bool(result.payee)
        import asyncio as _aio
        _payee_second, second = await _aio.gather(
            _payee_reread(inp, config_service) if _need_payee else _aio.sleep(0, result=None),
            _field_rereads(inp, config_service),
        )
        # Payee re-read gate (cheques only; a DD's payee is printed and has its own pass).
        if _need_payee:
            if _payee_second is None:
                updates["payee_reread_status"] = "UNAVAILABLE"
            else:
                try:
                    min_sim = _as_float(await config_service.get("cts.payee_reread_min_similarity"), 0.99)
                except Exception:
                    min_sim = 0.99
                if _payee_names_agree(result.payee, _payee_second, min_sim):
                    updates["payee_reread_status"] = "AGREE"
                else:
                    # Never show an unconfirmed handwritten name as fact — withhold it, keep both readings.
                    log.info("ocr.payee_reread_disagreement", instrument_id=inp.instrument_id, bank_id=inp.bank_id)
                    updates.update(
                        payee=None,
                        payee_reread_status="DISAGREE",
                        payee_candidates=[result.payee, _payee_second],
                        outcome="HUMAN_REVIEW",
                        low_confidence_fields=list(result.low_confidence_fields) + ["payee"],
                        low_confidence_reason="payee_reread_disagreement" + (
                            f"; {result.low_confidence_reason}" if result.low_confidence_reason else ""),
                    )
        # MICR number / sort code / amount second read (independent model, focused crop): `second` above.
        if second is None:
            updates["micr_reread_status"] = "UNAVAILABLE"
            updates["amount_reread_status"] = "UNAVAILABLE"
        else:
            extra_reasons, extra_fields = [], []
            p_num, p_sort = result.cheque_number, result.bank_branch_code
            s_num, s_sort = second.get("cheque_number"), second.get("sort_code")
            pairs = [(p, q) for p, q in ((p_num, s_num), (p_sort, s_sort)) if p and q]
            if not pairs:
                updates["micr_reread_status"] = "PRIMARY_UNREAD"
            elif all(_digits_agree(p, q) for p, q in pairs):
                updates["micr_reread_status"] = "AGREE"
            else:
                updates["micr_reread_status"] = "DISAGREE"
                cands = []
                for p, q in pairs:
                    if not _digits_agree(p, q):
                        cands += [str(p), str(q)]
                updates["micr_candidates"] = cands
                extra_reasons.append("micr_reread_disagreement")
                extra_fields.append("micr_line")
            p_amt, s_amt = result.amount_figures, second.get("amount_figures")
            if not (p_amt and s_amt):
                updates["amount_reread_status"] = "PRIMARY_UNREAD"
            elif _amounts_agree(p_amt, s_amt):
                updates["amount_reread_status"] = "AGREE"
            else:
                updates["amount_reread_status"] = "DISAGREE"
                updates["amount_candidates"] = [str(p_amt), str(s_amt)]
                extra_reasons.append("amount_reread_disagreement")
                extra_fields.append("amount_figures")
            if extra_reasons:
                log.info("ocr.field_reread_disagreement", instrument_id=inp.instrument_id, bank_id=inp.bank_id,
                         reasons=extra_reasons)
                prior = updates.get("low_confidence_reason") or result.low_confidence_reason
                updates["outcome"] = "HUMAN_REVIEW"
                updates["low_confidence_reason"] = "; ".join(extra_reasons) + (f"; {prior}" if prior else "")
                updates["low_confidence_fields"] = list(updates.get("low_confidence_fields", result.low_confidence_fields)) + extra_fields
        if not unanimous:
            # Signals disagree on CHEQUE vs DEMAND_DRAFT -> never pick silently.
            updates.update(
                outcome="HUMAN_REVIEW",
                low_confidence_reason=f"instrument_type_split: {cat_signals}",
                low_confidence_fields=list(result.low_confidence_fields) + ["instrument_category"],
            )
        elif amount_disagreement:
            updates.update(
                outcome="HUMAN_REVIEW",
                low_confidence_reason=amount_disagreement,
                low_confidence_fields=list(result.low_confidence_fields) + ["amount_figures"],
            )
        return result.model_copy(update=updates)


def _amount_value(raw) -> float | None:
    try:
        return float(re.sub(r"[^\d.]", "", str(raw)) or "nan")
    except ValueError:
        return None


def _is_plausible_date(raw) -> bool:
    """True only for a real calendar date: DD/MM/YYYY (any of - . / separators), or DDMMYYYY.
    strptime is too lenient ('658027' parses), so the shape is checked explicitly first."""
    from datetime import date
    text = str(raw).strip()
    m = re.fullmatch(r"(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{4})", text) or re.fullmatch(r"(\d{2})(\d{2})(\d{4})", text)
    if not m:
        return False
    try:
        date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return True
    except ValueError:
        return False


# ── Payee re-read gate ────────────────────────────────────────────────────────

_PAYEE_REREAD_PROMPT = (
    'This is a cropped strip of an Indian bank cheque containing the "Pay" line. Read ONLY the handwritten '
    'payee name after the word Pay. Spell it carefully letter by letter; do not guess or complete partial '
    'words. If any letter is unclear return null. '
    'Return JSON only: {"payee": {"value": "...", "confidence": 0.0}}'
)


def _payee_names_agree(a: str, b: str, min_similarity: float) -> bool:
    """Case, spacing, hyphens and punctuation are ignored; the letters themselves must match."""
    import difflib
    na = re.sub(r"[^A-Z0-9]", "", (a or "").upper())
    # The re-read prompt asks for null where a letter is unclear: those tokens are placeholders, not letters.
    nb = re.sub(r"[^A-Z0-9]", "", re.sub(r"null", "", (b or ""), flags=re.IGNORECASE).upper())
    if not na or not nb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= min_similarity


async def _payee_reread(inp, config_service) -> Optional[str]:
    """Independent second read of the Pay line from a zoomed, contrast-boosted crop. Cloud vision
    only when cts.allow_cloud_ai_fallback is on (the on-prem equivalent is the same crop sent to the
    vLLM queue). Returns the payee text, or None when it cannot be read / is unavailable."""
    try:
        if not await cloud_fallback_enabled(config_service, inp.bank_id):
            return None
        from PIL import ImageOps
        raw = await fetch_image_bytes(inp.image_url)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        crop = img.crop((0, int(h * 0.12), w, int(h * 0.45)))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        crop = ImageOps.autocontrast(crop.convert("L"), cutoff=1).convert("RGB")
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        # Independent second opinion: a DIFFERENT model from the primary read (configurable), then the
        # primary model as a fallback if the independent one is unreachable.
        try:
            first = await config_service.get("cts.payee_reread_model")
        except Exception:
            first = None
        models = [first if isinstance(first, str) and first else "qwen3-vl-32b"]
        if "qwen-72b" not in models:
            models.append("qwen-72b")
        for model in models:
            content = await call_hf_vision(config_service, buf.getvalue(), _PAYEE_REREAD_PROMPT, model=model, timeout=90.0)
            if not content:
                continue
            value = _parse_model_json(content).get("payee", {}).get("value")
            return None if value in (None, "", "null") else str(value)
        return None
    except Exception as exc:
        log.info("ocr.payee_reread_unavailable", instrument_id=inp.instrument_id, error=str(exc)[:120])
        return None


def _as_float(value, default: float) -> float:
    try:
        return float(value) if isinstance(value, (int, float, str)) and not isinstance(value, bool) else default
    except ValueError:
        return default


# ── MICR / amount second read ────────────────────────────────────────────────

_MICR_REREAD_PROMPT = (
    "This is the MICR band (bottom strip) of an Indian cheque or draft. Read the digits in E-13B font exactly as "
    "printed, left to right. Return JSON only: "
    '{"cheque_number": "6 digits or null", "sort_code": "9 digits or null"}. '
    "The cheque number is the first 6-digit group; the sort code is the next 9-digit group. "
    "Use null for any group you cannot read; never guess."
)
_AMOUNT_REREAD_PROMPT = (
    "This is an Indian bank cheque or demand draft. Read ONLY the amount written in FIGURES inside the rupee box "
    "(next to the rupee symbol). Return JSON only: "
    '{"amount_figures": "digits with commas/decimals as written, or null"}. Never guess; null if unclear.'
)


def _digits_agree(a, b) -> bool:
    da, db = re.sub(r"\D", "", str(a or "")), re.sub(r"\D", "", str(b or ""))
    return bool(da) and da == db


def _amount_float(raw) -> Optional[float]:
    text = re.sub(r"(?i)rs\.?|inr|/-|=|[A-Za-z\u20b9]", "", str(raw or "")).replace(",", "").strip()
    text = re.sub(r"[^\d.]", "", text).strip(".")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _amounts_agree(a, b) -> bool:
    fa, fb = _amount_float(a), _amount_float(b)
    return fa is not None and fb is not None and abs(fa - fb) < 0.5


async def _field_rereads(inp, config_service) -> Optional[dict]:
    """Independent second read of the MICR band (zoomed bottom strip) and the amount box, by a different
    model from the primary read. Cloud vision only when cts.allow_cloud_ai_fallback is on (the on-prem
    equivalent is the same crops sent to the vLLM queue). None when neither read is available."""
    try:
        if not await cloud_fallback_enabled(config_service, inp.bank_id):
            return None
        from PIL import ImageOps
        import asyncio as _aio
        raw = await fetch_image_bytes(inp.image_url)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        band = img.crop((0, int(h * 0.80), w, h))
        band = band.resize((band.width * 2, band.height * 2), Image.LANCZOS)
        band = ImageOps.autocontrast(band.convert("L"), cutoff=1).convert("RGB")
        b1, b2 = io.BytesIO(), io.BytesIO()
        band.save(b1, "PNG")
        img.save(b2, "JPEG", quality=92)
        try:
            first = await config_service.get("cts.field_reread_model")
        except Exception:
            first = None
        models = [first if isinstance(first, str) and first else "qwen3-vl-32b"]
        if "qwen-72b" not in models:
            models.append("qwen-72b")

        async def ask(image_bytes, prompt):
            for model in models:
                content = await call_hf_vision(config_service, image_bytes, prompt, model=model, timeout=90.0)
                if content:
                    try:
                        return _parse_model_json(content)
                    except Exception:
                        continue
            return None

        micr, amt = await _aio.gather(ask(b1.getvalue(), _MICR_REREAD_PROMPT), ask(b2.getvalue(), _AMOUNT_REREAD_PROMPT))
        if micr is None and amt is None:
            return None

        def clean(v):
            return None if v in (None, "", "null") else str(v)

        return {"cheque_number": clean((micr or {}).get("cheque_number")), "sort_code": clean((micr or {}).get("sort_code")),
                "amount_figures": clean((amt or {}).get("amount_figures"))}
    except Exception as exc:
        log.info("ocr.field_reread_unavailable", instrument_id=inp.instrument_id, error=str(exc)[:120])
        return None


# ── Instrument-type decision + DD second pass ────────────────────────────────

_DD_KEYS = ("has_dd_header", "dd_number", "dd_date", "payee", "remitter_name",
            "issuing_branch", "drawee_branch", "amount_figures", "amount_words", "micr_line")


def _parse_model_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _to_fields(parsed: dict, keys) -> dict:
    out: dict = {}
    for key in keys:
        entry = parsed.get(key) or {}
        if isinstance(entry, dict):
            out[key] = (entry.get("value"), float(entry.get("confidence", 0.0) or 0.0))
        else:
            out[key] = (None, 0.0)
    return out


async def _dd_pass(inp, orchestrator, config_service):
    """DD-specific second look: the cheque prompt reads the 'Issuing Branch' caption as the payee
    on a DD, so a DD gets its own prompt. Local model first, then the config-gated cloud fallback.
    Returns {field: (value, confidence)} or None when no vision model answered."""
    try:
        res = await orchestrator.call_ocr(image_url=inp.image_url, prompt=_DD_OCR_PROMPT, cheque_amount=0.0)
        return _to_fields(_parse_model_json(res.content), _DD_KEYS)
    except Exception as exc:
        log.warning("ocr.dd_pass_local_failed", instrument_id=inp.instrument_id, error=str(exc))
    try:
        if await cloud_fallback_enabled(config_service, inp.bank_id):
            content = await call_hf_vision(config_service, await fetch_image_bytes(inp.image_url), _DD_OCR_PROMPT)
            if content:
                return _to_fields(_parse_model_json(content), _DD_KEYS)
    except Exception as exc:
        log.warning("ocr.dd_pass_cloud_failed", instrument_id=inp.instrument_id, error=str(exc))
    return None


def _configure_tesseract(pytesseract_mod) -> None:
    """Point pytesseract at the standard Windows install (winget -> Program Files); no-op elsewhere."""
    if platform.system() != "Windows":
        return
    for _p in (get_message("CTS_C_PROGRAM_FILES_TESSERACT_OCR"),
               get_message("CTS_C_PROGRAM_FILES_X86_TESSERACT")):
        if os.path.isfile(_p):
            pytesseract_mod.pytesseract.tesseract_cmd = _p
            return


async def _header_says_dd(image_url: str):
    """Independent, model-free signal: Tesseract over the top band of the image looking for the
    printed 'DEMAND DRAFT' / 'D.D. NO.' header. True/False, or None when it cannot run."""
    try:
        import asyncio as _aio
        import re as _re
        import pytesseract
        _configure_tesseract(pytesseract)
        raw = await fetch_image_bytes(image_url)

        def _read() -> str:
            img = Image.open(io.BytesIO(raw)).convert("L")
            w, h = img.size
            band = img.crop((0, 0, w, int(h * 0.30)))
            return pytesseract.image_to_string(band, lang="eng", config=get_message("CTS_PSM_6"))

        text = await _aio.to_thread(_read)
        return bool(_re.search(r"DEMAND\s*DRAFT|D\.?\s?D\.?\s*NO", text, _re.IGNORECASE))
    except Exception as exc:
        log.info("ocr.header_check_unavailable", error=str(exc)[:120])
        return None


def _resolve_category(model_cat, header_ocr, dd_header):
    """Majority of the independent signals that exist. Returns (category, unanimous, signals)."""
    sig = {"model": model_cat,
           "header_ocr": None if header_ocr is None else ("DEMAND_DRAFT" if header_ocr else "CHEQUE"),
           "dd_pass": None if dd_header is None else ("DEMAND_DRAFT" if dd_header else "CHEQUE")}
    votes = [v for v in sig.values() if v is not None]
    n_dd = votes.count("DEMAND_DRAFT")
    n_ch = votes.count("CHEQUE")
    if n_dd == 0 or n_ch == 0:
        return votes[0], True, sig
    if n_dd == n_ch:                       # tie: trust the primary model, but flag it
        return model_cat, False, sig
    return ("DEMAND_DRAFT" if n_dd > n_ch else "CHEQUE"), False, sig


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
        "drawee_name":    _field("drawee_name"),
        "ifsc_code":      _field("ifsc_code"),
        "account_number": _field("account_number"),
        "instrument_category": _field("instrument_category"),
    }
    return fields, cascade_result.cascade_level


# ── Stage 1a: real cloud vision fallback (config-gated, off by default) ──────

async def _extract_hf_cloud(
    inp: OCRActivityInput,
    config_service: Any,
) -> Optional[tuple[dict[str, tuple[Optional[str], float]], int]]:
    """
    Real Hugging Face-hosted Qwen2.5-VL-72B call, used only when
    cts.allow_cloud_ai_fallback is explicitly enabled for this bank (default
    False — see shared/ai/hf_cloud_fallback.py's module docstring for why
    this is a deliberate architecture exception, not the norm).

    Returns (fields_dict, -2) on success, None if disabled/token missing/
    call fails — callers fall through to Tesseract exactly as they do today
    on any other vLLM-unavailable path.
    """
    from shared.ai.hf_cloud_fallback import call_hf_vision, cloud_fallback_enabled

    if not await cloud_fallback_enabled(config_service, inp.bank_id):
        return None

    try:
        image_bytes = await fetch_image_bytes(inp.image_url)
    except Exception as exc:
        log.warning("ocr.hf_cloud_image_fetch_failed", instrument_id=inp.instrument_id, error=str(exc))
        return None

    content = await call_hf_vision(config_service, image_bytes, _OCR_PROMPT)
    if content is None:
        return None

    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
    except Exception as exc:
        log.warning("ocr.hf_cloud_invalid_json", instrument_id=inp.instrument_id, error=str(exc))
        return None

    fields: dict[str, tuple[Optional[str], float]] = {}
    for key in ("micr_line", "amount_figures", "amount_words", "date", "payee", "drawee_name", "ifsc_code", "account_number", "instrument_category"):
        entry = parsed.get(key) or {}
        value = entry.get("value") if isinstance(entry, dict) else None
        confidence = float(entry.get("confidence", 0.0)) if isinstance(entry, dict) else 0.0
        fields[key] = (value, confidence)

    log.info(
        "ocr.hf_cloud_fallback_used",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        payee_found=bool(fields["payee"][0]),
        micr_found=bool(fields["micr_line"][0]),
    )
    return fields, -2   # -2 = HF cloud fallback, not local vLLM cascade


# ── Stage 1b: Tesseract CPU fallback ─────────────────────────────────────────

async def _extract_tesseract(
    inp: OCRActivityInput,
) -> Optional[tuple[dict[str, tuple[Optional[str], float]], int]]:
    """
    Tesseract 5 CPU fallback when GOT-OCR2.0/vLLM is unavailable.

    Returns (fields_dict, -1) on success (-1 signals Tesseract ran, not vLLM cascade).
    Returns None if Tesseract itself is unavailable or fails.

    Confidence for Tesseract results is set conservatively (0.55–0.70) so the
    confidence gate in _build_result correctly routes to HUMAN_REVIEW.
    Tesseract accuracy on handwritten Indian cheques is lower than GOT-OCR2.0 —
    HUMAN_REVIEW is always the right outcome for Tesseract results.
    """
    import io
    import re
    try:
        import httpx
        from PIL import Image
        import pytesseract
        # Windows: winget installs to Program Files/Tesseract-OCR
        import os as _os, platform as _plat
        if _plat.system() == "Windows":
            for _p in [
                get_message("CTS_C_PROGRAM_FILES_TESSERACT_OCR"),
                get_message("CTS_C_PROGRAM_FILES_X86_TESSERACT"),
            ]:
                if _os.path.isfile(_p):
                    pytesseract.pytesseract.tesseract_cmd = _p
                    break
    except ImportError:
        return None

    try:
        img = Image.open(io.BytesIO(await fetch_image_bytes(inp.image_url))).convert("RGB")

        # PSM 6 = assume a single uniform block of text — reasonable for cheques
        raw_text = pytesseract.image_to_string(img, lang="eng", config=get_message("CTS_PSM_6_OEM_1"))
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

        # ── Heuristic field extraction ────────────────────────────────────────
        # Normalise: strip OCR noise chars, collapse whitespace
        clean = re.sub(r'[^\x20-\x7E\n₹]', ' ', raw_text)

        # Date: DD/MM/YYYY, DD-MM-YYYY, or box-digit format "0]7 [0]4] 2]0]2[4"
        date_val: Optional[str] = None
        # Standard delimited
        m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b', clean)
        if m:
            date_val = f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"
        else:
            # Box-digit: extract 8 consecutive digits from bracket-noise
            digits_only = re.sub(r'[^0-9]', '', clean[:200])   # header area only
            if len(digits_only) >= 8:
                d = digits_only[:8]
                date_val = f"{d[0:2]}/{d[2:4]}/{d[4:8]}"

        # Amount figures: ₹/Rs prefix OR largest Indian-format number in the text
        amount_figures: Optional[str] = None
        m = re.search(r'(?:Rs\.?|₹)\s*([\d,\s]+(?:\.\d{1,2})?)', clean, re.IGNORECASE)
        if m:
            amount_figures = re.sub(r'[\s,]', '', m.group(1))
        else:
            # Indian format: 1,00,000 or 1, 00, 000 (spaces from box scan)
            nums = re.findall(r'\b\d{1,2}(?:[,\s]\s*\d{2})+(?:\.\d{2})?\b', clean)
            if nums:
                amount_figures = re.sub(r'[\s,]', '', nums[0])

        # Payee: line after "Pay" keyword only. "For <Name>" is the DRAWEE
        # (account holder issuing the cheque), the opposite of the payee —
        # never substitute one for the other (real bug fixed 2026-09-18,
        # same class of error as CLOUD_EXTRACT_PROMPT's payee_name rule).
        payee_val: Optional[str] = None
        for i, ln in enumerate(lines):
            if re.search(r'\bPay\b', ln, re.IGNORECASE):
                candidate = re.sub(r'\bPay\b', '', ln, flags=re.IGNORECASE).strip()
                if not candidate and i + 1 < len(lines):
                    candidate = lines[i + 1]
                if candidate and len(candidate) > 2:
                    payee_val = candidate
                    break

        # Drawee name: printed "For <Name>" near the signature — the account
        # holder/owner of the cheque, not the payee.
        drawee_val: Optional[str] = None
        m = re.search(r'\bFor\s+([A-Z][A-Za-z0-9 .&,\'-]{3,60})', clean)
        if m:
            drawee_val = m.group(1).strip()

        # MICR line: digit-heavy line at the bottom (last 5 lines)
        micr_val: Optional[str] = None
        for ln in reversed(lines[-6:]):
            digits = re.sub(r'\D', '', ln)
            if len(digits) >= 15:   # MICR has cheque# + routing + account = ~27 digits
                micr_val = ln.strip()
                break

        log.info(
            "ocr.tesseract_fallback",
            instrument_id=inp.instrument_id,
            date=date_val,
            amount=amount_figures,
            payee_found=bool(payee_val),
            micr_found=bool(micr_val),
        )

        # Conservative confidence — always routes to HUMAN_REVIEW via confidence gate
        _CONF = 0.60
        # Pure text heuristic -- Tesseract has no vision classification, just
        # check for the printed "DEMAND DRAFT" header / "D.D. NO." label.
        category_val = (
            "DEMAND_DRAFT"
            if re.search(r'\bDEMAND\s+DRAFT\b|\bD\.?\s?D\.?\s*NO\b', clean, re.IGNORECASE)
            else "CHEQUE"
        )
        fields: dict[str, tuple[Optional[str], float]] = {
            "micr_line":      (micr_val,      _CONF if micr_val else 0.0),
            "amount_figures": (amount_figures, _CONF if amount_figures else 0.0),
            "amount_words":   (None,           0.0),   # Tesseract can't parse words→numbers reliably
            "date":           (date_val,       _CONF if date_val else 0.0),
            "drawee_name":    (drawee_val,     _CONF if drawee_val else 0.0),
            "payee":          (payee_val,      _CONF if payee_val else 0.0),
            "ifsc_code":      (None,           0.0),
            "account_number": (None,           0.0),
            "instrument_category": (category_val, _CONF),
        }
        return fields, -1   # -1 = Tesseract, not vLLM cascade level

    except Exception as exc:
        log.warning("ocr.tesseract_failed", instrument_id=inp.instrument_id, error=str(exc))
        return None


# ── Stage 2 ───────────────────────────────────────────────────────────────────

_CLOUD_VLM_INDIC_CONFIDENCE_CAP = 0.65   # below any realistic min_confidence gate — see docstring


async def _cloud_vlm_refine_zone(
    zone_bytes: bytes, field: str, config_service: Any,
) -> Optional[tuple[str, float]]:
    """Last-resort zone-level retry against the cloud VLM when the IndicOCR service's own result
    doesn't clear indic_min_confidence.

    Found live 2026-09-22: PaddleOCR and Tesseract both fail on handwritten Indic script — tested
    against a real cheque's handwritten Kannada payee name, PaddleOCR returned garbage
    ("YPhg be ?"), Tesseract returned empty text. The cloud VLM (already the Stage 1 fallback) read
    the same crop correctly. Gated by cts.allow_cloud_ai_fallback — same opt-in, off-by-default
    config used by _extract_hf_cloud; never called unless the bank has explicitly enabled it.
    Returns None on any failure or when the model itself reports it couldn't read the text —
    never fabricates a value.
    """
    _field_hint = {
        "payee": get_message("CTS_THE_PAYEE_NAME_ONLY_THE"),
        "amount_words": get_message("CTS_THE_AMOUNT_WRITTEN_IN_WORDS"),
    }.get(field, field)
    prompt = (
        f"This is a small crop from an Indian bank cheque, in an Indic script. Read {_field_hint}, "
        f"exactly as handwritten or printed, in its native script — do not translate or "
        f"transliterate it. Respond in JSON only: "
        f'{{"value": "<native-script text, or null if illegible or not present in this crop>", '
        f'"confidence": <0.0-1.0>}}.'
    )
    try:
        content = await call_hf_vision(config_service, zone_bytes, prompt)
        if content is None:
            return None
        text = content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        value = data.get("value")
        confidence = float(data.get("confidence", 0.0))
    except Exception:
        return None
    if not value or detect_script(value) != "indic":
        return None
    # Never trust the model's self-reported confidence at face value: observed live, it can
    # confidently (0.9+) hallucinate fluent-looking text with no relation to the actual image on
    # illegible handwriting. Cap well under any realistic min_confidence gate so a cloud-VLM
    # reading always still needs the same human-review path a genuine low-confidence OCR result
    # would get — it is a best-effort assist, never an authoritative replacement.
    capped_confidence = min(confidence, _CLOUD_VLM_INDIC_CONFIDENCE_CAP)
    return value, capped_confidence


async def _refine_indic_zones(
    image_url: str,
    instrument_id: str,
    fields: dict[str, tuple[Optional[str], float]],
    indic_ocr_url: str,
    min_confidence: float,
    indic_min_confidence: float,
    field_to_zone: Optional[dict[str, str]] = None,
    bank_id: str = "",
    config_service: Any = None,
) -> tuple[list[str], str]:
    """
    For each SCRIPT_ADAPTIVE result field that contains Indic text (or has low
    confidence), fetch the cheque image, crop the zone, and call IndicOCR.
    Mutates `fields` in place with the refined value when IndicOCR wins.
    Returns (refined_field_names, engine_label).

    field_to_zone maps result-field names to zone names — defaults to the
    inward _RESULT_FIELD_TO_ZONE mapping; callers on a different path (e.g.
    outward vision_extract_and_check) may pass their own mapping.

    bank_id/config_service: when given, a field that IndicOCR could not confidently read is
    retried once against the cloud VLM (see _cloud_vlm_refine_zone) before being left as-is.
    """
    _ftz = field_to_zone if field_to_zone is not None else _RESULT_FIELD_TO_ZONE

    needs_refine: list[tuple[str, str, str]] = []
    for result_field, zone_name in _ftz.items():
        text, conf = fields.get(result_field, (None, 0.0))
        script = identify_indic_script(text or "")
        if script is not None or (text is None and conf < min_confidence):
            needs_refine.append((result_field, zone_name, script or "devanagari"))

    if not needs_refine:
        return [], ""

    try:
        img = Image.open(io.BytesIO(await fetch_image_bytes(image_url, timeout=20.0))).convert("RGB")
    except Exception as exc:
        log.warning("ocr.indic_image_fetch_failed", instrument_id=instrument_id, error=str(exc))
        return [], ""

    refined: list[str] = []
    scripts_seen: set[str] = set()
    backend_used: str = "paddle"   # IndicOCR service default; may differ per zone

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
            backend_used = data.get("backend", backend_used)

            if detect_script(indic_text) == "indic" and indic_conf >= indic_min_confidence:
                fields[result_field] = (indic_text, indic_conf)
                refined.append(result_field)
                scripts_seen.add(script)
                log.info("ocr.indic_refined",
                         instrument_id=instrument_id, field=result_field,
                         script=script, confidence=indic_conf)
            elif config_service is not None and await cloud_fallback_enabled(config_service, bank_id):
                cloud_result = await _cloud_vlm_refine_zone(buf.getvalue(), result_field, config_service)
                if cloud_result is not None:
                    cloud_text, cloud_conf = cloud_result
                    fields[result_field] = (cloud_text, cloud_conf)
                    refined.append(result_field)
                    scripts_seen.add(script)
                    backend_used = "hf-cloud-indic"
                    log.info("ocr.indic_refined_via_cloud_vlm",
                             instrument_id=instrument_id, field=result_field,
                             script=script, confidence=cloud_conf,
                             indic_ocr_confidence=indic_conf)

        except Exception as exc:
            log.warning("ocr.indic_zone_failed",
                        instrument_id=instrument_id, field=result_field, error=str(exc))

    script_label = "+".join(sorted(scripts_seen)) if scripts_seen else "none"
    engine_label = f"indic_ocr:{backend_used}/{script_label}" if refined else ""
    return refined, engine_label


# ── Stage 3 ───────────────────────────────────────────────────────────────────

def _build_result(
    fields: dict[str, tuple[Optional[str], float]],
    min_confidence: float,
    cascade_level: int,
    indic_refined: list[str],
    routing_table: Optional[dict],
    inp: OCRActivityInput,
    engines_used: Optional[list[str]] = None,
    indic_ks_active: bool = False,
    micr_bank_code: Optional[str] = None,
) -> OCRActivityResult:
    """Apply confidence gate, MICR routing, amount cross-check, build final result."""
    _engines = engines_used or []

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
    drawee_val   = fields.get("drawee_name",     (None, 0.0))[0]
    ifsc_raw     = fields.get("ifsc_code",       (None, 0.0))
    ifsc_code    = (
        ifsc_raw[0].strip().upper()
        if isinstance(ifsc_raw[0], str) and ifsc_raw[0] and ifsc_raw[1] >= 0.3
        else None
    )
    account_number = fields.get("account_number", (None, 0.0))[0]
    _raw_category = fields.get("instrument_category", (None, 0.0))[0]
    instrument_category = _raw_category if _raw_category in ("CHEQUE", "DEMAND_DRAFT") else "CHEQUE"

    # An optional field the model did not return (account number, drawee name, category) is not an unreadable one: only the
    # fields every cheque must yield, plus any optional field that was actually read, count towards the score.
    _must_read = set(_PRIMARY) | {"micr_line"}
    all_confs = [c for name, (value, c) in fields.items() if name in _must_read or value not in (None, "")]
    overall = sum(all_confs) / len(all_confs) if all_confs else 0.0

    principal_tag, sub_member_id = _route_micr(micr_line, routing_table, inp.instrument_id)
    micr_parsed = MICRParser.parse_ocr_text(micr_line or "", bank_code=micr_bank_code)
    cheque_number = micr_parsed["cheque_number"]
    bank_branch_code = micr_parsed["bank_branch_code"]

    if low_fields:
        log.info("ocr.low_confidence", instrument_id=inp.instrument_id, low_fields=low_fields)
        return OCRActivityResult(
            outcome="HUMAN_REVIEW",
            micr_line=micr_line,
            amount_figures=amt_figures,
            amount_words=amt_words,
            date=date_val,
            payee=payee_val,
            drawee_name=drawee_val,
            overall_confidence=overall,
            low_confidence_reason=f"low_confidence_fields: {low_fields}",
            low_confidence_fields=low_fields,
            cascade_level=cascade_level,
            principal_tag=principal_tag,
            sub_member_id=sub_member_id,
            indic_refined_fields=indic_refined,
            ocr_engines_used=_engines,
            indic_ocr_kill_switch_active=indic_ks_active,
            cheque_number=cheque_number,
            bank_branch_code=bank_branch_code,
            account_number=account_number,
            instrument_category=instrument_category,
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
            ocr_engines_used=_engines,
            indic_ocr_kill_switch_active=indic_ks_active,
            cheque_number=cheque_number,
            bank_branch_code=bank_branch_code,
            account_number=account_number,
            instrument_category=instrument_category,
        )

    return OCRActivityResult(
        outcome="PROCEED",
        micr_line=micr_line,
        amount_figures=amt_figures,
        amount_words=amt_words,
        date=date_val,
        payee=payee_val,
        drawee_name=drawee_val,
        ifsc_code=ifsc_code,
        overall_confidence=overall,
        cascade_level=cascade_level,
        principal_tag=principal_tag,
        sub_member_id=sub_member_id,
        indic_refined_fields=indic_refined,
        ocr_engines_used=_engines,
        indic_ocr_kill_switch_active=indic_ks_active,
        cheque_number=cheque_number,
        bank_branch_code=bank_branch_code,
        account_number=account_number,
        instrument_category=instrument_category,
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
