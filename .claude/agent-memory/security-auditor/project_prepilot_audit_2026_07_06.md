---
name: pre-pilot-audit-2026-07-06
description: Full standalone security audit of ASTRA codebase before saraswat-coop pilot deployment — 10 confirmed findings, JWT stub is pilot blocker
metadata:
  type: project
---

Full security audit conducted 2026-07-06 before first pilot bank (saraswat-coop) deployment.

**Critical blockers (must fix before pilot):**
1. JWT authentication is a test stub across ALL API routers (cts.py, ej.py, audit.py, admin.py, mcp_connections.py) — accepts `test-token-{bank_id}` pattern, rejects real SAML JWTs
2. Demo router (`apps/api/routers/demo.py`) mounted in `main.py` line 232 with no environment guard — unauthenticated endpoints exposed in production
3. `shared/utils/masking.py` does not exist — the canonical PII masking module referenced in pii-data-protection.md rules is absent
4. `ChequeProcessingWorkflow` has no `@workflow.run` decorated method — only `run_with_mocks()` (test harness); cannot register as a real Temporal workflow

**High findings (fix before GA):**
- `pps.py` lines 61, 67, 74: raw payee name + exact amount in structlog calls
- `ocr.py` lines 63 and 136/141: hardcoded threshold 0.85 as default param + raw amount_figures logged
- `signature.py` line 63: hardcoded threshold 0.80 as default param
- `fraud.py` lines 57, 62: hardcoded 0.70 and 5_000_000 in rule-based fallback scorer
- `alteration.py` line 446: hardcoded 0.5 tamper threshold in production decision logic
- `local.py` lines 44-48: timing oracle enables username enumeration (comment says "Constant-time-like" but is not)
- `ngch_adapter.py` lines 34-35: httpx.AsyncClient without mTLS cert — NGCH calls are unauthenticated at transport layer
- `modules/ej/workflows/activities/store_canonical.py` line 37: stub, no actual DB write
- `modules/ej/workflows/activities/write_audit.py` line 41: stub, no Kafka publish to platform.audit.events

**Why:** What was clean — vault miss routing (always HUMAN_REVIEW), SHAP computation, vault key hashing (HMAC-SHA256), structlog masking in cbs.py/stop_payment.py, OPA Layer 4 wiring, kill switch integration.

**How to apply:** When reviewing PRs for pilot readiness, prioritise JWT implementation (C1) and demo router gate (C2) as hard blockers. The EJ stubs mean EJ audit trail is entirely absent — cannot go to pilot if EJ module is in scope.
