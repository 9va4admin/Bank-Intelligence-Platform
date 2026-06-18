# Migration Diagnosis Flow — Guiding Principle

> **Status:** Reference architecture — implemented incrementally.
> Every component built in this platform that touches migration logging,
> diagnostic MCP resources, or the diagnosis workflow must conform to this design.
> Changes to this flow require updating this document first.

---

## Why This Exists

A failed Helm upgrade at a bank is a high-stakes event. The bank's IT team
sees a rollback. ASTRA support gets a call. Without structured diagnosis,
the root cause hunt is manual, slow, and error-prone.

This flow makes diagnosis automatic, auditable, and consent-gated —
the bank stays in control, ASTRA gets the signal it needs.

---

## The Two Environments

```
┌─────────────────────────────────────────┐   ┌──────────────────────────────────────────────┐
│         BANK'S CLUSTER (on-prem)        │   │        ASTRA INTERNAL ENVIRONMENT            │
│                                         │   │                                              │
│  Pre-upgrade Helm Hook                  │   │  MigrationDiagnosisWorkflow (Temporal)       │
│    └─ platform migration (always)       │   │    ├─ llm_diagnose       (Llama 3.3 70B)     │
│    └─ cts migration      (if enabled)   │   │    ├─ generate_report                        │
│    └─ ej migration       (if enabled)   │   │    ├─ notify_bank                            │
│                                         │   │    ├─ notify_internal_team                   │
│  Log files written to PersistentVolume  │   │    └─ write_audit        (Immudb)            │
│    /var/astra/logs/migrations/          │   │                                              │
│      {bank_id}/                         │   │  GPU: ASTRA's own inference cluster          │
│        {run_id}/                        │   │  Temporal: ASTRA's internal instance         │
│          platform.log                   │   │  Immudb: ASTRA's internal audit collection   │
│          cts.log                        │   │                                              │
│          ej.log                         │   │  Bank data NEVER persisted here —            │
│                                         │   │  log content is processed and discarded      │
│  astra-diagnostic-mcp (MCP server)      │   │  after report generation.                   │
│    Exposes logs as MCP Resources:       │   │                                              │
│    migration://logs/{bank_id}/          │   └──────────────────────────────────────────────┘
│      {run_id}/platform                  │               ▲
│      {run_id}/cts                       │               │  ASTRA support reads MCP
│      {run_id}/ej                        │               │  resources via MCP client
│                                         │               │  (consent-gated session)
│  Consent gate (OPA + Immudb):           │               │
│    Bank IT admin issues time-limited    │───────────────┘
│    diagnostic session token.            │
│    Every resource read is logged.       │
└─────────────────────────────────────────┘
```

---

## Step-by-Step Flow

### Step 1 — Migration runs, logs written to PV

The pre-upgrade Helm hook Job runs three containers sequentially.
Each container writes a structured JSONL log file to the shared PersistentVolume:

```
/var/astra/logs/migrations/{bank_id}/{run_id}/platform.log
/var/astra/logs/migrations/{bank_id}/{run_id}/cts.log       (if cts enabled)
/var/astra/logs/migrations/{bank_id}/{run_id}/ej.log        (if ej enabled)
```

**Log format — one JSON object per line (JSONL):**
```json
{"ts": "2026-06-18T10:32:11Z", "level": "INFO",  "chain": "platform", "event": "migration_start", "from_rev": "20260618_p_004", "to_rev": "20260618_p_005"}
{"ts": "2026-06-18T10:32:12Z", "level": "INFO",  "chain": "platform", "event": "applying",        "revision": "20260618_p_005", "description": "platform_model_registry"}
{"ts": "2026-06-18T10:32:13Z", "level": "INFO",  "chain": "platform", "event": "migration_ok",    "duration_ms": 1842, "applied": 1}
{"ts": "2026-06-18T10:33:01Z", "level": "ERROR", "chain": "cts",      "event": "migration_fail",  "revision": "20260618_013",   "error_class": "ProgrammingError", "error_summary": "column cts.clearing_batches.new_col already exists"}
```

**Rules for log content:**
- No account numbers, instrument IDs, customer names — ever
- Error messages truncated to first 500 chars (stack traces contain internal paths — redact before log)
- `error_summary` field: error class + message only, no stack trace
- `run_id` format: `{chart_version}-{timestamp}` e.g. `1.2.0-20260618T103200Z`

**Loki scrapes this path automatically** — structured JSONL with known labels
(`bank_id`, `chain`, `run_id`) makes log queries instant in Grafana.

---

### Step 2 — Bank grants diagnostic consent

Bank IT admin opens Admin UI → Diagnostic Sessions → New Session.

Selects:
- Scope: `migration-logs` (read-only, no service health, no queue depths)
- Resources: `migration://logs/{bank_id}/{run_id}/*`
- Duration: up to 4 hours
- ASTRA support ticket reference: `TICK-XXXX`

Vault issues a time-limited session token scoped to these resources only.
Every resource read is logged to Immudb (`DiagnosticAccessEvent`) and visible
to bank IT admin in real time via Admin UI.

See: `.claude/rules/diagnostic-mcp.md` for the full consent model.

---

### Step 3 — ASTRA support reads MCP resources

ASTRA support connects MCP client to the bank's `astra-diagnostic-mcp` server
using the session token provided by the bank.

Available resources for migration diagnosis:
```
migration://logs/{bank_id}/{run_id}/platform    → full platform.log content
migration://logs/{bank_id}/{run_id}/cts         → full cts.log content (if exists)
migration://logs/{bank_id}/{run_id}/ej          → full ej.log content (if exists)
migration://logs/{bank_id}/runs                 → list of all run_ids for this bank
```

The MCP client receives the log file content.
**The content never touches ASTRA's DB** — it is passed directly as workflow input.

---

### Step 4 — MigrationDiagnosisWorkflow (ASTRA internal Temporal)

Triggered by ASTRA support after pulling the log resources.
Runs entirely in ASTRA's own infrastructure — not in the bank's cluster.

```
MigrationDiagnosisWorkflow
  │
  ├─ Activity: parse_migration_logs(log_content: dict[chain, str])
  │    Parses JSONL, extracts: failed chain, failed revision,
  │    error_class, error_summary, last successful revision.
  │    Output: MigrationFailureSummary (structured Pydantic model)
  │
  ├─ Activity: llm_diagnose(summary: MigrationFailureSummary)
  │    Model: Llama 3.3 70B (ASTRA's internal vLLM, ej-reasoning queue)
  │    Input: structured failure summary + ASTRA migration changelog context
  │    Output: DiagnosisReport
  │      {
  │        root_cause: str,          # concise 1-2 sentence root cause
  │        likely_trigger: str,      # what in the new chart version caused this
  │        impact: str,              # what is broken, what still works
  │        recommended_action: str,  # exact steps to resolve
  │        estimated_fix_minutes: int,
  │        confidence: float,        # LLM confidence in this diagnosis
  │        requires_human_review: bool  # flag if LLM is uncertain
  │      }
  │
  ├─ Activity: generate_report(diagnosis: DiagnosisReport, summary: MigrationFailureSummary)
  │    Produces two versions:
  │      - bank_report: non-technical, action-oriented (for bank IT admin)
  │      - internal_report: full technical detail (for ASTRA support)
  │    Stores both in MinIO: reports/migration-diagnosis/{bank_id}/{run_id}/
  │
  ├─ Activity: notify_bank(bank_id, bank_report)
  │    Channel: email (bank IT admin contact from platform.banks)
  │    Template: MIGRATION_DIAGNOSIS_REPORT
  │    Content: root cause, impact, recommended action, MinIO report link
  │
  ├─ Activity: notify_internal_team(internal_report)
  │    Channel: internal (ASTRA support — email / internal tooling)
  │    Content: full technical report + bank_id + run_id + ticket reference
  │
  └─ Activity: write_audit(bank_id, run_id, session_id)
       Immudb collection: astra-internal-audit
       Event: MIGRATION_DIAGNOSIS_COMPLETE
       Fields: bank_id, run_id, diagnostic_session_id, llm_confidence,
               requires_human_review, report_minio_key
       (No log content stored — only metadata of the diagnosis event)
```

**Workflow ID:** `migration-diagnosis-{bank_id}-{run_id}` (idempotent — safe to re-trigger)

---

### Step 5 — Report delivered, audit closed

Bank IT admin receives email with:
- What failed and why (plain language)
- Exact recommended action (e.g. "Roll back to chart v1.1.0, then contact ASTRA support before retrying upgrade to v1.2.0")
- MinIO link to full report (accessible within bank's own MinIO — ASTRA copies it there)

ASTRA support receives full technical report with:
- Failed Alembic revision, error class, error message
- LLM root cause and confidence score
- Whether human review is flagged

Diagnostic session expires (or bank revokes it).
All access events remain in bank's Immudb — permanent consent audit trail.

---

## Component Ownership

| Component | Lives in | Owned by |
|---|---|---|
| Migration log files (PV) | Bank's cluster | Bank's infrastructure |
| `astra-diagnostic-mcp` MCP server | Bank's cluster | ASTRA (deployed via Helm) |
| Diagnostic consent session | Bank's Admin UI + Vault | Bank (bank controls issuance) |
| MCP client (pulls resources) | ASTRA support workstation | ASTRA support team |
| `MigrationDiagnosisWorkflow` | ASTRA internal Temporal | ASTRA engineering |
| Llama 3.3 70B inference | ASTRA internal GPU cluster | ASTRA engineering |
| Final reports (MinIO) | Both: ASTRA internal + copy in bank's MinIO | ASTRA (internal) / Bank (their copy) |
| Diagnosis audit trail (Immudb) | ASTRA internal Immudb | ASTRA engineering |

---

## Invariants (Never Violate These)

1. **Bank log content never persisted in ASTRA's DB** — processed in memory, discarded after report generation
2. **No diagnosis without consent** — diagnostic session token required; OPA enforces this at runtime
3. **Every resource read logged to bank's Immudb** — bank can audit exactly what ASTRA pulled
4. **Report sent to bank first** — bank IT admin gets the report before ASTRA's internal team notification completes
5. **Workflow is idempotent** — same `run_id` can be re-submitted without creating duplicate reports
6. **LLM never sees raw stack traces** — only `error_class` + `error_summary` (500-char truncated) from the structured log

---

## Future Extensions (Not Yet Built)

- **Auto-trigger**: migration Job emits a Kafka event on failure → ASTRA's internal system auto-triggers the workflow without needing manual support intervention (requires bank to pre-consent to auto-diagnosis sessions)
- **Pattern library**: diagnosis reports feed a curated knowledge base of known migration failure patterns → LLM diagnosis improves over time
- **Proactive alerts**: if ASTRA sees 2+ banks fail on the same revision, auto-alert engineering before more banks attempt the upgrade
