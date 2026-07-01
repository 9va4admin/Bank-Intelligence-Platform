"""
Alteration detection activity — Qwen2-VL 72B multi-modal analysis of cheque images.

Detection layers:
  1. Pixel-level field analysis — overwriting, erasure, correction fluid per field
  2. Ink-physics anomaly — pen-pressure variation, ink flow irregularities, bleed patterns
  3. Paper-fibre distortion — mechanical erasure stress marks at 200 DPI greyscale
  4. Correction-fluid spectral signature — bright-white patch with unnaturally sharp edges
  5. Chemical alteration stain — solvent halos, colour shift around altered region
  6. Overwriting brightness — luminance inconsistency within a single ink stroke

Result: per-field bounding boxes, per-anomaly-type scores, overall tamper_risk_score.
alteration_detected=True + high tamper_risk → STP_RETURN in decision activity.
Model unavailable → degraded=True, requires_human_review=True (never auto-return).
"""

from typing import Optional
import json

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillSwitchStatus

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.alteration")


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class BoundingBox(BaseModel):
    """Pixel coordinates of an anomalous region within the cheque image."""
    model_config = ConfigDict(frozen=True)
    x: int
    y: int
    w: int
    h: int
    label: str


class InkPhysicsAnomaly(BaseModel):
    """Ink-flow and pen-pressure anomaly for a specific field."""
    model_config = ConfigDict(frozen=True)
    field: str
    score: float = Field(ge=0.0, le=1.0)
    # Pen pressure dropped mid-digit (common in traced overwriting)
    pressure_inconsistency: bool = False
    # Ink spread outside normal capillary pattern (chemical / heavy press)
    bleed_anomaly: bool = False
    # Flow direction reversal mid-stroke (indicates re-inking after erasure)
    flow_reversal: bool = False
    bbox: Optional[BoundingBox] = None


class PaperFibreAnomaly(BaseModel):
    """Paper surface distortion consistent with mechanical erasure."""
    model_config = ConfigDict(frozen=True)
    field: str
    score: float = Field(ge=0.0, le=1.0)
    # Raised paper fibres visible in greyscale scan ≥ 200 DPI
    fibre_distortion_detected: bool = False
    # Glossy patch from re-sizing agent applied after erasure
    gloss_patch_detected: bool = False
    bbox: Optional[BoundingBox] = None


class CorrectionFluidAnomaly(BaseModel):
    """Bright-white patch with sharp boundary — correction fluid signature."""
    model_config = ConfigDict(frozen=True)
    field: str
    score: float = Field(ge=0.0, le=1.0)
    # Luminance spike well above surrounding paper baseline
    luminance_spike_detected: bool = False
    # Edge sharpness ratio (correction fluid has unnaturally crisp boundary)
    edge_sharpness_ratio: Optional[float] = None
    bbox: Optional[BoundingBox] = None


class ChemicalAlterationAnomaly(BaseModel):
    """Solvent halo or colour-shift pattern indicating chemical erasure."""
    model_config = ConfigDict(frozen=True)
    field: str
    score: float = Field(ge=0.0, le=1.0)
    # Solvent-damaged paper shows characteristic halo ring
    halo_detected: bool = False
    # Colour temperature shift around altered region
    colour_shift_detected: bool = False
    bbox: Optional[BoundingBox] = None


class FieldAlterationDetail(BaseModel):
    """Complete alteration assessment for a single cheque field."""
    model_config = ConfigDict(frozen=True)
    field_name: str
    altered: bool
    confidence: float = Field(ge=0.0, le=1.0)
    original_value_legible: Optional[str] = None   # if erasure is partial
    current_value: Optional[str] = None
    ink_physics: Optional[InkPhysicsAnomaly] = None
    paper_fibre: Optional[PaperFibreAnomaly] = None
    correction_fluid: Optional[CorrectionFluidAnomaly] = None
    chemical_alteration: Optional[ChemicalAlterationAnomaly] = None


class AlterationActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    image_url: str
    instrument_id: str
    bank_id: str
    scan_dpi: int = 200   # NPCI CTS 2010 minimum; higher = better fibre detection
    smb_id: Optional[str] = None  # populated for sub-member bank instruments


class AlterationActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    alteration_detected: bool
    tamper_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # Physical anomaly composite score (ink + paper + fluid + chemical)
    physical_anomaly_score: float = Field(default=0.0, ge=0.0, le=1.0)
    altered_fields: list[str] = []
    field_details: list[FieldAlterationDetail] = []
    ink_physics_anomalies: list[InkPhysicsAnomaly] = []
    paper_fibre_anomalies: list[PaperFibreAnomaly] = []
    correction_fluid_anomalies: list[CorrectionFluidAnomaly] = []
    chemical_alteration_anomalies: list[ChemicalAlterationAnomaly] = []
    requires_human_review: bool = False
    degraded: bool = False
    model_version: str = "qwen2-vl-72b"
    kill_switch_mode: str = "NONE"           # "NONE" | "KP" | "KC"
    kill_switch_scope: Optional[str] = None  # "GLOBAL" | "SB_OWN" | "SMB"


# ---------------------------------------------------------------------------
# Qwen2-VL prompt
# ---------------------------------------------------------------------------

_ALTERATION_PROMPT = """
You are an expert forensic document examiner specialising in cheque fraud detection.
Analyse the provided cheque image at the highest fidelity available. The scan is at {dpi} DPI.

Your task is to detect physical evidence of alteration across SIX detection layers:

LAYER 1 — FIELD CONTENT ANALYSIS
For each field (amount_figures, amount_words, date, payee_name, drawer_name, account_number, micr_band):
  • Read the current printed value
  • Identify any overwriting: ink on top of earlier ink, overlapping strokes, multi-layer text
  • Identify any erasure: missing ink, paper whitening, visible scrape marks
  • If partially erased, attempt to read original value (report as original_value_legible)

LAYER 2 — INK-PHYSICS ANOMALY
For each field's ink strokes, examine at sub-pixel level:
  • Pen-pressure variation within a single character (legitimate writing is consistent)
    — Pressure drop mid-stroke indicates traced or computer-printed overwriting
  • Ink-flow direction: legitimate ballpoint/gel leaves a characteristic start-thicken-taper pattern
    — Reversed or restarted flow indicates ink applied after erasure or overwriting
  • Ink bleed pattern: fresh ink on disturbed paper bleeds asymmetrically
    — Symmetric bleed = original; asymmetric bleed = applied to compromised paper surface
  • Ink colour temperature: same pen produces consistent hue; different hue = different writing session

LAYER 3 — PAPER-FIBRE DISTORTION (critical at ≥200 DPI greyscale)
  • Mechanical erasure (rubber/blade) leaves raised paper fibres that scatter light differently
    — Look for: irregular grey patch with higher local variance than surrounding paper
    — Look for: micro-texture disruption around suspected alteration site
  • Chemical erasure (bleach/solvent) destroys paper sizing, leaving a dull, slightly sunken zone
    — Re-sized paper (to conceal chemical erasure) shows a glossy patch — higher luminance
  • Unaltered paper has consistent fibre direction from manufacturing

LAYER 4 — CORRECTION FLUID SPECTRAL SIGNATURE
  • Correction fluid produces a bright-white opaque patch with unnaturally sharp edges
    — Local luminance ≥ 95th percentile of page luminance = strong indicator
    — Edge sharpness ratio: correction fluid boundaries are sharper than printed ink edges
    — Paper shows through at thin coverage points (semi-transparent coverage pattern)
  • White-out under ink: check if printed text above a bright patch shows ink settling inconsistency

LAYER 5 — CHEMICAL ALTERATION STAIN
  • Organic solvents (acetone, bleach) leave a characteristic halo ring around the treated area
    — Ring diameter and density correlates with solvent quantity used
  • Potassium permanganate (ink eradicator) leaves a brown/yellow residue ring
  • Chemical agents shift paper colour temperature: unaltered paper is warm-white; chemically treated paper shifts cool or yellowish

LAYER 6 — OVERWRITING BRIGHTNESS
  • A stroke written over correction fluid sits on a smoother surface than surrounding ink
    — Result: slightly higher local luminance under overwritten strokes
  • Two overlapping inks produce micro-interference patterns at edges
  • Examine ink density per unit area: higher density = multiple ink layers

MANDATORY OUTPUT FORMAT (respond in JSON only, no explanation outside JSON):
{{
  "fields": [
    {{
      "field_name": "amount_figures | amount_words | date | payee_name | drawer_name | account_number | micr_band",
      "altered": true | false,
      "confidence": 0.0–1.0,
      "current_value": "as printed",
      "original_value_legible": "partially visible original, or null",
      "ink_physics": {{
        "field": "<field_name>",
        "score": 0.0–1.0,
        "pressure_inconsistency": true | false,
        "bleed_anomaly": true | false,
        "flow_reversal": true | false,
        "bbox": {{"x": int, "y": int, "w": int, "h": int, "label": "description"}} | null
      }} | null,
      "paper_fibre": {{
        "field": "<field_name>",
        "score": 0.0–1.0,
        "fibre_distortion_detected": true | false,
        "gloss_patch_detected": true | false,
        "bbox": {{"x": int, "y": int, "w": int, "h": int, "label": "description"}} | null
      }} | null,
      "correction_fluid": {{
        "field": "<field_name>",
        "score": 0.0–1.0,
        "luminance_spike_detected": true | false,
        "edge_sharpness_ratio": float | null,
        "bbox": {{"x": int, "y": int, "w": int, "h": int, "label": "description"}} | null
      }} | null,
      "chemical_alteration": {{
        "field": "<field_name>",
        "score": 0.0–1.0,
        "halo_detected": true | false,
        "colour_shift_detected": true | false,
        "bbox": {{"x": int, "y": int, "w": int, "h": int, "label": "description"}} | null
      }} | null
    }}
  ],
  "overall_tamper_risk": 0.0–1.0,
  "physical_anomaly_score": 0.0–1.0
}}

Be conservative: only flag true if physical evidence is visible. Confidence < 0.60 = uncertain.
Do NOT assume alteration from amount alone. Physical evidence is the only basis for flagging.
"""


# ---------------------------------------------------------------------------
# Activity implementation
# ---------------------------------------------------------------------------

async def detect_alteration(
    inp: AlterationActivityInput,
    vllm_client=None,
    kill_switch_status: Optional[KillSwitchStatus] = None,
) -> AlterationActivityResult:
    """
    Detect physical cheque alterations using Qwen2-VL 72B.

    Six detection layers covering ink physics, paper fibre, correction fluid,
    chemical alteration, overwriting, and field content.
    Degrades gracefully on model failure — never assumes alteration without evidence.

    Kill-switch behaviour (RBI mandate):
      KC (Kill Complete) — Qwen2-VL is NOT called; returns requires_human_review=True.
      KP (Kill Partial)  — Qwen2-VL runs normally; result carries kill_switch_mode="KP"
                           so that synthesise_decision can force HUMAN_REVIEW at the
                           decision backstop (dual-checkpoint pattern).
    """
    with tracer.start_as_current_span("activity.detect_alteration") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        span.set_attribute("scan_dpi", inp.scan_dpi)

        # ── Kill-switch entry checkpoint (KC path) ─────────────────────────
        # Checked BEFORE any vLLM call. If KC is active, skip Vision AI entirely.
        # KP is recorded on the result but does not block the AI call here —
        # the decision backstop enforces HUMAN_REVIEW for KP.
        resolved_mode = "NONE"
        resolved_scope: Optional[str] = None

        if kill_switch_status is not None and kill_switch_status.is_active:
            resolved_mode = kill_switch_status.mode.value
            resolved_scope = kill_switch_status.scope.value if kill_switch_status.scope else None

            span.set_attribute("kill_switch_mode", resolved_mode)
            span.set_attribute("kill_switch_scope", resolved_scope or "")

            if kill_switch_status.blocks_vision_ai:  # KC
                log.warning(
                    "alteration_activity.kill_switch_kc",
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    smb_id=inp.smb_id,
                    scope=resolved_scope,
                )
                return AlterationActivityResult(
                    alteration_detected=False,
                    tamper_risk_score=0.0,
                    physical_anomaly_score=0.0,
                    requires_human_review=True,
                    degraded=False,
                    kill_switch_mode="KC",
                    kill_switch_scope=resolved_scope,
                )

            # KP — log and continue to AI
            log.info(
                "alteration_activity.kill_switch_kp",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                smb_id=inp.smb_id,
                scope=resolved_scope,
            )
        # ── End kill-switch entry checkpoint ───────────────────────────────

        prompt = _ALTERATION_PROMPT.format(dpi=inp.scan_dpi)

        try:
            response = await vllm_client.chat.completions.create(
                model="qwen2-vl-72b",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": inp.image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                extra_body={"queue": "cts-vision"},
                timeout=120,
            )
            raw_text = response.choices[0].message.content

        except Exception as exc:
            log.warning(
                "alteration_activity.model_unavailable",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return AlterationActivityResult(
                alteration_detected=False,
                tamper_risk_score=0.0,
                physical_anomaly_score=0.0,
                requires_human_review=True,
                degraded=True,
            )

        # Parse structured JSON from model output
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            # Model returned non-JSON — route to human review
            log.warning(
                "alteration_activity.parse_error",
                instrument_id=inp.instrument_id,
                raw_length=len(raw_text),
            )
            return AlterationActivityResult(
                alteration_detected=False,
                tamper_risk_score=0.0,
                physical_anomaly_score=0.0,
                requires_human_review=True,
                degraded=True,
            )

        # Build per-field detail objects
        field_details: list[FieldAlterationDetail] = []
        ink_anomalies: list[InkPhysicsAnomaly] = []
        paper_anomalies: list[PaperFibreAnomaly] = []
        fluid_anomalies: list[CorrectionFluidAnomaly] = []
        chemical_anomalies: list[ChemicalAlterationAnomaly] = []
        altered_fields: list[str] = []

        for f in data.get("fields", []):
            ink_raw = f.get("ink_physics")
            paper_raw = f.get("paper_fibre")
            fluid_raw = f.get("correction_fluid")
            chem_raw = f.get("chemical_alteration")

            ink_obj = _parse_ink(ink_raw) if ink_raw else None
            paper_obj = _parse_paper(paper_raw) if paper_raw else None
            fluid_obj = _parse_fluid(fluid_raw) if fluid_raw else None
            chem_obj = _parse_chemical(chem_raw) if chem_raw else None

            detail = FieldAlterationDetail(
                field_name=f.get("field_name", "unknown"),
                altered=bool(f.get("altered", False)),
                confidence=float(f.get("confidence", 0.0)),
                original_value_legible=f.get("original_value_legible"),
                current_value=f.get("current_value"),
                ink_physics=ink_obj,
                paper_fibre=paper_obj,
                correction_fluid=fluid_obj,
                chemical_alteration=chem_obj,
            )
            field_details.append(detail)

            if detail.altered:
                altered_fields.append(detail.field_name)
            if ink_obj:
                ink_anomalies.append(ink_obj)
            if paper_obj:
                paper_anomalies.append(paper_obj)
            if fluid_obj:
                fluid_anomalies.append(fluid_obj)
            if chem_obj:
                chemical_anomalies.append(chem_obj)

        tamper_risk = float(data.get("overall_tamper_risk", 0.0))
        physical_score = float(data.get("physical_anomaly_score", 0.0))
        alteration_detected = bool(altered_fields) or tamper_risk >= 0.5

        span.set_attribute("tamper_risk_score", tamper_risk)
        span.set_attribute("physical_anomaly_score", physical_score)
        span.set_attribute("altered_field_count", len(altered_fields))

        log.info(
            "alteration_activity.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            alteration_detected=alteration_detected,
            tamper_risk_score=tamper_risk,
            physical_anomaly_score=physical_score,
            altered_fields=altered_fields,
        )

        return AlterationActivityResult(
            alteration_detected=alteration_detected,
            tamper_risk_score=tamper_risk,
            physical_anomaly_score=physical_score,
            altered_fields=altered_fields,
            field_details=field_details,
            ink_physics_anomalies=ink_anomalies,
            paper_fibre_anomalies=paper_anomalies,
            correction_fluid_anomalies=fluid_anomalies,
            chemical_alteration_anomalies=chemical_anomalies,
            requires_human_review=alteration_detected,
            kill_switch_mode=resolved_mode,
            kill_switch_scope=resolved_scope,
        )


# ---------------------------------------------------------------------------
# Parse helpers (keep main function readable)
# ---------------------------------------------------------------------------

def _parse_bbox(raw: Optional[dict]) -> Optional[BoundingBox]:
    if not raw:
        return None
    return BoundingBox(
        x=int(raw.get("x", 0)),
        y=int(raw.get("y", 0)),
        w=int(raw.get("w", 0)),
        h=int(raw.get("h", 0)),
        label=str(raw.get("label", "")),
    )


def _parse_ink(raw: dict) -> InkPhysicsAnomaly:
    return InkPhysicsAnomaly(
        field=raw.get("field", "unknown"),
        score=float(raw.get("score", 0.0)),
        pressure_inconsistency=bool(raw.get("pressure_inconsistency", False)),
        bleed_anomaly=bool(raw.get("bleed_anomaly", False)),
        flow_reversal=bool(raw.get("flow_reversal", False)),
        bbox=_parse_bbox(raw.get("bbox")),
    )


def _parse_paper(raw: dict) -> PaperFibreAnomaly:
    return PaperFibreAnomaly(
        field=raw.get("field", "unknown"),
        score=float(raw.get("score", 0.0)),
        fibre_distortion_detected=bool(raw.get("fibre_distortion_detected", False)),
        gloss_patch_detected=bool(raw.get("gloss_patch_detected", False)),
        bbox=_parse_bbox(raw.get("bbox")),
    )


def _parse_fluid(raw: dict) -> CorrectionFluidAnomaly:
    return CorrectionFluidAnomaly(
        field=raw.get("field", "unknown"),
        score=float(raw.get("score", 0.0)),
        luminance_spike_detected=bool(raw.get("luminance_spike_detected", False)),
        edge_sharpness_ratio=raw.get("edge_sharpness_ratio"),
        bbox=_parse_bbox(raw.get("bbox")),
    )


def _parse_chemical(raw: dict) -> ChemicalAlterationAnomaly:
    return ChemicalAlterationAnomaly(
        field=raw.get("field", "unknown"),
        score=float(raw.get("score", 0.0)),
        halo_detected=bool(raw.get("halo_detected", False)),
        colour_shift_detected=bool(raw.get("colour_shift_detected", False)),
        bbox=_parse_bbox(raw.get("bbox")),
    )
