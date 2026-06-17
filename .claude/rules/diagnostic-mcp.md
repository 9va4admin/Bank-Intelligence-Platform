# Diagnostic MCP Server Rules (astra-diagnostic-mcp)

## Purpose
Allows ASTRA support engineers to pull operational health signals from a bank's
deployment — with explicit bank consent, time-limited access, and full audit trail.

## Fundamental Principle
The diagnostic server exposes OPERATIONAL SIGNALS only — never raw logs, never PII.
PII is stripped at the source (inside the bank's cluster) before any data is exposed.
The bank's OPA policy is the gate — it decides what the server is allowed to return.

## What CAN Be Exposed (non-PII operational signals)
```
Error signals (counts and codes — not content):
  - Error count per service per time window
  - HTTP status code distribution (4xx, 5xx counts)
  - Error code frequencies (e.g. "CTS_VAULT_MISS: 42 occurrences in last 1h")
  - Exception class names (e.g. "RedisTimeoutError: 3") — no stack trace content

Kafka signals:
  - Consumer lag per topic per consumer group
  - Message processing rate (messages/second)
  - Dead letter queue depth

Temporal signals:
  - Workflow failure count by workflow type
  - Failure reason codes (ACTIVITY_TIMEOUT, MAX_RETRIES_EXCEEDED) — not workflow content
  - IET near-breach count (how many cheques came within 30s of IET) — no instrument IDs
  - Human review queue depth and average wait time

Infrastructure signals:
  - Redis hit/miss rate per vault (CTS, EJ)
  - DB query latency percentiles (p50, p95, p99) per service
  - Pod CPU/memory utilisation per namespace
  - vLLM inference queue depth and latency per model queue
  - API response time percentiles per endpoint

AI model signals:
  - OCR confidence distribution (histogram, not per-cheque values)
  - Fraud score distribution (histogram — no scores linked to instruments)
  - Model drift indicators (7-day rolling metric change)
```

## What CANNOT Be Exposed (ever — OPA enforces this)
```
NEVER:
  - Account numbers (even hashed)
  - Cheque instrument IDs
  - Customer names
  - Transaction amounts
  - Workflow payloads or activity inputs/outputs
  - Raw log lines (contain PII in stack traces)
  - NGCH submission content
  - JWT tokens or session IDs
  - Vault key contents
  - Any data that could identify a specific cheque or customer
```

## Consent and Access Model

### Bank-Controlled Session Provisioning
```
Step 1 — ASTRA support raises support ticket with bank
  "We need diagnostic access for issue {ticket_id}. Scope: {service list}. Duration: {hours}."

Step 2 — Bank IT admin reviews and approves in Admin UI
  - Selects which services to expose
  - Sets session duration (max 4 hours)
  - Issues a time-limited diagnostic token (Vault-generated, scoped to diagnostic MCP only)
  - Token is single-use per session — cannot be reused after expiry

Step 3 — Bank provisions temporary mTLS tunnel
  - VPN/tunnel opened specifically for this session
  - ASTRA support receives the token via secure channel (not email)
  - Token scope encoded in JWT claims: {bank_id, allowed_services, expires_at, session_id}

Step 4 — ASTRA support connects via MCP client
  - Every tool call authenticated with session token
  - Every tool call logged to Immudb: DiagnosticAccessEvent{session_id, tool, params, timestamp}
  - Bank IT admin can see real-time log of what ASTRA is pulling in Admin UI

Step 5 — Session expires / bank revokes
  - Token expires automatically at duration end
  - Bank can revoke mid-session from Admin UI
  - On revoke: MCP server returns 401 on all subsequent calls
  - Revocation logged to Immudb
```

## MCP Tools Specification

### `get_error_summary`
```json
Input:  { "service": "cts-agent-worker", "window_minutes": 60 }
Output: {
  "window": "2026-06-17T10:00:00Z to 2026-06-17T11:00:00Z",
  "service": "cts-agent-worker",
  "error_counts": {
    "CTS_VAULT_MISS": 12,
    "OCR_LOW_CONFIDENCE": 3,
    "CBS_TIMEOUT": 1
  },
  "http_5xx_count": 0,
  "top_exception_classes": ["RedisTimeoutError: 2", "TemporalWorkerError: 1"]
}
# No stack traces, no instrument IDs, no account data
```

### `get_service_health`
```json
Input:  { "services": ["cts-agent-worker", "ej-normalisation-worker"] }
Output: {
  "cts-agent-worker": {
    "pod_count": 8,
    "ready_pods": 8,
    "cpu_utilisation_pct": 67,
    "memory_utilisation_pct": 54,
    "kafka_lag": { "cts.inward.{bank_id}": 0 },
    "redis_hit_rate_pct": 99.2,
    "last_successful_workflow": "2026-06-17T10:58:43Z"
  }
}
```

### `get_workflow_failures`
```json
Input:  { "workflow_type": "ChequeProcessingWorkflow", "window_minutes": 120 }
Output: {
  "total_failures": 3,
  "failure_breakdown": {
    "ACTIVITY_TIMEOUT:ocr_extract": 2,
    "MAX_RETRIES_EXCEEDED:file_to_ngch": 1
  },
  "iet_near_breach_count": 1,
  "human_review_queue_depth": 14,
  "avg_human_review_wait_minutes": 8.3
}
# Counts only — no workflow IDs, no instrument IDs
```

### `get_model_drift_signals`
```json
Input:  { "model": "got-ocr2", "window_days": 7 }
Output: {
  "model": "got-ocr2",
  "metric": "ocr_confidence_mean",
  "current_value": 0.943,
  "baseline_7d_ago": 0.961,
  "drift_pct": -1.87,
  "alert_status": "WARN",    # SAFE | WARN | CRITICAL
  "confidence_histogram": {  # distribution, not per-cheque values
    "0.95-1.0": 8432,
    "0.90-0.95": 1205,
    "0.80-0.90": 234,
    "below_0.80": 12
  }
}
```

## OPA Policy for Diagnostic Access
```rego
# infra/opa/policies/diagnostic_access.rego
package astra.diagnostic

# Default deny everything
default allow_tool = false

allow_tool if {
    # Valid session token
    valid_session(input.session_token)
    # Tool is in approved list for this session
    input.tool_name in session_scope(input.session_token).allowed_tools
    # Session not expired
    time.now_ns() < session_scope(input.session_token).expires_at_ns
}

# Bank can restrict to specific services even within a tool
allow_service if {
    input.requested_service in session_scope(input.session_token).allowed_services
}

# PII fields are always stripped regardless of session scope
pii_fields := {
    "account_number", "instrument_id", "customer_name",
    "amount", "payee", "workflow_payload"
}
```

## Immudb Audit Record (Every Tool Call)
```json
{
  "event_type": "DIAGNOSTIC_ACCESS",
  "session_id": "diag-session-{uuid}",
  "bank_id": "kotak-mah",
  "astra_support_ticket": "TICK-1234",
  "tool_called": "get_error_summary",
  "tool_params": {"service": "cts-agent-worker", "window_minutes": 60},
  "response_row_count": 1,
  "timestamp": "2026-06-17T10:32:11Z",
  "approved_by": "itadmin@kotak-mah.com",
  "session_expires_at": "2026-06-17T14:00:00Z"
}
# Bank can export this audit log at any time — full consent trail
```

## Forbidden in Diagnostic MCP Code
- Returning raw log lines from Loki/structlog — always aggregate to counts/codes
- Returning workflow IDs or instrument IDs in any response
- Accepting session tokens from environment variables — always from Vault
- Logging the diagnostic session token in any ASTRA-side log
- Keeping session alive after bank revokes (must check revocation status per call)
- Allowing ASTRA support to call tools not approved in the session scope

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| OPA validates every tool call | OPA policy `astra/diagnostic/allow_tool` called at runtime — not bypassed | Runtime (403 returned) |
| No raw log lines in responses | `security-auditor` agent: Loki query returning raw lines = CRITICAL | PR merge blocked |
| No workflow/instrument IDs in responses | `security-auditor` agent: response model containing `_id` fields = HIGH | PR merge blocked |
| Every call logged to Immudb | Code review: `log_diagnostic_access()` must appear before every `return` | PR merge blocked |
| Session token never from env vars | Semgrep: `os.environ.get` in diagnostic_mcp_server.py = ERROR | PR merge blocked |
| Bank revocation checked per call | `security-auditor` agent: missing revocation check = CRITICAL | PR merge blocked |
