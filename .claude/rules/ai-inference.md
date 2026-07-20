# AI Inference Rules (Vision LLM · Reasoning LLM · OCR · Embeddings)

## Model Routing — Which Model for Which Task

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

Every AI call must: (1) open an OTel span with `bank_id`, `model`, `queue` attributes; (2) create a Langfuse trace via `langfuse.trace()` and call `generation.end()` on completion — no exceptions; (3) pass `extra_body={"queue": "<queue-name>"}` explicitly in every `vllm_client.chat.completions.create()` — never use default queue; (4) set an explicit `timeout` — never rely on SDK default.

## SHAP Requirement (Non-Negotiable)

Every AI decision influencing a cheque outcome MUST have SHAP values computed via `shap.TreeExplainer` and stored in `decision.shap_values` **before** filing to NGCH. Never file to NGCH without SHAP — audit requirement.

## Confidence Threshold Rules — All Values from config_service

Load all AI thresholds at activity start via `await config_service.get_ai_config(bank_id)`. Never hardcode any threshold value:
- `ai_config["ocr.min_confidence"]` — OCR threshold; below → `route_to_human_review()`
- `ai_config["signature.min_match_score"]` — signature threshold; below → human review
- `ai_config["ej.field_extraction.min_confidence"]` — EJ per-field threshold
- `ai_config["ej.field_extraction.max_weak_fields"]` — too many weak fields → `EJParseFailedError`

Default values in `infra/helm/values/_defaults.yaml`. Banks adjust via Admin UI (Layer 3), hot-reload < 30 seconds.

## Graceful Degradation When GPU / vLLM Is Down

On `vLLMUnavailableError` or `TimeoutError`: log warning, return `ActivityResult(outcome="HUMAN_REVIEW", reason="MODEL_UNAVAILABLE", degraded=True)`. Never silent failure. Temporal retries; IETWatchdogWorkflow files emergency if max_attempts exhausted before IET.

Fallback priority: LLM down → rule-based fallback → human review · CBS unreachable → image-only → file before IET · Vault stale → human review (NEVER auto-return on vault miss)

## Prompt Engineering Standards

**Vision prompts (Qwen2-VL, InternVL2):** Request structured JSON with per-field `{"value": ..., "altered": bool, "confidence": float}` and `"overall_tamper_risk": float`.

**Reasoning prompts (Llama 3.3 70B):** Include bank context + transaction type + risk factors already identified. Request structured JSON with confidence scores. Include: "If uncertain, set confidence below 0.70 rather than guessing." Never include raw account numbers or full customer names in prompts.

## Forbidden Patterns
- Calling vLLM without specifying `queue` in `extra_body` — always explicit
- Using a CTS queue (`cts-vision`) from EJ module code — isolation violation
- Caching any AI output — every cheque is unique, never reuse inference results
- Filing to NGCH without SHAP values stored — audit compliance violation
- Logging full prompt content if it contains account numbers or customer names
- Using cloud LLM APIs (OpenAI, Anthropic API) — data localisation violation

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Explicit queue in every vLLM call | Semgrep: vLLM call without `extra_body` queue key | PR merge (CI SAST) |
| Langfuse `generation.end()` called on every AI call | `security-auditor` agent + Langfuse CI smoke test | PR merge |
| SHAP computed before NGCH filing | `cts-workflow-reviewer` agent checklist item 6 | PR merge (CRITICAL) |
| Confidence thresholds from config_service only | Semgrep `astra-no-hardcoded-threshold` | PR merge (CI SAST) |
| AI outputs never cached | Semgrep: `redis.set()` inside ai-inference paths | PR merge |
| No AI decision without OTel span | CI integration test: span count assertion | PR merge |
