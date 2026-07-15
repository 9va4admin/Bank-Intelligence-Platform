"""
Cloud AI cheque extraction — Miscellaneous / demo only.

DELIBERATE, TEMPORARY, EXPLICITLY-AUTHORIZED exception to
.claude/rules/ai-inference.md's "no cloud LLM APIs" rule and this
platform's Security Principle #7 ("Data Never Leaves Bank"). Added at the
user's direction to give live demos real (not simulated) AI extraction
ahead of an on-prem vLLM GPU deployment being available; the plan is to
swap the Hugging Face call below for a real CascadeOrchestrator/vLLM call
once GPU infra exists (see shared/ai/model_cascade.py for that pattern).

Never called by any production CTS clearing workflow — this router is
reachable only from the "Miscellaneous" nav section's Cloud AI Demo page,
clearly labelled in the UI as a temporary cloud-based demo. Still requires
the same authenticated session as every other route in this app; the
exception is scoped to "which model answers the extraction call", not to
"who can call this endpoint".

HF token is Vault-backed via config_service.get_secret() like every other
credential in this codebase — never hardcoded, never read from a .env or
Streamlit-secrets file (that's how ImageScanUtility/, the standalone
reference this prompt was adapted from, handles it, which is fine for a
throwaway local script but not for anything reachable from the real app).
"""
import base64
import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts/demo/cloud-extract", tags=["Demo — Cloud AI (temporary)"])

_HF_BASE_URL = "https://router.huggingface.co/v1"

_MODEL_MAPPING = {
    "qwen-32b": "Qwen/Qwen3-VL-32B-Instruct:featherless-ai",
    "qwen-72b": "Qwen/Qwen2.5-VL-72B-Instruct:ovhcloud",
    "gemma-27b": "google/gemma-3-27b-it:featherless-ai",
}

# Adapted from ImageScanUtility/prompt.py (already validated against real
# cheque images in that standalone tool) — kept here as ASTRA's own prompt
# constant rather than importing across the reference-folder boundary,
# matching .claude/rules/ai-inference.md's "Prompt Engineering Standards".
CLOUD_EXTRACT_PROMPT = """You are an expert Indian Bank Cheque OCR and Validation Engine.

Your task is to extract cheque information with maximum accuracy and perform consistency checks between fields.

IMPORTANT INSTRUCTIONS:

1. Read the ENTIRE cheque carefully.
2. Extract all visible information exactly as written.
3. Preserve leading zeros in cheque numbers, account numbers, MICR codes, and other numeric identifiers.
4. If a field is not visible or cannot be determined confidently, return null.
5. Return ONLY valid JSON.
6. Do not return markdown, comments, explanations, confidence scores, or extra text.

FIELD EXTRACTION RULES

* bank_name: Full bank name printed on the cheque.
* ifsc_code: Extract IFSC code exactly (format XXXX0XXXXXX, e.g. SBIN0001234).
* date: Convert to DD/MM/YYYY format.
* payee_name: Full name written after "Pay".
* amount_words: Complete handwritten amount in words.
* amount_numeric: Numeric amount from the amount box. Preserve commas and decimals exactly as written.
* is_amount_matching: Compare amount_words and amount_numeric using semantic understanding — allow minor
  OCR mistakes and spelling variations (e.g. "One Thousnd Rupees Only" vs 1000 -> true). Only return false
  when the actual monetary values differ.
* account_number: Customer account number printed on the cheque. Preserve leading zeros.
* signature_present: true if a handwritten signature exists, false if the signature area is blank.
* signature_name: Printed account holder name near the signature area, if visible; else null.
* cheque_number: The 6-digit cheque number printed at the LEFT side of the MICR band. Preserve leading zeros.
* micr_code: The 9-digit MICR code printed in the MICR band. Preserve leading zeros.

VALIDATION RULES
1. Never truncate cheque_number or micr_code.
2. Never remove leading zeros.
3. Never infer missing digits.
4. If unreadable, return null.

Return ONLY valid JSON:
{
"bank_name": "",
"date": "",
"payee_name": "",
"amount_words": "",
"amount_numeric": "",
"is_amount_matching": true,
"account_number": "",
"ifsc_code": "",
"cheque_number": "",
"micr_code": "",
"signature_present": true,
"signature_name": null
}
"""


class CloudExtractResponse(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())
    model_used: str
    bank_name: Optional[str] = None
    date: Optional[str] = None
    payee_name: Optional[str] = None
    amount_words: Optional[str] = None
    amount_numeric: Optional[str] = None
    is_amount_matching: Optional[bool] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    cheque_number: Optional[str] = None
    micr_code: Optional[str] = None
    signature_present: Optional[bool] = None
    signature_name: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None


def _clean_json_response(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


@router_v1.post("", response_model=CloudExtractResponse)
async def cloud_extract_cheque(
    file: UploadFile = File(...),
    model: str = "qwen-72b",
    ctx: UserContext = Depends(require_user_context),
) -> CloudExtractResponse:
    if model not in _MODEL_MAPPING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown model '{model}'. Must be one of {list(_MODEL_MAPPING)}.",
        )

    from shared.config.config_service import config_service
    from openai import AsyncOpenAI

    try:
        hf_token = await config_service.get_secret("demo.hf_token")
    except Exception as exc:
        log.error("demo.cloud_extract.hf_token_unavailable", bank_id=ctx.bank_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloud AI demo token not configured — set demo.hf_token in Vault.",
        ) from exc

    image_bytes = await file.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    client = AsyncOpenAI(base_url=_HF_BASE_URL, api_key=hf_token)
    model_id = _MODEL_MAPPING[model]

    try:
        response = await client.chat.completions.create(
            model=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": CLOUD_EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            temperature=0,
        )
    except Exception as exc:
        log.error("demo.cloud_extract.hf_call_failed", bank_id=ctx.bank_id, model=model, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloud AI extraction failed — Hugging Face Inference Providers unreachable.",
        ) from exc

    raw_text = response.choices[0].message.content
    cleaned = _clean_json_response(raw_text)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("demo.cloud_extract.invalid_json", bank_id=ctx.bank_id, model=model)
        return CloudExtractResponse(model_used=model, error="INVALID_JSON_RETURNED", raw_response=raw_text)

    log.info("demo.cloud_extract.completed", bank_id=ctx.bank_id, model=model)
    return CloudExtractResponse(model_used=model, **parsed)
