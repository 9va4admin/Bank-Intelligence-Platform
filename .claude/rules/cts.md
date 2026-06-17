# CTS Module Rules

## Critical Constraints
- IET breach rate must be 0.000% — every code path that touches a cheque decision MUST have an IET watchdog reference
- All NGCH submissions go exclusively through `modules/cts/workflows/activities/ngch_filer.py` — never direct
- Vault misses (signature or PPS) must ALWAYS route to human review, never auto-return

## Coding Patterns
- Every CTS activity function must emit an OTel span: `with tracer.start_as_current_span("activity.name")`
- Every AI call (OCR, signature, fraud) must be wrapped in a Langfuse trace
- Vault lookups use hashed keys: `sig:{bank_id}:{sha256(account_number)}`
- All Pydantic models for CTS entities live in `modules/cts/` — never import from EJ module

## Temporal Workflow Rules
- `ChequeProcessingWorkflow` is the only entry point for a cheque — no direct activity calls
- `IETWatchdogWorkflow` must be spawned as child workflow before any processing begins
- Retry policies: OCR/signature max 2 retries; NGCH filing max 3 retries with exponential backoff
- Workflow IDs: `cts-{bank_id}-{instrument_id}` — must be idempotent (exactly-once guarantee)

## The Golden Rule — No Literal Thresholds in Code, Ever
```
WRONG:  if fraud_score > 0.72
WRONG:  if amount > 500000
WRONG:  if confidence < 0.90
WRONG:  IET_MINUTES = 180

CORRECT: thresholds = await config_service.get_cts_config(bank_id)
         if fraud_score > thresholds["human_review_fraud_threshold"]
         if amount > thresholds["high_value_amount_threshold"]
         if confidence < thresholds["ocr_min_confidence"]
         if elapsed > thresholds["iet_minutes"] * 60
```
Default values live in `infra/helm/values/_defaults.yaml`.
Banks change them via Admin UI (no code, no restart, no ASTRA involvement).

## Forbidden Patterns in CTS
- `SELECT *` on `cheque_instruments` or `agent_decisions` tables
- Logging `account_number`, `amount`, `payee_name` in full — mask to last 4 digits / first letter
- Any direct HTTP call to NGCH outside ngch_filer activity
- Caching AI outputs (OCR, signature scores, fraud scores) — every cheque is unique
- Skipping Immudb write after any YugabyteDB write

## Decision Thresholds — Always from config_service, Never Hardcoded
```python
# CORRECT — every threshold is a config_service call
thresholds = await config_service.get_module_config("cts", bank_id)

stp_threshold      = thresholds["stp_auto_confirm_threshold"]
fraud_threshold    = thresholds["human_review_fraud_threshold"]
high_value_limit   = thresholds["high_value_amount_threshold"]
iet_minutes        = thresholds["iet_minutes"]
vault_miss_action  = thresholds["vault_miss_action"]  # always HUMAN_REVIEW — Layer 1 enforced

# FORBIDDEN — never write a literal threshold in code
if fraud_score > 0.72:    # WRONG — hardcoded, not bank-configurable
if amount > 500000:       # WRONG — hardcoded, not bank-configurable
```

Defaults live in `infra/helm/values/_defaults.yaml` (Layer 1) and `infra/helm/values/bank-template.yaml` (Layer 2 starting point).
Banks change Layer 3 values via Admin UI maker-checker — code never needs to change.

## IET Breach Rate
- Target: 0.000% — enforced by IETWatchdogWorkflow architecture, not by a configurable threshold
- The watchdog fires at T-30 seconds regardless of any config — this is structural, not a setting
- What IS configurable: `iet_minutes` (default 180) — the total IET window the bank operates under
