"""Hugging Face cloud vision fallback for real CTS activities (ocr.py, alteration.py,
detect_signatures.py) when the on-prem vLLM cluster (cts-vision / cts-ocr) is
genuinely unreachable.

ARCHITECTURE NOTE — read before enabling this anywhere:
CLAUDE.md section 2.1 states "All on-premises — zero cloud dependencies
(regulatory + data localisation)" and .claude/rules/ai-inference.md forbids
"Using cloud LLM APIs ... — data localisation violation". This module is a
real cloud dependency and therefore a real exception to that architecture
decision. It is OFF by default everywhere (config key
"cts.allow_cloud_ai_fallback", default False in _LAYER3_DEFAULTS) and must
stay off for any real bank deployment. It exists only so a bank's own dev/
test environment (no local GPU cluster) can still exercise full-pipeline
tests end-to-end instead of falling all the way to Tesseract/pixel-only
fallbacks. Do not remove the config gate.

Reuses the exact resolution pattern already proven working in
apps/api/routers/demo_cloud_extract.py (Vault secret first, env var
fallback for bare local dev, ovhcloud provider for qwen-72b since
featherless-ai is Cloudflare-blocked for this account).
"""
from __future__ import annotations

import base64
from typing import Optional

import structlog

log = structlog.get_logger()

_HF_BASE_URL_FALLBACK = "https://router.huggingface.co/v1"

_MODEL_MAPPING = {
    "qwen-72b": "Qwen/Qwen2.5-VL-72B-Instruct:ovhcloud",
}


async def cloud_fallback_enabled(config_service, bank_id: str) -> bool:
    try:
        return bool(await config_service.get("cts.allow_cloud_ai_fallback"))
    except Exception:
        return False


async def resolve_hf_token(config_service) -> Optional[str]:
    try:
        return await config_service.get_secret("demo.hf_token")
    except Exception as exc:
        log.warning("hf_cloud_fallback.vault_token_unavailable", error=str(exc))
    try:
        return await config_service.get("demo.hf_token")
    except Exception:
        pass
    import os
    return os.environ.get("ASTRA_DEMO_HF_TOKEN") or None


async def resolve_hf_base_url(config_service) -> str:
    try:
        return await config_service.get_secret("demo.hf_base_url")
    except Exception:
        pass
    try:
        return await config_service.get("demo.hf_base_url")
    except Exception:
        pass
    return _HF_BASE_URL_FALLBACK


async def call_hf_vision(
    config_service,
    image_bytes: bytes,
    prompt: str,
    *,
    model: str = "qwen-72b",
    timeout: float = 60.0,
) -> Optional[str]:
    """Call the HF-hosted vision model with a cheque image + prompt.

    Returns the raw text response content, or None if the token is
    unavailable or the call fails for any reason (never raises — callers
    treat None the same as any other vLLM-unavailable outcome).
    """
    token = await resolve_hf_token(config_service)
    if token is None:
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        log.warning("hf_cloud_fallback.openai_sdk_missing")
        return None

    base_url = await resolve_hf_base_url(config_service)
    model_id = _MODEL_MAPPING.get(model, _MODEL_MAPPING["qwen-72b"])
    image_b64 = base64.b64encode(image_bytes).decode()

    try:
        client = AsyncOpenAI(base_url=base_url, api_key=token, timeout=timeout)
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        log.warning("hf_cloud_fallback.call_failed", model=model_id, error=str(exc))
        return None
