# NPCI API Modernisation — ASTRA Readiness Plan

> **Trigger:** NPCI accepts the concept note in `docs/NPCI-CTS-Modernisation-ConceptNote.html`
> **Status:** Not started — waiting on NPCI response to concept note
> **Author:** Nilesh Shah | Last reviewed: June 2026

---

## What NPCI Would Ship vs. What ASTRA Must Build

```
NPCI ships (their side):                 ASTRA must build (bank side):
────────────────────────────────         ──────────────────────────────────────
POST /cts/v1/instruments         →       ngch_adapter: HTTP client replacing SFTP
POST /cts/v1/returns             →       ngch_filer activity: REST POST instead of SFTP
GET  /cts/v1/instruments/{ref}   →       Status polling client in IETWatchdogWorkflow
Webhook push to bank endpoint    →       New FastAPI webhook receiver service
NPCI mTLS cert bundle            →       HSM + cert-manager integration for NPCI mTLS
NPCI API Key + HMAC-SHA256       →       3-layer auth module in shared/ngch_auth/
MCP server (Phase 3)             →       MCP client upgrade in ngch_adapter
```

---

## PHASE A — REST API Readiness (NPCI Phase 1 acceptance → 6 months)

**Priority: CRITICAL — must be done before NPCI pilot goes live**

```
NGCH Adapter Rewrite (modules/cts/mcp/ngch_adapter.py)
  [ ] A-1  Replace SFTP submit_instrument with HTTP POST /cts/v1/instruments
           - Request: JSON body with instrument_ref, presentee_ifsc, drawee_ifsc, amount_range,
             image_hash (SHA-256), micr_line, iet_deadline_utc
           - Response: Parse instrument_ref, status, iet_deadline from NPCI response
           - Keep SFTP path alive as fallback (config flag: ngch.transport = "rest" | "sftp")
  [ ] A-2  Replace SFTP file_decision / return filing with POST /cts/v1/returns
           - ngch_filer.py activity: transport-agnostic — route on config_service.get("ngch.transport")
           - Never change the Temporal activity interface — only swap the transport underneath
  [ ] A-3  Add GET /cts/v1/instruments/{ref} status polling to IETWatchdogWorkflow
           - Poll every 30s when IET risk = ELEVATED; every 10s when HIGH; every 5s when CRITICAL
           - IET risk levels defined in concept note §6.4 — use config_service for thresholds
  [ ] A-4  Idempotency key generation: UUIDv7-based per instrument_id + bank_id
           - Store idempotency key in cheque_instruments table (new column: ngch_idempotency_key)
           - On retry: reuse same key → NPCI deduplicates (24-hour window)
  [ ] A-5  Alembic migration: add ngch_idempotency_key, ngch_transport columns to
           cts.cheque_instruments and cts.ngch_submissions

3-Layer Authentication Module (NEW: shared/ngch_auth/)
  [ ] A-6  shared/ngch_auth/__init__.py — exports NgchAuthClient
  [ ] A-7  L1: mTLS cert loading — cert from Vault (secret/astra/{bank_id}/ngch/tls/*)
           via config_service; rotate cert without restart (Vault dynamic certs)
  [ ] A-8  L2: API Key header injection (X-NPCI-API-Key from Vault) + Session Token
           exchange (POST /cts/v1/auth/session → 30-min token, cached in Redis CTS)
  [ ] A-9  L3: HMAC-SHA256 request signing — sign canonical string
           "{method}\n{path}\n{timestamp}\n{sha256(body)}" with secret from Vault
           Header: X-NPCI-Signature: {timestamp}.{hex(hmac)}
  [ ] A-10 Unit tests: 95%+ coverage (auth module is security-critical)
           Test: cert expiry graceful renewal, HMAC replay rejection, session token refresh

Rate Limit Handling (ngch_adapter)
  [ ] A-11 Parse Retry-After header on HTTP 429 responses
  [ ] A-12 Exponential backoff: respect Retry-After; cap at IET T-60s (never wait past safe window)
  [ ] A-13 Rate limit counters exposed as Prometheus metrics: ngch_rate_limit_total{bank_id,endpoint}
  [ ] A-14 Alert: PrometheusRule — if rate limit hits > 5x in 10 minutes → PagerDuty

Error Handling (ngch_filer.py + ngch_adapter.py)
  [ ] A-15 Map all NPCI error codes (AUTH_4001 → AUTH_5003, INSTR_4001 → INSTR_4010,
           SYS_5001 → SYS_5005) to internal NGCHError subclasses
  [ ] A-16 Retry semantics per error class:
           - AUTH_4001 (cert expired): renew cert → retry once
           - INSTR_4003 (duplicate): treat as success (idempotent)
           - SYS_5003 (maintenance): wait Retry-After → retry; escalate to IET watchdog if >T-60s
           - INSTR_4006 (IET expired): terminal — write audit, notify ops, never retry
  [ ] A-17 IETWatchdogWorkflow: add emergency SFTP fallback path if REST fails at T-60s
           (SFTP never decommissioned per NPCI concept note: 30-month notice required)

Observability for NPCI API
  [ ] A-18 OTel span attributes: npci.transport, npci.instrument_ref, npci.response_code,
           npci.iet_risk_level on every ngch_adapter call
  [ ] A-19 Grafana dashboard update: cts-iet-vault.json — add REST vs SFTP transport split panel,
           NPCI latency percentiles (p50/p95/p99), rate limit hit rate
  [ ] A-20 Langfuse: trace every NGCH REST call same as AI calls (latency, success/fail, bank_id)
```

---

## PHASE B — Webhook Receiver (NPCI Phase 2 → 12 months from Phase 1)

**Priority: HIGH — eliminates SFTP polling latency; IET safety improves significantly**

```
New Service: ngch-webhook-receiver (NEW FastAPI service)
  [ ] B-1  apps/api/routers/ngch_webhook.py — POST /v1/ngch/webhook/inward
           POST /v1/ngch/webhook/return-notification
           POST /v1/ngch/webhook/session-event
  [ ] B-2  Webhook authentication: verify X-NPCI-Webhook-Signature (HMAC-SHA256)
           using shared NPCI webhook secret from Vault
           Reject if timestamp in header > 5 minutes old (replay protection)
  [ ] B-3  Idempotency: check webhook_event_id against Redis SET (24h TTL) before processing
           HTTP 200 on duplicate (NPCI stops retrying); never double-process
  [ ] B-4  On inward cheque webhook: publish to cts.inward.{bank_id} Kafka topic
           (same topic SFTP polling feeds today — KEDA auto-scales, zero change downstream)
  [ ] B-5  On return notification webhook: signal HumanReviewWorkflow or update STP status
  [ ] B-6  Webhook HTTPS endpoint: Istio Ingress Gateway exposes as
           https://ngch-webhook.{bank_id}.astra.internal → bank registers with NPCI
  [ ] B-7  TLS certificate for webhook endpoint: cert-manager + internal CA
  [ ] B-8  Fallback: if webhook not received within config_service.get("ngch.webhook_timeout_s"),
           fall back to REST polling — auto-detect gap
  [ ] B-9  Helm: new Deployment + Service in astra-cts chart, separate resource limits
  [ ] B-10 Tests: webhook signature verification, duplicate suppression, Kafka publish,
           fallback trigger — 95%+ coverage

Dual-Mode Operation
  [ ] B-11 Config flag: ngch.inward_source = "webhook" | "polling" | "dual"
  [ ] B-12 Grafana panel: inward cheque source split (webhook vs polling %) per bank_id
  [ ] B-13 Target: webhook handles 95%+ of volume within 30 days of go-live
```

---

## PHASE C — MCP Intelligence Client (NPCI Phase 3 → 24 months)

**Priority: MEDIUM — competitive differentiator; ASTRA ahead of all incumbents**

```
NGCH MCP Client Upgrade
  [ ] C-1  Upgrade ngch_adapter to MCP client calling NPCI MCP server
  [ ] C-2  MCP tool bindings: submit_instrument, file_decision, query_status,
           get_settlement_report, get_iet_risk_signal, get_batch_position,
           get_counterparty_health, stream_clearing_events
  [ ] C-3  MCP resource subscriptions: inward_cheques/{bank_ifsc} (streaming),
           return_notifications/{bank_ifsc}, settlement_position/{bank_ifsc}/{date},
           iet_risk_signals/live
  [ ] C-4  ChequeProcessingWorkflow: MCP tool invocations with Temporal exactly-once wrapper
  [ ] C-5  IETWatchdogWorkflow: subscribe to iet_risk_signals/live instead of polling
  [ ] C-6  Agentic orchestration: ChequeProcessingWorkflow becomes MCP-native agent

ASTRA Diagnostic MCP exposed to NPCI (consent-gated)
  [ ] C-7  Extend astra-diagnostic-mcp with npci_liaison role (new OPA policy)
           Tools: get_iet_risk_events, get_queue_depths, get_workflow_failures — counts only
  [ ] C-8  Bank grants NPCI inspector access via same time-limited consent model
```

---

## Cross-Cutting Prerequisites

```
Documentation & Integration
  [ ] X-1  docs/npci-api-integration-guide.md — bank IT admin guide
  [ ] X-2  Helm values: ngch_transport, ngch_rest_base_url, ngch_webhook_enabled, ngch_mcp_server_url
  [ ] X-3  Bank onboarding runbook: NPCI mTLS cert provisioning steps

Testing
  [ ] X-4  Contract tests: mock NPCI REST server (FastAPI) for CI
  [ ] X-5  Performance test: NPCI REST must not increase p99 CTS latency beyond 600ms
  [ ] X-6  Chaos tests: NPCI REST down → SFTP fallback under 5s

Security (mandatory before production REST usage)
  [ ] X-7  HSM: NPCI mTLS private key in HSM partition (separate from CBS keys)
  [ ] X-8  Vault policy: ngch.* secrets accessible only by ngch_adapter service account
  [ ] X-9  Semgrep rule: any HTTP call to NPCI domain outside ngch_adapter = ERROR
  [ ] X-10 Pen test scope: include NPCI webhook endpoint and HMAC bypass attempts

Regulatory
  [ ] X-11 RBI IT Framework: map new NPCI transport to existing control IDs
  [ ] X-12 Audit trail: verify ngch_filer write_audit activity covers REST path
```

---

## Readiness Summary

| Capability | Current State | Gap |
|---|---|---|
| NGCH filing (submit) | SFTP-based ngch_filer.py | Replace transport only; keep Temporal activity |
| NGCH filing (returns) | SFTP-based | Same as above |
| IET watchdog | T-30s emergency filer | Add REST status polling at risk-level cadence |
| Auth to NPCI | SFTP key (SSH) | Build 3-layer: mTLS + API Key/HMAC module |
| Idempotency | Temporal workflow ID | Add UUIDv7 at NPCI API level |
| Error handling | SFTP error codes | Map 50 NPCI REST error codes |
| Inward receipt | SFTP poll every 15 min | Webhook receiver service (Phase B) |
| Rate limit awareness | None needed (SFTP) | Parse Retry-After, backoff, alert |
| Observability | SFTP transfer logs | OTel spans + Grafana for REST/webhook |
| MCP client | MCP server wrapping SFTP | Upgrade to MCP client (Phase C) |

**Bottom line:** ~70% of internal plumbing is ready. The gap is entirely in the NPCI-facing transport layer.
No changes needed to: AI activities, vault, Temporal workflow structure, CBS connectors, EJ module, frontend, or audit trail.

---

## Sequencing

```
Month 0-1   NPCI pilot approval received → A-1 through A-10 + X-4
Month 2     A-11 through A-20; X-7 through X-10
Month 3     X-1 through X-6, X-11/X-12 → first pilot bank with ngch.transport = "rest"
Month 4-6   Monitor; dual-mode sftp+rest
Month 7+    Phase B (webhook) begins; Phase C parallel design
```
