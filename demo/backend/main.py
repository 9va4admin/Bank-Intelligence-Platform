#!/usr/bin/env python3
"""ASTRA Demo Backend

Single FastAPI service that simulates the full CTS pipeline:
- Inward cheque processing (drawee bank perspective)
- Vision LLM vs OCR comparison for Cat C/D/E
- Real cheque data from seed JSON files

Runs as 5 instances (one per bank) via Docker-compose.
BANK_ID env var controls which bank this instance serves.
"""

import json
import os
import asyncio
import time
import random
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ----- startup ----------------------------------------------------------- #

BANK_ID = os.environ.get("BANK_ID", "srcb")
SEED_DIR = Path("/seed")  # mounted via Docker volume
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001")

# Load all seed data at startup
def _load(fname):
    p = SEED_DIR / fname
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []

ALL_BANKS: list = _load("banks.json")
ALL_CUSTOMERS: list = _load("customers.json")
ALL_CHEQUES: list = _load("cheques.json")
ALL_CBS: list = _load("cbs_accounts.json")
ALL_VAULT: list = _load("signature_vault.json")
ALL_PPS: list = _load("pps_records.json")
ALL_CANCELLED: list = _load("cancelled_leaves.json")
ALL_DUPLICATES: list = _load("duplicate_registry.json")

MANIFEST: dict = {}
manifest_path = SEED_DIR / "image_manifest.json"
if manifest_path.exists():
    MANIFEST = json.loads(manifest_path.read_text(encoding="utf-8"))

# Index by bank
THIS_BANK = next((b for b in ALL_BANKS if b["bank_id"] == BANK_ID), {})
BANKS_MAP = {b["bank_id"]: b for b in ALL_BANKS}

# Cheques presented TO this bank (presentee_bank_id == BANK_ID)
PRESENTEE_CHEQUES = [c for c in ALL_CHEQUES if c["presentee_bank_id"] == BANK_ID]
# Cheques drawn ON this bank (drawee_bank_id == BANK_ID)
DRAWEE_CHEQUES = [c for c in ALL_CHEQUES if c["drawee_bank_id"] == BANK_ID]

CBS_MAP = {a["account_number"]: a for a in ALL_CBS}
VAULT_MAP = {v["account_number"]: v for v in ALL_VAULT}
PPS_MAP = {p["account_number"]: p for p in ALL_PPS}
CANCELLED_MAP = {c["account_number"]: c for c in ALL_CANCELLED}
DUPLICATE_SET = {d["cheque_id"] for d in ALL_DUPLICATES}

# ----- FastAPI app ------------------------------------------------------- #

app = FastAPI(
    title=f"ASTRA Demo - {THIS_BANK.get('name', BANK_ID)}",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve seed images as static files
if (SEED_DIR / "images").exists():
    app.mount("/images", StaticFiles(directory=str(SEED_DIR / "images")), name="images")
if (SEED_DIR / "signatures").exists():
    app.mount("/signatures", StaticFiles(directory=str(SEED_DIR / "signatures")), name="signatures")


# ----- models ------------------------------------------------------------ #

class BankInfo(BaseModel):
    bank_id: str
    name: str
    short: str
    type: str
    ifsc_prefix: str
    micr_code: str
    branch: str
    color_primary: str
    color_accent: str
    port_ui: int
    port_api: int


class ChequeStatus(BaseModel):
    cheque_id: str
    status: str                    # PENDING | PROCESSING | STP_CONFIRM | STP_RETURN | HUMAN_REVIEW
    stage: str                     # current pipeline stage
    decision_ms: Optional[int] = None
    return_reason: Optional[str] = None
    fraud_score: Optional[float] = None
    ocr_result: Optional[dict] = None
    vision_result: Optional[dict] = None
    vision_catches_ocr_miss: bool = False


class ProcessRequest(BaseModel):
    cheque_id: str
    simulate_speed_ms: int = 800   # total simulated pipeline time


class PipelineStageEvent(BaseModel):
    cheque_id: str
    stage: str
    status: str       # OK | WARN | FAIL
    detail: str
    ms: int


# ----- helpers ------------------------------------------------------------ #

CAT_DESCRIPTIONS = {
    "A": "Clean STP - passes all checks",
    "B": "Amount figures/words mismatch - OCR detects",
    "C": "Overwritten amount - OCR misses, Vision LLM catches",
    "D": "Tampered date (year changed) - OCR misses, Vision LLM catches",
    "E": "CANCELLED stamp - OCR misses, Vision LLM catches",
    "F": "Stale cheque (>90 days) - rule engine",
    "G": "Duplicate instrument - registry check",
    "H": "CTS image quality failure",
    "I": "Signature mismatch - drawee vault",
    "J": "Stop payment active - drawee CBS",
    "K": "Insufficient funds - drawee CBS",
    "L": "PPS amount mismatch - drawee PPS vault",
    "M": "Account frozen - drawee CBS",
}


def simulate_ocr(cheque: dict) -> dict:
    """Simulate GOT-OCR2 extraction. Cat C/D/E: OCR gets fooled."""
    cat = cheque.get("category", "A")
    ocr_vs = cheque.get("ocr_vs_vision", {})

    base = {
        "engine": "GOT-OCR2.0",
        "micr_serial": cheque.get("serial_number", ""),
        "payee_name": cheque.get("payee_name", ""),
        "cheque_date": cheque.get("cheque_date", ""),
        "amount_figures": cheque.get("amount_figures", 0),
        "amount_words": cheque.get("amount_words", ""),
        "confidence": 0.97,
        "flags": [],
    }

    if cat == "C":
        # OCR reads the fraud (overwritten) amount — it has no ink-layer awareness
        base["amount_figures"] = ocr_vs.get("ocr_reads_fraud_amount", cheque.get("amount_figures"))
        base["amount_words"] = ocr_vs.get("ocr_reads_fraud_words", cheque.get("amount_words"))
        base["confidence"] = 0.96
        base["flags"] = []  # OCR finds nothing wrong
        base["ocr_verdict"] = "PASS - all fields extracted cleanly"

    elif cat == "D":
        # OCR reads the tampered (new) year — date looks valid to OCR
        base["cheque_date"] = cheque.get("cheque_date", "")  # new date (not stale)
        base["confidence"] = 0.95
        base["flags"] = []  # OCR passes the date as valid
        base["ocr_verdict"] = "PASS - date within validity window"

    elif cat == "E":
        # OCR reads through the CANCELLED stamp - extracts text fields successfully
        base["confidence"] = 0.88
        base["flags"] = []
        base["ocr_verdict"] = "PASS - all text fields extracted (stamp not detected by OCR)"

    elif cat == "B":
        base["flags"] = ["AMOUNT_MISMATCH"]
        base["ocr_verdict"] = "FAIL - figures/words mismatch detected"

    else:
        base["ocr_verdict"] = "PASS"

    return base


def simulate_vision_llm(cheque: dict) -> dict:
    """Simulate Qwen2-VL Vision LLM analysis. Catches what OCR misses."""
    cat = cheque.get("category", "A")
    ocr_vs = cheque.get("ocr_vs_vision", {})

    base = {
        "model": "Qwen2-VL-72B",
        "queue": "cts-vision-l2",
        "inference_ms": random.randint(380, 520),
        "findings": [],
        "overall_tamper_risk": 0.02,
        "verdict": "CLEAN",
        "vision_verdict": "PASS",
    }

    if cat == "C":
        base["findings"] = [
            {
                "field": "amount_figures",
                "finding": "INK_LAYER_ANOMALY",
                "detail": (
                    f"Two distinct ink layers detected. L1 (original): faint ink consistent with "
                    f"original cheque fill - reads {ocr_vs.get('original_amount_display', '')}. "
                    f"Correction fluid (Tipp-Ex) residue band present. "
                    f"L2 (overwrite): fresh dark ink reads {ocr_vs.get('fraud_amount_display', '')}. "
                    f"Confidence: 0.93"
                ),
                "severity": "CRITICAL",
            }
        ]
        base["overall_tamper_risk"] = 0.94
        base["verdict"] = "FRAUD_DETECTED"
        base["vision_verdict"] = (
            f"FAIL - amount overwrite detected. Original: "
            f"{ocr_vs.get('original_amount_display', '')} | "
            f"Fraudulent overwrite: {ocr_vs.get('fraud_amount_display', '')}"
        )
        base["catches_ocr_miss"] = True
        base["ocr_passed_but_vision_caught"] = True

    elif cat == "D":
        base["findings"] = [
            {
                "field": "cheque_date",
                "finding": "DATE_YEAR_TAMPER",
                "detail": (
                    f"Correction fluid residue detected beneath year digits. "
                    f"UV-fluorescence anomaly in year field. "
                    f"Original year {ocr_vs.get('original_year', '')} overwritten with "
                    f"{ocr_vs.get('new_year', '')}. "
                    f"Original date {ocr_vs.get('orig_date', '')} would be stale (>90 days). "
                    f"Confidence: 0.89"
                ),
                "severity": "CRITICAL",
            }
        ]
        base["overall_tamper_risk"] = 0.89
        base["verdict"] = "FRAUD_DETECTED"
        base["vision_verdict"] = (
            f"FAIL - date tamper detected. Year changed "
            f"{ocr_vs.get('original_year', '')} -> {ocr_vs.get('new_year', '')}. "
            f"True instrument date: {ocr_vs.get('orig_date', '')} (STALE)"
        )
        base["catches_ocr_miss"] = True
        base["ocr_passed_but_vision_caught"] = True

    elif cat == "E":
        base["findings"] = [
            {
                "field": "instrument_face",
                "finding": "CANCELLED_STAMP",
                "detail": (
                    "Diagonal red rubber-stamp overlay detected spanning full instrument face. "
                    "Text: 'CANCELLED'. Stamp ink is separate layer above cheque text. "
                    "Instrument is void and must not be cleared. "
                    "Confidence: 0.97"
                ),
                "severity": "CRITICAL",
            }
        ]
        base["overall_tamper_risk"] = 0.97
        base["verdict"] = "VOID_INSTRUMENT"
        base["vision_verdict"] = (
            "FAIL - CANCELLED stamp detected across instrument face. "
            "Void instrument. Must not be presented for clearing."
        )
        base["catches_ocr_miss"] = True
        base["ocr_passed_but_vision_caught"] = True

    elif cat in ("I",):
        base["findings"] = [
            {
                "field": "signature",
                "finding": "SIGNATURE_ANALYSED",
                "detail": "Signature present. Layout analysis passed. Match score via Siamese network: 0.61 (below threshold).",
                "severity": "INFO",
            }
        ]
        base["verdict"] = "SIGNATURE_CHECK_REQUIRED"

    return base


def simulate_pipeline(cheque: dict) -> dict:
    """Run the full pipeline and return all stage results."""
    cat = cheque.get("category", "A")
    cbs_acct = CBS_MAP.get(cheque.get("drawee_account", ""), {})
    pps = PPS_MAP.get(cheque.get("drawee_account", ""), None)
    cancelled = CANCELLED_MAP.get(cheque.get("drawee_account", ""), None)
    is_duplicate = cheque["cheque_id"] in DUPLICATE_SET

    stages = []

    def stage(name, status, detail, ms=0):
        stages.append({"stage": name, "status": status, "detail": detail, "ms": ms})

    # Stage 1: CTS 2010 image compliance
    if cat == "H":
        stage("cts_image_validate", "FAIL", "Image quality below CTS 2010 threshold: skew > 3 degrees, resolution < 100dpi", 12)
        return {"outcome": "STP_RETURN", "return_reason": "CTS_IMAGE_QUALITY", "stages": stages, "decision_ms": 12}
    stage("cts_image_validate", "OK", "CTS 2010 compliant: 200dpi, skew < 0.5 deg, MICR band clean", 11)

    # Stage 2: OCR extraction
    ocr = simulate_ocr(cheque)
    ocr_ms = random.randint(45, 80)
    if cat == "B":
        stage("ocr_extract", "FAIL",
              f"Amount mismatch: figures={ocr['amount_figures']:,} | words={cheque.get('original_words', ocr['amount_words'])}",
              ocr_ms)
        return {"outcome": "STP_RETURN", "return_reason": "AMOUNT_MISMATCH", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr}
    stage("ocr_extract", "OK", ocr.get("ocr_verdict", "PASS"), ocr_ms)

    # Stage 3: Stale cheque check
    if cat == "F":
        stage("stale_check", "FAIL", f"Cheque date {cheque['cheque_date']} is >90 days old", 3)
        return {"outcome": "STP_RETURN", "return_reason": "STALE_CHEQUE", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr}
    stage("stale_check", "OK", f"Cheque date {cheque['cheque_date']} within validity window", 3)

    # Stage 4: Duplicate check
    if is_duplicate:
        stage("duplicate_check", "FAIL", f"Instrument {cheque['cheque_id']} already presented and cleared", 5)
        return {"outcome": "STP_RETURN", "return_reason": "DUPLICATE_INSTRUMENT", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr}
    stage("duplicate_check", "OK", "No duplicate found in registry", 5)

    # Stage 5: Vision LLM analysis
    vision = simulate_vision_llm(cheque)
    vision_ms = vision.get("inference_ms", 450)
    if cat in ("C", "D", "E"):
        stage("vision_llm", "FAIL", vision.get("vision_verdict", ""), vision_ms)
        reason_map = {
            "C": "AMOUNT_OVERWRITE_FRAUD",
            "D": "DATE_TAMPER_FRAUD",
            "E": "CANCELLED_INSTRUMENT",
        }
        return {
            "outcome": "STP_RETURN",
            "return_reason": reason_map[cat],
            "stages": stages,
            "decision_ms": sum(s["ms"] for s in stages),
            "ocr_result": ocr,
            "vision_result": vision,
            "vision_catches_ocr_miss": True,
            "key_insight": f"OCR returned PASS. Vision LLM returned FAIL. Fraud prevented by Vision LLM alone.",
        }
    stage("vision_llm", "OK",
          f"No tampering detected. Tamper risk: {vision['overall_tamper_risk']:.2f}", vision_ms)

    # Stage 6: Stop payment
    if cat == "J":
        stage("stop_payment", "FAIL",
              f"Stop payment instruction active on account {cheque.get('drawee_account','')[-4:]}", 8)
        return {"outcome": "STP_RETURN", "return_reason": "STOP_PAYMENT_ACTIVE", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr, "vision_result": vision}
    stage("stop_payment", "OK", "No stop payment instruction found", 8)

    # Stage 7: Account status
    acct_status = cbs_acct.get("status", "ACTIVE")
    if cat == "M" or acct_status == "FROZEN":
        stage("cbs_account_check", "FAIL",
              f"Account {cheque.get('drawee_account','')[-4:]} is FROZEN by bank order", 18)
        return {"outcome": "STP_RETURN", "return_reason": "ACCOUNT_FROZEN", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr, "vision_result": vision}
    stage("cbs_account_check", "OK",
          f"Account ACTIVE | Balance band: {cbs_acct.get('balance_band','SUFFICIENT')}", 18)

    # Stage 8: Balance check
    if cat == "K" or cbs_acct.get("balance_band") == "INSUFFICIENT":
        stage("balance_check", "FAIL",
              f"Insufficient funds. Cheque amount {cheque['amount_figures']:,} exceeds available balance", 12)
        return {"outcome": "STP_RETURN", "return_reason": "INSUFFICIENT_FUNDS", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr, "vision_result": vision}
    stage("balance_check", "OK", "Sufficient funds confirmed", 12)

    # Stage 9: Signature verification
    sig_vault = VAULT_MAP.get(cheque.get("drawee_account", ""), {})
    if cat == "I":
        stage("signature_verify", "FAIL",
              "Siamese network match score: 0.61 (threshold: 0.85). Signature mismatch — routing to Human Review", 95)
        return {"outcome": "HUMAN_REVIEW", "return_reason": "SIGNATURE_MISMATCH", "stages": stages,
                "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr, "vision_result": vision}
    sig_score = 0.94 + random.uniform(-0.02, 0.03)
    stage("signature_verify", "OK", f"Siamese match score: {sig_score:.2f} (threshold: 0.85)", 95)

    # Stage 10: PPS check
    if pps:
        pps_amount = pps.get("amount", 0)
        if cat == "L" or abs(pps_amount - cheque["amount_figures"]) > 1:
            stage("pps_check", "FAIL",
                  f"PPS mismatch: presented amount {cheque['amount_figures']:,} != PPS registered {pps_amount:,}", 6)
            return {"outcome": "STP_RETURN", "return_reason": "PPS_AMOUNT_MISMATCH", "stages": stages,
                    "decision_ms": sum(s["ms"] for s in stages), "ocr_result": ocr, "vision_result": vision}
        stage("pps_check", "OK", f"PPS match: amount {pps_amount:,} confirmed", 6)
    else:
        stage("pps_check", "OK", "No PPS record — standard clearing applies", 4)

    # Stage 11: Fraud scoring
    fraud_score = 0.08 + random.uniform(-0.04, 0.06)
    stage("fraud_score", "OK",
          f"XGBoost fraud score: {fraud_score:.3f} (threshold: 0.72). STP eligible.", 25)

    # Stage 12: STP confirm
    stage("stp_confirm", "OK",
          f"All {len(stages)} checks passed. STP CONFIRM — filing to NGCH.", 5)

    total_ms = sum(s["ms"] for s in stages)
    return {
        "outcome": "STP_CONFIRM",
        "stages": stages,
        "decision_ms": total_ms,
        "ocr_result": ocr,
        "vision_result": vision,
        "fraud_score": fraud_score,
    }


# ----- routes ------------------------------------------------------------ #

@app.get("/health/live")
async def liveness():
    return {"status": "ok", "bank_id": BANK_ID}


@app.get("/health/ready")
async def readiness():
    return {
        "status": "ready",
        "bank_id": BANK_ID,
        "bank_name": THIS_BANK.get("name", BANK_ID),
        "cheques_loaded": len(ALL_CHEQUES),
        "customers_loaded": len(ALL_CUSTOMERS),
    }


@app.get("/v1/bank", response_model=dict)
async def get_bank_info():
    return THIS_BANK


@app.get("/v1/banks")
async def get_all_banks():
    return ALL_BANKS


@app.get("/v1/customers")
async def get_customers(bank_id: str = Query(None)):
    if bank_id:
        return [c for c in ALL_CUSTOMERS if c["bank_id"] == bank_id]
    return [c for c in ALL_CUSTOMERS if c["bank_id"] == BANK_ID]


@app.get("/v1/cheques")
async def get_cheques(
    role: str = Query("presentee", description="presentee or drawee"),
    bank_id: str = Query(None),
    category: str = Query(None),
):
    bid = bank_id or BANK_ID
    if role == "drawee":
        result = [c for c in ALL_CHEQUES if c["drawee_bank_id"] == bid]
    else:
        result = [c for c in ALL_CHEQUES if c["presentee_bank_id"] == bid]

    if category:
        result = [c for c in result if c["category"] == category]
    return result


@app.get("/v1/cheques/{cheque_id}")
async def get_cheque(cheque_id: str):
    chq = next((c for c in ALL_CHEQUES if c["cheque_id"] == cheque_id), None)
    if not chq:
        raise HTTPException(status_code=404, detail=f"Cheque {cheque_id} not found")
    return chq


@app.post("/v1/pipeline/process")
async def process_cheque(req: ProcessRequest):
    """Run the full CTS pipeline for a single cheque. Returns all stage results."""
    chq = next((c for c in ALL_CHEQUES if c["cheque_id"] == req.cheque_id), None)
    if not chq:
        raise HTTPException(status_code=404, detail=f"Cheque {req.cheque_id} not found")

    # Simulate processing time
    await asyncio.sleep(req.simulate_speed_ms / 1000)

    result = simulate_pipeline(chq)
    result["cheque_id"] = req.cheque_id
    result["cheque"] = chq

    # Add image paths
    manifest_entry = MANIFEST.get(req.cheque_id, {})
    result["images"] = {
        "cheque_front": f"{BASE_URL}/images/{req.cheque_id}.png",
        "cheque_bw": f"{BASE_URL}/images/{req.cheque_id}_bw.png",
        "signature_specimen": f"{BASE_URL}/signatures/{chq.get('customer_id', '')}.png",
    }

    return result


@app.post("/v1/pipeline/batch")
async def process_batch(cheque_ids: List[str]):
    """Process multiple cheques — simulates parallel agent swarm."""
    results = []
    tasks = []
    for cid in cheque_ids:
        chq = next((c for c in ALL_CHEQUES if c["cheque_id"] == cid), None)
        if chq:
            tasks.append(chq)

    # Run all in parallel (simulated)
    async def _process(chq):
        await asyncio.sleep(random.uniform(0.1, 0.6))
        r = simulate_pipeline(chq)
        r["cheque_id"] = chq["cheque_id"]
        r["cheque"] = chq
        return r

    results = await asyncio.gather(*[_process(c) for c in tasks])
    return {
        "total": len(results),
        "stp_confirm": sum(1 for r in results if r.get("outcome") == "STP_CONFIRM"),
        "stp_return": sum(1 for r in results if r.get("outcome") == "STP_RETURN"),
        "human_review": sum(1 for r in results if r.get("outcome") == "HUMAN_REVIEW"),
        "vision_catches_ocr_miss": sum(1 for r in results if r.get("vision_catches_ocr_miss")),
        "results": results,
    }


@app.get("/v1/pipeline/summary")
async def pipeline_summary():
    """Pre-computed summary of what would happen if all presentee cheques were processed."""
    by_cat = {}
    for chq in PRESENTEE_CHEQUES:
        cat = chq["category"]
        if cat not in by_cat:
            by_cat[cat] = {"count": 0, "description": CAT_DESCRIPTIONS.get(cat, ""), "outcome": ""}

        # Determine expected outcome
        if cat == "A":
            by_cat[cat]["outcome"] = "STP_CONFIRM"
        elif cat in ("C", "D", "E"):
            by_cat[cat]["outcome"] = "STP_RETURN (Vision LLM)"
        else:
            by_cat[cat]["outcome"] = "STP_RETURN"
        by_cat[cat]["count"] += 1

    return {
        "bank_id": BANK_ID,
        "bank_name": THIS_BANK.get("name", BANK_ID),
        "total_presentee_cheques": len(PRESENTEE_CHEQUES),
        "total_drawee_cheques": len(DRAWEE_CHEQUES),
        "by_category": by_cat,
        "vision_llm_catches": sum(1 for c in PRESENTEE_CHEQUES if c["category"] in ("C", "D", "E")),
        "ocr_would_have_missed": sum(1 for c in PRESENTEE_CHEQUES if c["category"] in ("C", "D", "E")),
    }


@app.get("/v1/vault/signature/{account_number}")
async def get_signature(account_number: str):
    entry = VAULT_MAP.get(account_number)
    if not entry:
        raise HTTPException(status_code=404, detail="Signature not in vault")
    return entry


@app.get("/v1/cbs/account/{account_number}")
async def get_cbs_account(account_number: str):
    entry = CBS_MAP.get(account_number)
    if not entry:
        raise HTTPException(status_code=404, detail="Account not found in CBS")
    return entry


@app.get("/v1/stats")
async def get_stats():
    """Real-time stats for the demo dashboard."""
    return {
        "bank_id": BANK_ID,
        "name": THIS_BANK.get("name", BANK_ID),
        "type": THIS_BANK.get("type", "SB"),
        "customers": len([c for c in ALL_CUSTOMERS if c["bank_id"] == BANK_ID]),
        "presentee_cheques": len(PRESENTEE_CHEQUES),
        "drawee_cheques": len(DRAWEE_CHEQUES),
        "cat_breakdown": {
            cat: sum(1 for c in PRESENTEE_CHEQUES if c["category"] == cat)
            for cat in "ABCDEFGHIJKLM"
        },
    }
