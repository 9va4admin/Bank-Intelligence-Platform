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

app = FastAPI(title="ASTRA OCR Stub", docs_url=None, redoc_url=None)


# ── Deterministic OCR payloads ──────────────────────────────────────────────

_HIGH_CONF_FIELDS = {
    "micr_line":      {"value": "500025033290062", "confidence": 0.97},
    "amount_figures": {"value": "95000",           "confidence": 0.96},
    "amount_words":   {"value": "Ninety Five Thousand Only", "confidence": 0.95},
    "date":           {"value": "25-08-2026",      "confidence": 0.98},
    "payee":          {"value": "Pradeep Kumar",   "confidence": 0.94},
    "ifsc_code":      {"value": "SYNB0003011",     "confidence": 0.92},
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


# ── Chat completions endpoint (vLLM / OpenAI compatible) ────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "got-ocr2-stub")

    # Extract image URL from messages
    image_url = ""
    for msg in body.get("messages", []):
        content = msg.get("content", [])
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_url = part.get("image_url", {}).get("url", "")
                    break

    scenario = _extract_scenario(image_url)

    if scenario == "model_unavailable":
        raise HTTPException(status_code=503, detail="Model unavailable (test stub)")

    is_outward = "outward" in image_url.lower()
    fields = _fields_for(scenario, is_outward)
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
    port = int(os.environ.get("OCR_STUB_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
