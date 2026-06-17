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

## Forbidden Patterns in CTS
- `SELECT *` on `cheque_instruments` or `agent_decisions` tables
- Logging `account_number`, `amount`, `payee_name` in full — mask to last 4 digits / first letter
- Any direct HTTP call to NGCH outside ngch_filer activity
- Caching AI outputs (OCR, signature scores, fraud scores) — every cheque is unique
- Skipping Immudb write after any YugabyteDB write

## File Decision Thresholds (from config_service, never hardcoded)
- `stp_auto_confirm_threshold`: default 0.92 (bank-configurable)
- `human_review_fraud_threshold`: default 0.72 (bank-configurable)
- `high_value_amount_threshold`: default ₹5,00,000 (bank-configurable)
