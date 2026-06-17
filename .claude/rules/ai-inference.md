# AI Inference Rules (Vision LLM · Reasoning LLM · OCR · Embeddings)

## Model Routing — Which Model for Which Task
Never choose a model ad hoc. Use the correct queue for each task type:

| Task | Model | vLLM Queue | Module |
|---|---|---|---|
| Cheque image analysis (alteration, layout) | Qwen2-VL 72B | `cts-vision` | CTS only |
| MICR line OCR, handwriting extraction | GOT-OCR2.0 | `cts-ocr` | CTS only |
| Signature comparison (image-level) | Siamese Network (PyTorch) | direct HTTP, no queue | CTS only |
| Fraud synthesis + explanation | Llama 3.3 70B | `cts-reasoning` | CTS only |
| CCTV frame analysis, person detection | InternVL2-26B | `cts-vision-cctv` | CTS only |
| EJ log parsing, field extraction | Llama 3.3 70B | `ej-reasoning` | EJ only |
| Dispute semantic matching | BGE-M3 embeddings | `ej-embeddings` | EJ only |
| Dispute arbitration reasoning | Qwen2.5 72B | `ej-dispute` | EJ only |
| Fraud scoring (structured features) | XGBoost ensemble | direct call, no GPU | CTS only |

## vLLM Client Call Pattern (Mandatory)
```python
from shared.observability.langfuse_setup import langfuse
from opentelemetry import trace

tracer = trace.get_tracer("astra.ai")

async def call_vision_model(image_url: str, prompt: str, bank_id: str) -> VisionResult:
    with tracer.start_as_current_span("ai.vision.qwen2vl") as span:
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("model", "qwen2-vl-72b")
        span.set_attribute("queue", "cts-vision")

        # Langfuse trace — every AI call, no exceptions
        trace_obj = langfuse.trace(name="vision_inference", metadata={"bank_id": bank_id})
        generation = trace_obj.generation(
            name="qwen2vl_call",
            model="qwen2-vl-72b",
            input={"prompt": prompt, "image": image_url},
        )

        response = await vllm_client.chat.completions.create(
            model="qwen2-vl-72b",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt},
            ]}],
            extra_body={"queue": "cts-vision"},   # always explicit — never default
            timeout=120,
        )

        result = parse_vision_response(response)

        generation.end(output={"confidence": result.confidence})
        span.set_attribute("ai.confidence", result.confidence)

        return result
```

## SHAP Requirement (Non-Negotiable for All Decisions)
Every AI decision that influences a cheque outcome MUST have SHAP values:
```python
# After XGBoost fraud scoring:
fraud_score = xgb_model.predict_proba(features)[0][1]

# SHAP is mandatory — never skip
explainer = shap.TreeExplainer(xgb_model)
shap_values = explainer.shap_values(features)
shap_summary = {
    feature_names[i]: float(shap_values[0][i])
    for i in range(len(feature_names))
}

# Store SHAP in AgentDecision before filing to NGCH
decision.shap_values = shap_summary
# Never file to NGCH without SHAP stored — audit requirement
```

## Confidence Threshold Rules — All Values from config_service
```python
# Load all AI thresholds at activity start — never hardcode
ai_config = await config_service.get_ai_config(bank_id)

# OCR confidence
ocr_min = ai_config["ocr.min_confidence"]           # bank sets this, default in Layer 2 template
if ocr_result.confidence < ocr_min:
    return route_to_human_review("OCR_LOW_CONFIDENCE")

# Signature verification
sig_min = ai_config["signature.min_match_score"]    # bank sets this
if sig_result.match_score < sig_min:
    return route_to_human_review("SIGNATURE_LOW_CONFIDENCE")

# EJ field extraction (per-field threshold)
ej_field_min = ai_config["ej.field_extraction.min_confidence"]
for field, extraction in ej_result.fields.items():
    if extraction.confidence < ej_field_min:
        extraction.value = None
        extraction.warning = "LOW_CONFIDENCE_EXTRACTION"

# EJ record rejection threshold (how many low-confidence fields before reject)
ej_max_weak_fields = ai_config["ej.field_extraction.max_weak_fields"]
low_confidence_count = sum(
    1 for f in ej_result.fields.values() if f.confidence < ej_field_min
)
if low_confidence_count > ej_max_weak_fields:
    raise EJParseFailedError("too_many_low_confidence_fields")

# FORBIDDEN — hardcoded AI thresholds
if ocr_result.confidence < 0.90:    # WRONG
if sig_result.match_score < 0.85:   # WRONG
if low_confidence_count > 3:        # WRONG
```

Default values for these keys live in `infra/helm/values/_defaults.yaml`.
Banks adjust via Admin UI (Layer 3) — changes hot-reload in < 30 seconds, no restart.

## Graceful Degradation When GPU / vLLM Is Down
```python
# Never let model unavailability breach IET
try:
    ocr_result = await call_ocr_model(image_url, bank_id)
except (vLLMUnavailableError, TimeoutError):
    # Degrade: route to human review — never silent failure, never auto-decision
    log.warning("vllm.unavailable", queue="cts-ocr", bank_id=bank_id)
    return ActivityResult(
        outcome="HUMAN_REVIEW",
        reason="MODEL_UNAVAILABLE",
        degraded=True,
    )
    # Temporal retries this activity — if still failing after max_attempts,
    # IETWatchdogWorkflow files emergency before IET breach

# Fallback priority:
# LLM down       → rule-based fallback scorer → human review
# CBS unreachable → image-only processing → file before IET
# Vault stale    → human review (NEVER auto-return on vault miss)
```

## Prompt Engineering Standards

### Vision Prompts (Qwen2-VL, InternVL2)
```python
CHEQUE_ALTERATION_PROMPT = """
Analyse this cheque image for alterations or tampering.
Examine: amount in figures, amount in words, date, payee name, signature area.

For each field, report:
1. Value as printed
2. Any signs of alteration (overwriting, erasure, correction fluid, ink difference)
3. Confidence score (0.0 to 1.0)

Respond in JSON:
{
  "amount_figures": {"value": "...", "altered": bool, "confidence": float},
  "amount_words": {"value": "...", "altered": bool, "confidence": float},
  "date": {"value": "...", "altered": bool, "confidence": float},
  "payee": {"value": "...", "altered": bool, "confidence": float},
  "overall_tamper_risk": float
}
"""
```

### Reasoning Prompts (Llama 3.3 70B)
- Always include: bank context, transaction type, risk factors already identified
- Always request: structured JSON output with confidence scores
- Always include: "If uncertain, set confidence below 0.70 rather than guessing"
- Never include: raw account numbers, full customer names in prompt

## Forbidden Patterns
- Calling vLLM without specifying `queue` in `extra_body` — always explicit
- Using a CTS model queue (`cts-vision`) from EJ module code — isolation violation
- Caching any AI output — every cheque image is unique, never reuse inference results
- Filing to NGCH without SHAP values stored — audit compliance violation
- Logging full prompt content if it contains account numbers or customer names
- Using cloud LLM APIs (OpenAI, Anthropic API) — data localisation violation
