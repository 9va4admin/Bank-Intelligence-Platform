---
name: ai-agent-activity
description: Implement a new AI inference activity for ASTRA. Covers model selection, vLLM client pattern, Langfuse tracing, SHAP computation, confidence threshold handling, and graceful degradation.
---

# Skill: Implement an AI Inference Activity

## When to Use
User says: "add an AI activity", "call the vision model for {X}", "implement {model} inference", "add fraud scoring for {Y}".

---

## Step 1 — Pick the Right Model (from rules/ai-inference.md)

| What you need to do | Model | Queue |
|---|---|---|
| Read cheque image — layout, amounts, dates | Qwen2-VL 72B | `cts-vision` |
| Extract MICR line / handwriting | GOT-OCR2.0 | `cts-ocr` |
| Compare signature on cheque vs specimen | Siamese Network | direct HTTP |
| Fraud synthesis + natural language reason | Llama 3.3 70B | `cts-reasoning` |
| CCTV frame — detect person, cash dispense | InternVL2-26B | `cts-vision-cctv` |
| Parse EJ log text into canonical fields | Llama 3.3 70B | `ej-reasoning` |
| Match dispute description to EJ records | BGE-M3 | `ej-embeddings` |
| Dispute arbitration logic | Qwen2.5 72B | `ej-dispute` |
| Fraud probability score (structured features) | XGBoost | direct call, no GPU |

---

## Step 2 — Activity Skeleton with All Required Wiring

```python
# modules/cts/workflows/activities/ocr.py  (example)
from temporalio import activity
from opentelemetry import trace
import structlog
from shared.observability.langfuse_setup import langfuse
from shared.config.config_service import config_service
from apps.ai_server.client import vllm_client

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.activities")

@activity.defn
async def ocr_extract(input: OcrInput) -> OcrResult:
    with tracer.start_as_current_span("activity.ocr_extract") as span:
        # 1. Span attributes — never include raw PII
        span.set_attribute("bank_id", input.bank_id)
        span.set_attribute("instrument_id", input.instrument_id)
        span.set_attribute("model", "got-ocr2")
        span.set_attribute("queue", "cts-ocr")

        # 2. Langfuse trace — mandatory for every AI call
        lf_trace = langfuse.trace(
            name="ocr_extract",
            metadata={"bank_id": input.bank_id, "module": "cts"}
        )
        generation = lf_trace.generation(
            name="got_ocr2_inference",
            model="got-ocr2",
            input={"instrument_id": input.instrument_id},
        )

        # 3. Heartbeat for long-running activities (> 10s expected)
        activity.heartbeat("calling got-ocr2 model")

        # 4. Call vLLM — always explicit queue
        try:
            response = await vllm_client.chat.completions.create(
                model=config_service.get("ai.ocr.model"),     # from config, not hardcoded
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": input.image_presigned_url}},
                    {"type": "text", "text": OCR_EXTRACTION_PROMPT},
                ]}],
                extra_body={"queue": "cts-ocr"},              # always explicit
                timeout=config_service.get("ai.ocr.timeout_seconds", 30),
            )
        except Exception as e:
            # 5. Graceful degradation — never crash the workflow
            log.warning("ocr_extract.model_unavailable",
                        bank_id=input.bank_id,
                        error=str(e))
            generation.end(level="ERROR", status_message=str(e))
            raise  # re-raise: Temporal retries per retry_policy; watchdog catches breach

        # 6. Parse and validate response
        result = OcrResult.model_validate_json(response.choices[0].message.content)

        # 7. Confidence check — threshold always from config_service, no default literal
        ocr_min_confidence = config_service.get(f"banks.{input.bank_id}.ai.ocr.min_confidence")
        if result.confidence < ocr_min_confidence:
            log.warning("ocr_extract.low_confidence",
                        bank_id=input.bank_id,
                        confidence=result.confidence,
                        threshold=ocr_min_confidence)
            result.requires_human_review = True

        # 8. Complete Langfuse generation
        generation.end(
            output={"confidence": result.confidence, "fields_extracted": len(result.fields)},
        )
        span.set_attribute("ai.confidence", result.confidence)

        return result
```

---

## Step 3 — SHAP (Required for Fraud Scoring Activities)

```python
# modules/cts/workflows/activities/fraud.py
import shap
import xgboost as xgb

@activity.defn
async def score_fraud(input: FraudInput) -> FraudResult:
    with tracer.start_as_current_span("activity.score_fraud") as span:

        model = xgb_model_registry.get_current()
        features = build_feature_vector(input)

        # Fraud score
        fraud_probability = float(model.predict_proba(features)[0][1])

        # SHAP — mandatory, non-negotiable
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(features)
        shap_summary = {
            feature_names[i]: round(float(shap_values[0][i]), 4)
            for i in range(len(feature_names))
        }

        # Top 3 risk drivers for human reviewer
        top_drivers = sorted(shap_summary.items(), key=lambda x: abs(x[1]), reverse=True)[:3]

        span.set_attribute("fraud.score", fraud_probability)
        span.set_attribute("fraud.top_driver", top_drivers[0][0] if top_drivers else "none")

        return FraudResult(
            score=fraud_probability,
            shap_values=shap_summary,
            top_risk_drivers=top_drivers,
            model_version=model.version,
        )
        # SHAP must be stored in AgentDecision BEFORE NGCH filing — verified by cts-workflow-reviewer
```

---

## Step 4 — Prompt Template (Vision / Reasoning Models)

```python
# prompts/{domain}/{task}.py — keep prompts in separate files, not inline
OCR_EXTRACTION_PROMPT = """
Extract all fields from this cheque image.

For each field provide:
- value: the extracted text/number exactly as printed
- confidence: 0.0 to 1.0 (your certainty about the extraction)
- altered: true if you see signs of overwriting, erasure, or ink mismatch

Fields to extract:
{
  "amount_figures": ...,
  "amount_words": ...,
  "date": ...,
  "payee_name": ...,
  "drawer_account": ...,
  "micr_code": ...,
  "cheque_number": ...
}

If uncertain about any field, set confidence below 0.70 rather than guessing.
Respond ONLY in valid JSON matching the schema above.
"""
```

---

## Step 5 — Checklist Before Merging AI Activity

```
[ ] Model and queue from rules/ai-inference.md model routing table
[ ] vLLM call uses explicit queue in extra_body — never default
[ ] OTel span wraps the entire activity function
[ ] Langfuse trace.generation() called with input AND output (generation.end())
[ ] Heartbeat called for activities expected to take > 10s
[ ] try/except around model call with meaningful graceful degradation
[ ] Confidence threshold checked against config_service (not hardcoded)
[ ] SHAP computed and returned for fraud scoring activities
[ ] No raw account numbers or customer names in prompts or logs
[ ] Prompt template in separate prompts/ file (not inline string)
[ ] Activity added to worker registration in worker.py
[ ] Unit test: happy path (model returns result)
[ ] Unit test: model unavailable (verify graceful degradation, not crash)
[ ] Unit test: low confidence (verify requires_human_review=True)
[ ] Performance test: activity completes within timeout budget
```
