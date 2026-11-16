"""
OCR Stub Server — mimics the vLLM OpenAI-compatible chat completions API.

Used by Cut 1, Cut 2, and Cut 3 integration tests instead of real GOT-OCR2/Qwen2-VL GPU.

Scenario encoding: embed one of these tokens in the image URL:
  ?scenario=low_confidence    → OCR returns confidence < 0.5 → HUMAN_REVIEW
  ?scenario=amount_mismatch   → figures/words mismatch → HUMAN_REVIEW
  ?scenario=model_unavailable → returns HTTP 503 → activity degrades gracefully
  (nothing / any other)       → high-confidence PROCEED result

Run standalone:
  python -m tests.integration.stubs.ocr_server          (port 8010)
  OCR_STUB_PORT=8011 python -m tests.integration.stubs.ocr_server

The server also serves a minimal /ocr endpoint for IndicOCR-style zone requests
(used when indic_ocr_url is configured in Cut 2/3 tests).
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

# Exported constant — imported by cut conftest files
OCR_STUB_PORT = int(os.environ.get("OCR_STUB_PORT", "18010"))

app = FastAPI(title="ASTRA OCR Stub", docs_url=None, redoc_url=None)


# ── Deterministic OCR payloads ──────────────────────────────────────────────

_HIGH_CONF_FIELDS = {
    "micr_line":      {"value": "500025033290062", "confidence": 0.97},
    "amount_figures": {"value": "95000",           "confidence": 0.96},
    "amount_words":   {"value": "Ninety Five Thousand Only", "confidence": 0.95},
    "date":           {"value": "25-08-2026",      "confidence": 0.98},
    "payee":          {"value": "Pradeep Kumar",   "confidence": 0.94},
    "ifsc_code":      {"value": "SYNB0003011",     "confidence": 0.92},
    "account_number": {"value": "4242424242",      "confidence": 0.93},
    "depositor_name": {"value": "Pradeep Kumar",   "confidence": 0.93},
}

_LOW_CONF_FIELDS = {
    "micr_line":      {"value": "500025033290062", "confidence": 0.91},
    "amount_figures": {"value": "95000",           "confidence": 0.40},   # below threshold
    "amount_words":   {"value": "Ninety Five",     "confidence": 0.38},   # below threshold
    "date":           {"value": "25-08-2026",      "confidence": 0.92},
    "payee":          {"value": None,              "confidence": 0.30},   # below threshold
    "ifsc_code":      {"value": "SYNB0003011",     "confidence": 0.91},
}

_MISMATCH_FIELDS = {
    "micr_line":      {"value": "500025033290062", "confidence": 0.97},
    "amount_figures": {"value": "95000",           "confidence": 0.96},
    "amount_words":   {"value": "One Lakh Only",   "confidence": 0.95},  # ≠ figures
    "date":           {"value": "25-08-2026",      "confidence": 0.98},
    "payee":          {"value": "Pradeep Kumar",   "confidence": 0.94},
    "ifsc_code":      {"value": "SYNB0003011",     "confidence": 0.92},
}

_OUTWARD_HIGH_CONF = {
    "micr_line":      {"value": "600012003300456", "confidence": 0.97},
    "amount_figures": {"value": "220000",          "confidence": 0.96},
    "amount_words":   {"value": "Two Lakh Twenty Thousand Only", "confidence": 0.95},
    "date":           {"value": "25-08-2026",      "confidence": 0.98},
    "payee":          {"value": "Dinesh Kumar Vemula", "confidence": 0.94},
    "ifsc_code":      {"value": "UTIB0000426",     "confidence": 0.92},
    "account_number": {"value": "4242424242",      "confidence": 0.93},   # deposit-slip account (the MICR band carries none)
    "depositor_name": {"value": "Pradeep Kumar",   "confidence": 0.93},   # deposit-slip depositor
}


def _extract_scenario(image_url: str) -> str:
    m = re.search(r"[?&]scenario=([^&]+)", image_url or "")
    return m.group(1) if m else "high_confidence"


def _fields_for(scenario: str, is_outward: bool) -> dict:
    if is_outward:
        return _OUTWARD_HIGH_CONF if scenario == "high_confidence" else _LOW_CONF_FIELDS
    if scenario == "low_confidence":
        return _LOW_CONF_FIELDS
    if scenario == "amount_mismatch":
        return _MISMATCH_FIELDS
    return _HIGH_CONF_FIELDS


def _openai_response(content: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 150, "total_tokens": 350},
    }


# What image the "model" was actually given: a real vLLM can only read http(s)/data URLs, so a data URI is the proof an
# image arrived. sha256 of the decoded bytes lets a test compare it with the file it uploaded.
RECEIVED: list[dict] = []


def _remember_image(image_url: str) -> None:
    import base64
    import hashlib
    if image_url.startswith("data:") and "," in image_url:
        raw = base64.b64decode(image_url.split(",", 1)[1])
        RECEIVED.append({"kind": "data_uri", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "head": image_url[:30]})
    else:
        RECEIVED.append({"kind": "reference", "url": image_url[:120]})


@app.get("/received")
async def received():
    return RECEIVED


# What a specific image "reads" as: sha256 of its bytes -> field overrides. Lets a test cheque read as the cheque it is declared to be
# (the model itself is a stand-in either way). Unregistered images keep the default reading.
REGISTERED: dict[str, dict] = {}


@app.post("/register")
async def register(request: Request):
    body = await request.json()
    REGISTERED[body["sha256"]] = body["fields"]
    return {"registered": len(REGISTERED)}


def _registered_fields(image_url: str) -> dict:
    import base64
    import hashlib
    if image_url.startswith("data:") and "," in image_url:
        return REGISTERED.get(hashlib.sha256(base64.b64decode(image_url.split(",", 1)[1])).hexdigest(), {})
    return {}


# ── Chat completions endpoint (vLLM / OpenAI compatible) ────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "got-ocr2-stub")

    # Extract image URL (and any text prompt) from messages
    image_url = ""
    prompt_text = ""
    for msg in body.get("messages", []):
        content = msg.get("content", [])
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_url = part.get("image_url", {}).get("url", "")
                elif isinstance(part, dict) and part.get("type") == "text":
                    prompt_text += part.get("text", "")

    # security_features asks whether the four CTS-2010 features are present: a stand-in reading says all are.
    if "void_pantograph" in prompt_text:
        return JSONResponse(_openai_response(json.dumps({
            k: {"present": True, "confidence": 0.95}
            for k in ("void_pantograph", "rupee_symbol", "micro_lettering", "printer_name_cts2010")}), model))

    # detect_signatures asks the vision model for signature_count / signature_bboxes: answer that shape (a stand-in reading, one signature).
    if "signature_count" in prompt_text:
        return JSONResponse(_openai_response(json.dumps(
            {"signature_count": 1, "signature_bboxes": [[0.2, 0.2, 0.8, 0.8]], "signature_fraud_flags": []}), model))

    _remember_image(image_url)
    scenario = _extract_scenario(image_url)

    if scenario == "model_unavailable":
        raise HTTPException(status_code=503, detail="Model unavailable (test stub)")

    is_outward = "outward" in image_url.lower()
    fields = {**_fields_for(scenario, is_outward), **_registered_fields(image_url)}
    content = json.dumps(fields)
    return JSONResponse(_openai_response(content, model))


# ── IndicOCR-style zone endpoint ────────────────────────────────────────────

@app.post("/ocr")
async def ocr_zone(request: Request):
    """Stub for IndicOCR zone refinement. Returns deterministic Indic text."""
    return JSONResponse({
        "text": "प्रदीप कुमार",
        "confidence": 0.88,
        "backend": "paddle",
        "script": "devanagari",
    })


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "ocr-stub"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=OCR_STUB_PORT, log_level="warning")
