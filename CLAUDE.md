# ASTRA — Bank Intelligence Platform
## Claude Code Master Index & Project Constitution

> **This file is the single source of truth for Claude Code sessions.**
> Every architectural decision, tech choice, NFR, and design rationale
> is recorded here. Read this fully before writing any code.

> **Standing Session Rule:** After every task — no matter how small — commit all changed/created files and push to the active branch immediately. Every push must be complete so that a `git pull` on the developer's local machine always reflects the latest state. Never leave files uncommitted at end of task.

---

## 0. Project Identity

| Field | Value |
|---|---|
| Platform Name | **ASTRA** |
| Full Form | Automated Settlement and Transaction Recognition Architecture |
| Tagline | Precision Banking. Zero Compromise. |
| Author / Domain Expert | Nilesh Shah (Ex-NPCI · Piramal · Fullerton/SMFG) |
| Etymology | Sanskrit: precision weapon · Latin: star |
| Classification | Confidential — Banking Grade |
| Started | June 2026 |
| Repo | 9va4admin/bank-intelligence-platform |
| Branch convention | `claude/` prefix for AI-assisted development |

---

## 1. Business Context

### What This Platform Does
Two independent but unified product modules sold to Indian banks:

**Module 1 — CTS (Cheque Truncation System)**
- Reimagines India's cheque clearing infrastructure with agentic AI
- Handles **both sides** of CTS clearing for the bank:

  **Outward clearing (Presentee Bank role)**
  - Bank's customers deposit cheques drawn on other banks
  - ASTRA: physical scanner capture → MICR line extraction → CTS-2010 image compliance
    → lot/batch creation → endorsement stamping → NGCH submission
  - Session reconciliation + Return Reason File (RRF) generation at session close
  - Sub-member bank (SMB) sponsor routing: Saraswat-class UCBs route outward
    instruments for smaller UCBs through ASTRA

  **Inward clearing (Drawee Bank role)**
  - Cheques drawn on the bank arrive from NGCH
  - Solves the RBI T+3 hour IET (Item Expiry Time) mandate (Jan 2026)
  - Missed IET = deemed approval = bank pays regardless of fraud
  - One AI agent per inward cheque → decision in < 600ms
  - 500 cheques → 500 parallel agents → entire batch < 600ms wall clock

- Target buyers: Any bank participating in CTS clearing — public sector banks (SBI, PNB, BoB, Canara), private sector banks (HDFC, ICICI, Axis, Kotak, Yes, IndusInd), small finance banks, urban co-operative banks, RRBs, foreign banks with Indian operations — any institution that both submits outward cheques and receives inward instruments subject to RBI's IET mandate
- 18-month first-mover window before incumbents (Nelito, TCS BaNCS) catch up

**Module 2 — ATM EJ Intelligence**
- AI normalisation of Electronic Journal logs across all ATM OEMs
- 5+ OEMs, zero standard format — LLM solves this permanently
- Dispute resolution, fleet observability, predictive maintenance
- Same bank buyer, cross-sell after CTS foothold

### Why Single Platform (Not Two Codebases)
- Same buyer (bank IT/ops team)
- Shared infrastructure: auth, audit, HSM, CBS connectors, NPCI connectivity
- Cross-sell: CTS bank activates EJ with a config flag, zero new deployment
- RBI compliance certified once, not twice
- AI models improve with data from both modules

### Market Numbers
- CTS: ₹71 lakh crore cleared annually, 609M cheques/year (FY25)
- ATMs: 2.5L+ deployed, 5+ OEMs, zero EJ standard exists
- Revenue model: per-cheque SaaS / platform licence / managed AI

---

## 2. Architecture Decisions (All Final — Do Not Revisit Without Recording Here)

### 2.1 Deployment Model
- **Active-Active across 2 Data Centers** (both DCs serve live traffic)
- RPO = 0, RTO < 30 seconds for DC failure
- A separate air-gapped DC3 for backups (NOT serving traffic)
- All on-premises — zero cloud dependencies (regulatory + data localisation)
- Per-bank: isolated Kubernetes namespace

### 2.2 Multi-Center (Large Banks)
- Large banks have Regional Processing Centers (RPCs) per clearing zone
- Each RPC connects to its zone NGCH grid independently
- No outward consolidation needed — NPCI handles cross-zone settlement
- Consolidation needed only for: reporting, settlement position, cross-center fraud
- Central Intelligence Hub aggregates reporting across all RPCs
- Cross-center signature lookup: hub-and-spoke (local Redis → Central Hub on miss)
- PPS vault: always hub-and-spoke (PPS submitted from any channel)

### 2.3 EJ — Hybrid Edge + Central
- Edge Agent (lightweight Go binary) deployed at branch/ATM controller
- Edge does: OEM fingerprinting, compression (gzip ~70%), AES-256 encryption, buffering
- Edge does NOT do: LLM parsing (no GPU at edge)
- Central does: full LLM normalisation, cross-ATM patterns, dispute matching
- Phased rollout: Phase 1 (ATM mgmt system API) → Phase 2 (ATM controller edge agent) → Phase 3 (direct on ATM)

### 2.5 Module Blast Isolation (CTS ↔ EJ — Non-Negotiable)

**Principle:** CTS load must never degrade EJ. EJ failure must never affect CTS. No cascading impact in either direction.

This is enforced at every layer — not by convention but by hard boundaries:

#### Kubernetes
- CTS and EJ run in **separate Kubernetes namespaces**: `astra-cts-{bank_id}` and `astra-ej-{bank_id}`
- Each namespace has its own `ResourceQuota` and `LimitRange` — CTS cannot consume EJ's CPU/memory budget
- Istio `NetworkPolicy`: CTS pods cannot call EJ pods directly, and vice versa
- No shared Deployments — every service belongs to exactly one module namespace

#### Kafka
- Separate topic prefixes already: `cts.*` and `ej.*` — no cross-topic consumption ever
- Separate Kafka consumer groups per module — no shared group coordinator
- Separate KEDA `ScaledObject` per module — CTS scaling events do not trigger EJ scaling
- `cts-agent-worker` must never subscribe to any `ej.*` topic, and vice versa

#### Redis
- **Two separate Redis Clusters**: `redis-cts` (Signature Vault + PPS Vault) and `redis-ej` (EJ canonical cache, ATM health signals)
- Separate Helm release per Redis cluster — separate resource limits
- No shared Redis keyspace — CTS eviction pressure cannot evict EJ keys

#### Database (YugabyteDB)
- Separate pgbouncer pools: `pgbouncer-cts` and `pgbouncer-ej` — separate connection budgets
- CTS tables and EJ tables are in separate YugabyteDB schemas: `schema: cts` and `schema: ej`
- No cross-schema JOINs in application code — only analytics-service may read both (read-only, async)

#### AI Inference (vLLM)
- Separate inference queues per model family:
  - `queue: cts-vision` → Qwen2-VL (cheque images, signatures) — CTS exclusive
  - `queue: cts-ocr` → GOT-OCR2.0 (MICR line) — CTS exclusive
  - `queue: ej-reasoning` → Llama 3.3 70B (EJ log parsing) — EJ exclusive
  - `queue: ej-embeddings` → BGE-M3 (dispute matching) — EJ exclusive
  - `queue: shared-fraud` → XGBoost (fraud scoring) — CTS only, no GPU queue
- If CTS vision queue saturates, EJ reasoning queue is unaffected — separate vLLM workers per queue

#### Temporal
- Separate Temporal task queues: `cts-processing-{bank_id}` and `ej-normalisation-{bank_id}`
- Separate Temporal worker Deployments — CTS workers only poll CTS task queues
- Temporal namespace isolation: `temporal-ns: cts` and `temporal-ns: ej` (if multi-namespace Temporal)

#### Shared Services (allowed exceptions)
Only these services are shared — and each has a per-module rate limit:
- `audit-service` — shared, but CTS and EJ write to separate Immudb collections
- `notification-service` — shared, separate Kafka consumer groups per module
- `analytics-service` — read-only consumer, separate consumer group, no write path

#### What Sharing Means for Code
- No Python import across module boundaries: `from modules.cts import ...` forbidden in `modules/ej/` and vice versa
- Shared utilities live in `shared/` only — never in a module directory
- Pydantic models: CTS models in `modules/cts/`, EJ models in `modules/ej/` — no cross-import

### 2.6 On-Premises Deployment, Upgrade, and Configuration Model

#### Deployment Model — Per-Bank, Air-Gapped, GitOps Pull

ASTRA is not SaaS. Each bank runs a fully isolated ASTRA instance inside their own data center. There is no central control plane that reaches into a bank's environment. All delivery is pull-based.

```
ASTRA Vendor (9va4admin)          Bank's Premises
─────────────────────────         ──────────────────────────────────────
GitLab CI builds & tests          ArgoCD (bank-owned)
       │                                   │
       ▼                                   │ watches
Private OCI Helm Registry  ◄──── pulls ───┘
(versioned chart releases)
       │
       └── infra/helm/values/banks/{bank_id}/   (bank-specific config, one file per chart)
                ├── platform.yaml               always present
                ├── cts.yaml                    only if CTS purchased
                └── ej.yaml                     only if EJ purchased
```

- ASTRA team publishes **three independent versioned Helm charts** to a private OCI registry:
  - `astra-platform` — shared infra, deployed to every bank
  - `astra-cts` — CTS module, deployed only to banks that purchased CTS
  - `astra-ej` — EJ module, deployed only to banks that purchased EJ
- Each chart has its own version — a CTS fix ships without forcing EJ banks to upgrade
- ArgoCD ApplicationSets auto-discover which charts a bank uses by the presence of `cts.yaml` / `ej.yaml`
- Bank-specific values live in `infra/helm/values/banks/{bank_id}/` — changes go through PR + maker-checker
- **No ASTRA team member ever has shell/kubectl access to any bank's cluster in production**

#### Upgrade Process

```
Step 1 — ASTRA releases new version
  GitLab CI: run full test suite → tag v1.x.y → build all three Helm charts
  → publish to OCI registry as astra-platform:v1.x.y, astra-cts:v1.x.y, astra-ej:v1.x.y
  → publish release notes + upgrade guide + compatibility matrix per chart

Step 2 — Bank change management
  Bank IT Admin raises Change Request (bank's ITSM tool)
  Review: release notes, schema migration impact, config changes needed
  Approval: bank CISO + Change Advisory Board (CAB)

Step 3 — Upgrade execution (bank controls this)
  ArgoCD: change targetRevision from v1.x.y-1 to v1.x.y
  Helm pre-upgrade hook: Alembic migration Job runs first (with --dry-run reported)
  Helm upgrade: rolling update (zero-downtime for stateless services)
  Temporal workers: drain existing workflows before restart (graceful shutdown)
  Post-upgrade: smoke test suite runs automatically via Helm post-upgrade hook

Step 4 — Rollback if needed (bank controls this)
  ArgoCD: revert targetRevision to previous version
  Alembic: downgrade migration runs automatically
  SLA: rollback complete in < 10 minutes
```

#### Schema Migration Strategy
- All migrations via Alembic — never raw DDL in application code
- Migrations are **always backwards-compatible for one version** (additive only):
  - New column: nullable first, populate in app, add NOT NULL constraint in next release
  - Dropped column: mark deprecated in N, remove in N+1
  - This ensures rollback never requires a data migration
- Migration runs as a **Kubernetes Job** in a Helm pre-upgrade hook — completes before any new pods start
- Migration failures: Helm upgrade fails and rolls back automatically

#### Bank-Specific Configuration — Four Layers, Zero Code Changes

```
LAYER 1 — Platform Constraints  [in Helm chart — non-overridable by bank]
  Baked into the chart defaults. Banks cannot override these.
  Examples: min_tls_version: "1.3", audit_trail_enabled: true, data_localisation: enforced
  Change requires: ASTRA vendor release

LAYER 2 — Deployment Topology  [in infra/helm/values/banks/{bank_id}.yaml]
  Controls what gets deployed and at what scale.
  Examples: module_cts_enabled, module_ej_enabled, cbs_connector_type, max_agent_swarm_size
  Change requires: PR to ASTRA repo → bank IT Admin approval → ArgoCD sync
  Audited: Git history is the audit trail

LAYER 3 — Business Rules / Thresholds  [Admin UI → YugabyteDB → config_service hot-reload]
  Operational parameters. Changes take effect within 30 seconds, no restart needed.
  Examples: iet_minutes, stp_auto_confirm_threshold, human_review_fraud_threshold,
            high_value_amount_threshold, special_cheque_routes
  Change requires: Maker (ops_manager) submits → Checker (bank_it_admin) approves
  Audited: every change written to Immudb as ConfigChangeEvent before taking effect

LAYER 4 — Business Policy Rules  [OPA Rego policies → hot-reloaded via OPA config watcher]
  Complex conditional routing and decision logic. No code deploy needed.
  Examples: "Government cheques always to human review", "Return immediately if account frozen",
            "High-value cheques on first-clearing-day require dual approval"
  Change requires: compliance_officer authors Rego → bank_it_admin approves → OPA hot-reloads
  Audited: Rego policy versions stored in YugabyteDB with full diff history

LAYER 5 — Secrets  [HashiCorp Vault — dynamic, rotated every 24h]
  DB passwords, TLS certs, API keys for CBS/NGCH/WhatsApp.
  Change requires: Vault operator — no application restart needed (dynamic secrets)
  Audited: Vault audit log
```

#### Config Hot-Reload Architecture
```
Admin UI ──► API Gateway ──► config-service ──► YugabyteDB (writes)
                                     │
                              publishes event to
                                     │
                             Kafka: platform.config.changed
                                     │
                    ┌────────────────┴───────────────────┐
                    ▼                                     ▼
            cts-agent-worker                    ej-normalisation-worker
         (reloads thresholds                  (reloads LLM confidence
          in < 30 seconds)                     threshold in < 30 seconds)

OPA Watcher polls YugabyteDB for new Rego policy versions → hot-reloads
No pod restart required for Layer 3 or Layer 4 changes.
```

#### Multi-Bank Operations (ASTRA Vendor View)
- Each bank has a separate row in ASTRA's internal `banks` registry (not a shared DB — just ASTRA's own records)
- Each bank has its own `infra/helm/values/banks/{bank_id}.yaml` in the repo
- Version matrix tracked: which bank is on which chart version → drives support and upgrade nudges
- No bank's data ever crosses to another bank's environment — complete isolation at Helm namespace level

### 2.4 MCP as Integration Standard
- MCP (Model Context Protocol) = universal integration layer for AI agents
- **CTS + NPCI**: Standards proposal to NPCI for MCP-native NGCH interface
  - Today: NGCH Adapter wraps existing SFTP/API, exposes as MCP tools to agents
  - Future: Direct NPCI MCP server (proposal under engagement)
- **EJ + Branches**: Edge Agent IS an MCP server — exposes EJ files as resources
- **CBS**: CBS Connector as MCP server (read-only, async)
- **CCTV**: CCTV Adapter as MCP server
- MCP transport: always HTTPS with mTLS — MCP is the agent interface, not the transport

---

## 3. Technology Stack (Final — Locked)

### Core Infrastructure
| Component | Technology | Reason |
|---|---|---|
| Container Orchestration | Kubernetes (on-prem) + Helm | Bank-standard, per-bank Helm values |
| Auto-scaling | KEDA (Kafka-driven) | 0→500 pods in <2s on Kafka lag |
| Service Mesh | Istio | mTLS, zero trust, per-pod identity |
| GitOps | ArgoCD | Declarative, auditable deployments |
| CI/CD | GitLab CI (self-hosted) | No cloud CI dependency |

### Application
| Component | Technology | Reason |
|---|---|---|
| Backend API | FastAPI (Python) | Async, Pydantic v2, OpenAPI auto-gen |
| Frontend | React JS + Vite | SPA, fast, bank ops workstation |
| UI Components | TailwindCSS + Recharts | Clean, no heavy UI framework |
| State Management | React Query (TanStack) | Server state, cache, real-time |
| Workflow Engine | Temporal (self-hosted, multi-cluster) | Durable, exactly-once, IET timer |

### Data Layer
| Component | Technology | Reason |
|---|---|---|
| Operational DB | YugabyteDB YSQL | Active-active, Apache 2.0, PG-compatible |
| In-Memory / Vaults | Redis Cluster (6 nodes, 3+3 per DC) | <5ms vault lookups |
| Object Store | MinIO (WORM, ILM tiering) | On-prem S3-compatible, 3-tier lifecycle |
| Immutable Audit | Immudb | Cryptographic append-only, Merkle tree |
| Time-Series | YugabyteDB (partitioned) | Consolidate — avoid TimescaleDB separately |

### AI / ML
| Component | Technology | Reason |
|---|---|---|
| LLM Inference Server | vLLM | OpenAI-compatible API, on-prem GPU |
| Vision LLM | Qwen2-VL 72B | Best open-source vision for documents |
| CCTV Vision | InternVL2-26B | Frame analysis, person detection |
| Reasoning LLM | Llama 3.3 70B | Fraud synthesis, EJ understanding |
| Dispute Reasoning | Qwen2.5 72B | Arbitration logic |
| OCR Specialised | GOT-OCR2.0 | MICR line, handwriting extraction |
| Embeddings | BGE-M3 | EJ semantic matching, dispute search |
| Signature Verification | Siamese Neural Network (PyTorch) | Custom trained on bank's specimens |
| Fraud Scoring | XGBoost ensemble + LLM explainer | Score + natural language rationale |
| Explainability | SHAP | Feature impact per fraud decision |
| Model Registry | MLflow (on-prem) | Versioning, lineage, deployment |
| LLM Observability | Langfuse (on-prem) | Every inference logged |
| GPU minimum (pilot) | 4× RTX 4090 | Qwen2-VL 7B + Llama 3.1 8B quantised |
| GPU target (production) | 4–8× A100 80GB | Full 70B models, AWQ/GPTQ quantised |

### Messaging & Events
| Component | Technology | Reason |
|---|---|---|
| Event Bus | Apache Kafka (Strimzi on K8s) | Exactly-once, replay, fan-out |
| Cross-DC Replication | Kafka MirrorMaker 2 | Bidirectional DC1↔DC2 |

### Security
| Component | Technology | Reason |
|---|---|---|
| Secrets | HashiCorp Vault (on-prem) | Dynamic secrets, 24hr rotation |
| Certificates | cert-manager + internal CA | mTLS across all services |
| HSM | FIPS 140-2 Level 3 | NGCH PKI signing, key custody |
| Policy Engine | OPA (Open Policy Agent) | Rego policies, business rules |
| Identity | Bank's IdP via SAML 2.0 | ASTRA never stores passwords |

### Observability (Single Pane — Infra + AI + Business)
| Component | Technology | Reason |
|---|---|---|
| Instrumentation | OpenTelemetry SDK | Traces + metrics + logs, standard |
| Metrics | Prometheus | Scrapes all services |
| Dashboards | Grafana | Unified: infra + AI decisions + business |
| Logs | Loki | Grafana-native log aggregation |
| Traces | Tempo | Grafana-native trace backend |
| Distributed Traces | Jaeger (Grafana embedded) | Agent lifecycle tracing |
| Alerting | Grafana Alertmanager | Route to Notification Service |
| Chaos Testing | Chaos Mesh | Continuous resilience validation |

### Notifications
| Component | Technology | Reason |
|---|---|---|
| Email | Postal (self-hosted MTA) | No cloud email dependency |
| Email Templates | React Email | Component-driven HTML emails |
| WhatsApp | Meta WhatsApp Business API | Official, pre-approved templates |

---

## 4. Monorepo Structure

```
cerebrum/
├── CLAUDE.md                          ← THIS FILE
├── apps/
│   ├── web/                           ← React JS + Vite (frontend)
│   │   └── src/
│   │       ├── modules/
│   │       │   ├── cts/               ← CTS ops workstation
│   │       │   ├── ej/                ← EJ intelligence dashboard
│   │       │   ├── disputes/          ← Dispute resolution console
│   │       │   ├── fleet/             ← ATM fleet observability
│   │       │   └── observability/     ← Unified Grafana + AI explain
│   │       └── shared/                ← Auth, layout, design system
│   │
│   ├── api/                           ← FastAPI backend
│   │   ├── routers/
│   │   │   ├── cts.py
│   │   │   ├── ej.py
│   │   │   ├── disputes.py
│   │   │   ├── audit.py
│   │   │   ├── admin.py
│   │   │   └── notifications.py
│   │   ├── middleware/                ← Auth, RBAC, rate limit, tracing
│   │   └── dependencies/
│   │
│   └── ai_server/                     ← vLLM wrapper + model routing
│       ├── models/
│       │   ├── vision.py              ← Qwen2-VL calls
│       │   ├── reasoning.py           ← Llama calls
│       │   ├── ocr.py                 ← GOT-OCR2 calls
│       │   └── embeddings.py          ← BGE-M3 calls
│       └── explainability/
│           └── shap_service.py
│
├── modules/
│   ├── cts/                           ← CTS domain (fully isolated)
│   │   ├── workflows/                 ← Temporal workflow definitions
│   │   │   ├── cheque_workflow.py     ← Main: one cheque one agent
│   │   │   ├── human_review_workflow.py ← 55-min timeout, signal-driven
│   │   │   ├── iet_watchdog_workflow.py ← T-30s emergency filer
│   │   │   ├── vault_sync_workflow.py ← CBS → Redis vault sync
│   │   │   └── activities/
│   │   │       ├── ocr.py
│   │   │       ├── alteration.py
│   │   │       ├── signature.py
│   │   │       ├── pps.py
│   │   │       ├── cbs.py             ← balance check + account status
│   │   │       ├── stop_payment.py    ← CBS stop-payment instruction lookup
│   │   │       ├── fraud.py
│   │   │       ├── decision.py
│   │   │       ├── ngch_filer.py
│   │   │       └── write_audit.py
│   │   ├── vaults/
│   │   │   ├── signature_vault.py
│   │   │   └── pps_vault.py
│   │   ├── compliance/                ← CTS 2010 validation rules
│   │   │   ├── cts2010.py
│   │   │   ├── exporter.py
│   │   │   └── models.py
│   │   ├── endorsement/               ← Batch endorsement stamping
│   │   │   ├── batch.py
│   │   │   ├── models.py
│   │   │   └── stamper.py
│   │   ├── lot/                       ← Lot management
│   │   │   └── manager.py
│   │   ├── reconciliation/            ← Session reconciliation engine
│   │   │   ├── engine.py
│   │   │   ├── exporter.py
│   │   │   └── models.py
│   │   ├── reports/                   ← Report generation
│   │   │   ├── exporter.py
│   │   │   └── models.py
│   │   ├── rrf/                       ← Return Reason File generation
│   │   │   ├── generator.py
│   │   │   └── models.py
│   │   ├── scanner/                   ← Physical scanner adapters + MICR
│   │   │   ├── adapters.py
│   │   │   ├── micr.py
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   ├── sub_member/                ← Sub-member bank (sponsor routing)
│   │   │   ├── activities.py
│   │   │   ├── csv_generator.py
│   │   │   ├── kafka_bridge.py
│   │   │   ├── models.py
│   │   │   ├── notifications.py
│   │   │   ├── risk_shield.py
│   │   │   └── router.py
│   │   ├── worker.py                  ← Temporal worker: CTS task queues
│   │   └── mcp/
│   │       └── ngch_adapter.py        ← MCP server wrapping NGCH
│   │
│   └── ej/                            ← EJ domain (fully isolated)
│       ├── workflows/
│       │   ├── normalise_workflow.py  ← Full 8-activity pipeline: ingest→store→audit
│       │   ├── dispute_workflow.py    ← EJ match + CCTV → auto-resolve or escalate
│       │   └── activities/
│       │       ├── ingest.py
│       │       ├── fingerprint.py
│       │       ├── llm_parse.py
│       │       ├── validate.py
│       │       ├── store_canonical.py ← Persist to YugabyteDB ej schema
│       │       ├── trigger_dispute_check.py ← Publish to ej.canonical Kafka
│       │       ├── update_atm_health.py     ← Publish to ej.health.signals Kafka
│       │       ├── write_audit.py     ← Immudb audit (all terminal states)
│       │       ├── dispute_match.py   ← BGE-M3 semantic claim-to-EJ matching
│       │       └── cctv_extract.py    ← CCTV clip → MinIO (object_key only)
│       ├── worker.py                  ← Temporal worker: EJ task queues
│       ├── parser/
│       │   └── llm_parser.py
│       ├── mcp/
│       │   └── diagnostic_mcp_server.py ← Consent-gated diagnostic MCP server
│       └── cctv/
│           └── evidence_extractor.py
│
├── shared/
│   ├── audit/
│   │   ├── immudb_client.py
│   │   └── audit_event.py             ← AuditEvent schema + HSM sign
│   ├── notifications/
│   │   ├── dispatcher.py              ← Routes to correct channel
│   │   ├── email_channel.py           ← Postal SMTP
│   │   └── whatsapp_channel.py        ← Meta WA Business API
│   ├── observability/
│   │   ├── otel_setup.py
│   │   └── langfuse_setup.py
│   ├── auth/
│   │   ├── rbac.py                    ← Role definitions + ABAC
│   │   └── saml_handler.py
│   ├── config/
│   │   └── config_service.py          ← Reads from Vault + OPA
│   ├── cbs_connector/
│   │   ├── base.py                    ← Abstract CBS interface + AccountInfo/PPSEntry models
│   │   ├── finacle.py                 ← Infosys Finacle REST adapter (IMPLEMENTED)
│   │   ├── bancs.py                   ← TCS BaNCS REST adapter (IMPLEMENTED)
│   │   ├── flexcube.py                ← Oracle FlexCube SOAP/XML adapter (IMPLEMENTED)
│   │   └── exceptions.py              ← AccountNotFoundError, CBSUnavailableError
│   └── event_bus/
│       ├── producer.py
│       └── consumer.py
│
├── edge/
│   └── ej-agent/                      ← Go binary: branch MCP server
│       ├── main.go
│       ├── mcp_server.go
│       ├── file_watcher.go
│       ├── compressor.go
│       └── uploader.go
│
├── infra/
│   ├── helm/
│   │   ├── astra-platform/            ← Shared infra chart — deployed to EVERY bank
│   │   │   ├── Chart.yaml
│   │   │   ├── values.yaml            ← Layer 1 (non-overridable) + Layer 2 defaults
│   │   │   ├── templates/
│   │   │   │   ├── migration-scripts-configmap.yaml
│   │   │   │   ├── pre-upgrade-migration-job.yaml  ← platform+cts+ej Alembic chains
│   │   │   │   └── migration-rbac.yaml
│   │   │   └── hooks/
│   │   │       └── post-upgrade.yaml  ← Smoke test: Vault + mTLS + Immudb assertions
│   │   ├── astra-cts/                 ← CTS module chart — only banks with CTS purchased
│   │   │   ├── Chart.yaml             ← Independent version from astra-ej
│   │   │   ├── values.yaml            ← CTS Layer 2 defaults + Layer 3 threshold seeds
│   │   │   ├── templates/             ← CTS Deployments, KEDA ScaledObjects, Redis
│   │   │   └── hooks/
│   │   ├── astra-ej/                  ← EJ module chart — only banks with EJ purchased
│   │   │   ├── Chart.yaml             ← Independent version from astra-cts
│   │   │   ├── values.yaml            ← EJ Layer 2 defaults + Layer 3 threshold seeds
│   │   │   ├── templates/             ← EJ Deployments, KEDA ScaledObjects, Redis
│   │   │   └── hooks/
│   │   └── values/
│   │       └── banks/
│   │           └── {bank_id}/
│   │               ├── platform.yaml  ← Always present — bank identity, CBS, DC config
│   │               ├── cts.yaml       ← Present only if CTS purchased
│   │               └── ej.yaml        ← Present only if EJ purchased
│   ├── argocd/
│   │   ├── app-of-apps.yaml           ← ArgoCD App-of-Apps: one entry per bank
│   │   └── apps/
│   │       └── bank-template-app.yaml ← ArgoCD Application template per bank
│   ├── opa/
│   │   ├── policies/
│   │   │   ├── cts_routing.rego       ← Layer 4: CTS cheque routing rules
│   │   │   ├── cts_auto_return.rego   ← Layer 4: auto-return triggers
│   │   │   └── ej_dispute.rego        ← Layer 4: dispute auto-resolve rules
│   │   └── bundles/                   ← OPA bundle build output
│   ├── migrations/
│   │   ├── cts/                       ← Alembic migrations for cts schema
│   │   └── ej/                        ← Alembic migrations for ej schema
│   ├── k8s/
│   │   ├── temporal/
│   │   ├── kafka/
│   │   ├── redis/
│   │   ├── yugabyte/
│   │   ├── minio/
│   │   ├── immudb/
│   │   ├── vault/
│   │   └── monitoring/
│   └── terraform/
│       └── on-prem/
│
└── compliance/
    ├── rbi-it-framework/
    │   └── control-mapping.yaml
    └── audit-queries/
        └── standard-reports.sql
```

---

## 5. Configuration Hierarchy

Five layers. Lower layers cannot override higher layers. All changes at Layer 2+ are audited.

```
LAYER 1 — Platform Constraints  [Helm chart _defaults.yaml — non-overridable]
─────────────────────────────────────────────────────────────────────────────
  Who changes: ASTRA vendor only, via a new chart release
  How: New Helm chart version → bank upgrade process
  Hot-reload: No (requires pod restart with new chart)

  min_tls_version: "1.3"
  audit_trail_enabled: true          # cannot be turned off by any bank
  data_localisation: enforced        # no external API calls with customer data
  hsm_required: true
  exactly_once_ngch: true            # Temporal idempotency — never overridable
  iet_watchdog_enabled: true         # IET watchdog — never overridable

LAYER 2 — Deployment Topology  [infra/helm/values/banks/{bank_id}.yaml]
─────────────────────────────────────────────────────────────────────────────
  Who changes: ASTRA vendor + bank_it_admin, via PR to ASTRA repo
  How: PR review → ArgoCD sync → rolling deploy (bank's change management gates this)
  Hot-reload: No (Helm upgrade required)
  Audit trail: Git history + Immudb ConfigChangeEvent on apply

  module_cts_enabled: true
  module_ej_enabled: false
  cbs_connector_type: finacle        # finacle | bancs | flexcube
  max_agent_swarm_size: 500
  redis_cts_nodes: 6
  redis_ej_nodes: 6
  gpu_profile: pilot                 # pilot (4×RTX4090) | production (4×A100)
  clearing_zones: [MUMBAI, DELHI]
  dc_count: 2

LAYER 3 — Business Rules / Thresholds  [Admin UI → YugabyteDB → config_service]
─────────────────────────────────────────────────────────────────────────────
  Who changes: ops_manager (maker) + bank_it_admin (checker) — dual approval required
  How: Admin UI form → maker submits → checker approves → config_service publishes
       Kafka event platform.config.changed → workers reload within 30 seconds
  Hot-reload: YES — no pod restart, no deployment
  Audit trail: Every change written to Immudb as ConfigChangeEvent BEFORE taking effect

  iet_minutes: 180
  stp_auto_confirm_threshold: 0.92
  human_review_fraud_threshold: 0.72
  high_value_amount_threshold: 500000
  special_cheque_routes: [GOVERNMENT, COURT_ORDER]
  ej_pull_schedule: "*/15 * * * *"
  dispute_auto_resolve_categories: [BALANCE_SUFFICIENT, DISPENSE_CONFIRMED]
  vault_miss_action: HUMAN_REVIEW     # never changeable to AUTO_RETURN

LAYER 4 — Business Policy Rules  [OPA Rego → YugabyteDB → OPA config watcher]
─────────────────────────────────────────────────────────────────────────────
  Who changes: compliance_officer (author) + bank_it_admin (approve)
  How: Rego policy authored in Admin UI → approval → OPA watcher detects version change
       OPA hot-reloads policy bundle — no restart needed
  Hot-reload: YES — OPA live bundle reload
  Audit trail: Full Rego diff stored in YugabyteDB policy_versions table + Immudb

  Examples of what lives here:
  - "Government/court-order cheques always require human review regardless of score"
  - "If account frozen in CBS, return immediately without fraud scoring"
  - "Cheques > ₹50L on first clearing day: dual ops_reviewer approval required"
  - "EJ disputes for cash-not-dispensed: auto-resolve only if CCTV confirms no dispense"

LAYER 5 — User Preferences  [per-user YugabyteDB record]
─────────────────────────────────────────────────────────────────────────────
  Who changes: individual user, via UI settings
  Hot-reload: YES — per-request preference fetch
  No approval required, no audit trail (non-operational preferences)

  dashboard_layout, notification_preferences, locale, timezone
```

### Config-Service Architecture
`shared/config/config_service.py` is the single point of access for all configuration.
- Layer 1: read from environment variable injected by Helm at startup (immutable)
- Layer 2: read from environment variable injected by Helm at startup (immutable until redeploy)
- Layer 3: read from YugabyteDB `config` table, cached in Redis with 30-second TTL, invalidated on Kafka `platform.config.changed`
- Layer 4: OPA decision API called per request (OPA holds loaded policy bundle in memory)
- Layer 5: read from YugabyteDB `user_preferences` table per authenticated user

**No service reads from environment variables directly — always via config_service.**

---

## 6. User Roles (RBAC)

| Role | Module Access | Data Access | Config Access |
|---|---|---|---|
| ops_reviewer | CTS human queue | Own zone only | None |
| fraud_analyst | CTS + EJ analytics | Scores + SHAP, no PII | None |
| ops_manager | CTS + EJ full | Cross-zone reports | Level 3 |
| bank_it_admin | Admin console | Infrastructure only, no txn data | Level 2 (with maker-checker) |
| compliance_officer | Audit + reports | Read-only audit trail | None |
| rbi_examiner | Audit only (time-scoped) | Read-only, date-scoped | None |
| ml_engineer | AI server + MLflow | Inference logs, no customer data | None |

**ABAC rules applied on top:**
- `ops_reviewer` further scoped to `clearing_zone` attribute
- All roles scoped to `bank_id` (multi-tenancy isolation)
- `rbi_examiner` access: time-limited, scope defined per audit engagement

---

## 7. Kafka Topics

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `cts.inward.{bank_id}` | NGCH Adapter | CTS Agent Workers (KEDA) | Fan-out per inward cheque (drawee side) |
| `cts.decisions.{bank_id}` | CTS Agents | Audit Service, Analytics | All filed inward decisions |
| `cts.human.review.{bank_id}` | CTS Agents | Ops Workstation | Human review queue (inward) |
| `cts.vault.sync.{bank_id}` | CBS Connector | Vault Sync Worker | Signature/PPS updates |
| `cts.outward.scanned.{bank_id}` | Scanner Service | OutwardScanWorkflow | Newly scanned outward instruments |
| `cts.outward.lot.sealed.{bank_id}` | Lot Manager | BatchEndorsementWorkflow | Lot sealed and ready for endorsement |
| `cts.outward.submitted.{bank_id}` | NGCHSubmissionWorkflow | Audit Service, Analytics | Instruments submitted to NGCH (outward) |
| `cts.smb.inbound.{bank_id}` | SMB Forwarding Worker | SMBForwardingWorkflow | Sub-member instruments arriving for sponsor routing |
| `ej.raw.ingested.{bank_id}` | EJ Ingestion Gateway | EJ Parse Workers | Trigger normalisation |
| `ej.canonical.{bank_id}` | EJ Parse Workers | Dispute Engine, Analytics | Normalised records |
| `ej.health.signals.{bank_id}` | EJ Parse Workers | Anomaly Detector | ATM health time-series |
| `platform.audit.events` | All Services | Immudb Writer | Immutable audit stream |
| `platform.notifications` | All Services | Notification Dispatcher | All notification triggers |

---

## 8. Temporal Workflows

### CTS Workflows — Inward Clearing (Drawee Bank)
| Workflow | Trigger | Activities | Terminal States |
|---|---|---|---|
| `ChequeProcessingWorkflow` | Kafka `cts.inward` event | validate_cts2010, ocr_extract, detect_alteration, verify_signature, lookup_pps, check_cbs_balance, check_stop_payment, score_fraud, synthesise_decision, file_to_ngch, write_audit, send_notification | STP_CONFIRM, STP_RETURN, HUMAN_REVIEW |
| `HumanReviewWorkflow` | Signal from ChequeProcessingWorkflow | push_to_queue, wait_for_signal (max 55min), receive_decision, file_to_ngch, write_audit | REVIEWER_CONFIRMED, REVIEWER_RETURNED, TIMEOUT_AUTO_RETURNED |
| `VaultSyncWorkflow` | CBS event stream / schedule (6AM daily) | load_signatures_from_cbs, load_pps_from_cbs, warm_redis_vault, verify_vault_integrity | SYNC_COMPLETE |
| `IETWatchdogWorkflow` | Child of ChequeProcessingWorkflow | monitor_countdown, emergency_file_if_30s_remaining | SAFE, EMERGENCY_FILED |

### CTS Workflows — Outward Clearing (Presentee Bank)
| Workflow | Trigger | Activities | Terminal States |
|---|---|---|---|
| `OutwardScanWorkflow` | Scanner session open (ops workstation) | capture_image, extract_micr, validate_cts2010_image, create_lot_entry, write_audit | ACCEPTED, CTS_REJECTED |
| `BatchEndorsementWorkflow` | Lot sealed by ops | stamp_endorsement, update_lot_status, write_audit | ENDORSED, FAILED |
| `NGCHSubmissionWorkflow` | Lot endorsed + clearing session opens | build_ngch_file, submit_to_ngch, confirm_acknowledgement, write_audit | SUBMITTED, SUBMISSION_FAILED |
| `SessionReconciliationWorkflow` | Clearing session close | fetch_ngch_settlement_report, match_submitted_vs_settled, generate_rrf, write_audit | RECONCILED, EXCEPTIONS_FLAGGED |
| `SMBForwardingWorkflow` | Kafka `cts.smb.inbound.{bank_id}` (sub-member instrument arrives) | validate_smb_instrument, route_to_sponsor_lot, forward_to_ngch, notify_smb, write_audit | FORWARDED, RETURNED_TO_SMB |

### EJ Workflows
| Workflow | Trigger | Activities | Terminal States |
|---|---|---|---|
| `EJNormalisationWorkflow` | Kafka `ej.raw.ingested` event | fetch_raw_log, detect_oem_fingerprint, llm_parse_canonical, validate_schema, store_canonical, trigger_dispute_check, update_atm_health, write_audit | NORMALISED, PARSE_FAILED |
| `DisputeResolutionWorkflow` | Kafka `ej.canonical` event or NPCI claim | fetch_npci_claim, embed_and_match_ej, fetch_cctv_evidence, package_evidence, auto_resolve_or_escalate, send_notification, write_audit | AUTO_RESOLVED, ESCALATED_TO_HUMAN, FILED_TO_NPCI |
| `ATMHealthWorkflow` | Scheduled (every 1 hour) | analyse_health_signals, detect_anomalies, predict_failure, send_alert_if_threshold | HEALTHY, DEGRADED, CRITICAL |

### Platform Workflows
| Workflow | Trigger | Activities |
|---|---|---|
| `NotificationWorkflow` | `platform.notifications` event | route_to_channel, send_email, send_whatsapp, track_delivery, retry_on_failure |
| `AuditWriteWorkflow` | `platform.audit.events` event | sign_with_hsm, write_to_immudb, write_to_minio_worm, verify_merkle |
| `BankOnboardingWorkflow` | Admin trigger | provision_namespace, init_db_schema, warm_vaults, verify_connections, send_welcome |

---

## 9. MCP Servers in the Platform

| MCP Server | Hosts | Tools Exposed | Resources Exposed |
|---|---|---|---|
| `ngch-adapter` | Central DC (DMZ) | `submit_instrument`, `file_decision`, `query_status`, `get_settlement_report` | `inward_cheques/{bank_ifsc}`, `return_notifications/{bank_ifsc}` |
| `cbs-connector` | Central DC (internal) | `get_balance`, `get_account_status`, `get_account_metadata` | `account_events/{bank_id}` |
| `branch-ej-agent` | Branch / ATM controller (Go binary) | `fetch_ej_file`, `list_pending`, `confirm_receipt` | `ej://atm/{atm_id}/logs/{date}`, `ej://atm/{atm_id}/health` |
| `cctv-adapter` | Branch / DVR (per vendor) | `fetch_clip`, `list_cameras`, `get_timestamp_frame` | `cctv://branch/{branch_id}/cameras` |
| `astra-diagnostic-mcp` | Bank's cluster (consent-gated) | `get_error_summary`, `get_service_health`, `get_queue_depths`, `get_workflow_failures`, `get_iet_risk_events`, `get_model_drift_signals` | `diag://errors/{service}/{window}`, `diag://metrics/{service}`, `diag://workflows/failed` |

---

## 10. Storage Tiers and Lifecycle

| Tier | Hardware | What Lives Here | TTL / Retention | Technology |
|---|---|---|---|---|
| Tier 0 — Processing | NVMe SSD (in-server) | Active agent processing, Redis vaults, Temporal active state | Minutes to hours | Redis + local disk |
| Tier 1 — Operational Hot | NVMe/SSD networked | Last 90 days: cheque images, EJ canonical, active disputes, audit trail | 90 days rolling | MinIO (hot bucket) + YugabyteDB |
| Tier 2 — Warm Archive | HDD object storage | 91 days to 2 years: all artifacts | 2 years | MinIO (warm bucket) |
| Tier 3 — Cold Regulatory | LTO-9 Tape OR MinIO Glacier | 2–10 years: WORM, regulatory hold | 10 years minimum | MinIO (WORM, COMPLIANCE mode) |

**MinIO ILM Policy (automated):**
- Day 0 → Tier 1 (hot)
- Day 90 → Tier 2 (warm, auto-transition)
- Day 730 → Tier 3 (cold/WORM, auto-transition, object lock enabled)
- Year 10 → Legal review required before any delete

---

## 11. Security Principles (Non-Negotiable)

1. **Zero Trust** — every request authenticated and authorised, no implicit trust inside VPC
2. **Least Privilege** — minimum access per service and user, no wildcards
3. **No Secrets in Code/Git** — `gitleaks` pre-commit hook blocks any credential; Vault only
4. **HSM for All PKI** — FIPS 140-2 Level 3; no software-held private keys
5. **mTLS Everywhere** — Istio service mesh; every pod has a certificate
6. **Audit Always On** — cannot be disabled; tampering is cryptographically detectable
7. **Data Never Leaves Bank** — zero cloud, zero vendor access, 100% on-premises
8. **Encryption Always** — AES-256 at rest, TLS 1.3 in transit, column-level for PII
9. **No Black-Box AI** — every AI decision has SHAP + human-readable rationale
10. **Exactly-Once** — Temporal idempotency; no duplicate NGCH submissions ever

---

## 12. NFR Summary (Engineering Constitution)

### Critical SLAs
- CTS agent decision: < 600ms wall clock (p99)
- IET breach rate: **0.000%** — non-negotiable
- Vault lookup: < 5ms (Redis, p99)
- DC failover: < 30 seconds (automatic)
- RPO: 0 (active-active)

### Availability
- CTS (10AM–4PM clearing): 99.999%
- CTS (outside clearing): 99.99%
- EJ module: 99.9%

### AI Model Thresholds
- OCR accuracy: > 99.0%
- Signature verification precision: > 97.0%
- Fraud F1 score: > 0.92
- Fraud false positive rate: < 3.0%
- Fraud false negative rate: < 1.0%
- EJ field extraction: > 98.0%

### Model Drift Rules
- Alert if any metric drops > 2% over 7 days
- Auto-tighten thresholds if drops > 5%
- Pull model from production if drops > 8%

### Graceful Degradation Priority
```
LLM down        → rule-based fallback scorer → all to human review
CBS unreachable → image-only processing → file before IET
Vault stale     → route ALL to human review (never auto-return on miss)
NGCH down       → queue in Temporal → file on reconnect (IET watchdog active)
DC1 failed      → DC2 handles 100% automatically
NEVER: silent failure | NEVER: IET breach | NEVER: duplicate NGCH filing
```

### Caching Rules
- Vault data: cache-aside + write-through; event-driven invalidation
- AI outputs: NEVER cached (every cheque is unique)
- Session tokens: Redis, 15-min TTL
- Dashboard aggregates: Redis, 60-sec TTL

### Auto-scaling Rules
- CTS workers: scale up on Kafka lag > 10; minimum 2 pods always warm
- Scale up: aggressive (+50 pods/30s); Scale down: conservative (-10 pods/60s)
- LLM inference: static GPU nodes; queue backpressure governs throughput

---

## 13. Data Dictionary Index
*(Detailed schemas in `/docs/data-dictionary/` — to be created)*

### Core Entities
- `Bank` — tenant configuration and metadata
- `ProcessingCenter` — RPC per bank, zone mapping
- `ChequeInstrument` — inward cheque, all fields, lifecycle state
- `AgentDecision` — CTS agent output, fraud score, rationale, SHAP
- `SignatureVaultEntry` — per-account signature vector
- `PPSVaultEntry` — per-account positive pay record
- `HumanReviewItem` — escalated cheques with context bundle
- `NGCHSubmission` — filed decisions with NGCH acknowledgement
- `ATM` — ATM master, OEM, location, bank
- `EJRawLog` — ingested raw log file, hash, source metadata
- `EJCanonicalRecord` — normalised per-transaction EJ record
- `DisputeCase` — NPCI claim + EJ match + resolution
- `CCTVEvidence` — clip reference, timestamps, ATM linkage
- `AuditEvent` — immutable event record (Immudb)
- `NotificationRecord` — dispatched notifications, delivery status
- `User` — bank staff, role, zone scope
- `ModelVersion` — deployed model, metrics, deployment history

---

## 14. Microservices Index
*(Detailed specs in `/docs/microservices/` — to be created)*

| Service | Language | Purpose |
|---|---|---|
| `api-gateway` | FastAPI | Unified API entry point, auth, rate limit |
| `cts-agent-worker` | Python | Temporal worker: CTS cheque processing |
| `ej-ingestion-service` | Python | Receives EJ files from MCP servers |
| `ej-normalisation-worker` | Python | Temporal worker: LLM normalisation |
| `dispute-engine` | Python | Temporal worker: dispute matching + resolution |
| `vault-sync-service` | Python | CBS → Redis vault synchronisation |
| `ngch-adapter` | Python | MCP server wrapping NGCH SFTP/API |
| `cbs-connector` | Python | MCP server per CBS type (pluggable) |
| `ai-inference-server` | Python | vLLM wrapper, model routing |
| `fraud-scoring-service` | Python | XGBoost + SHAP, called by CTS agents |
| `signature-verification-service` | Python | Siamese network inference |
| `audit-service` | Python | Immudb writer, event signing |
| `notification-service` | Python | Postal + WhatsApp dispatcher |
| `config-service` | Python | Reads Vault + OPA, serves config |
| `user-service` | Python | SAML, RBAC, session management |
| `analytics-service` | Python | Aggregations for dashboards |
| `branch-ej-agent` | **Go** | Edge MCP server at branch (lightweight) |

---

## 15. Development Rules for Claude Code

### Before Writing Any Code
1. Check this CLAUDE.md for existing decisions
2. Check the relevant microservice spec in `/docs/microservices/`
3. Check the data dictionary for entity schemas
4. Never re-architect — follow what is here; propose changes if needed

### Code Standards
- Python: FastAPI, Pydantic v2 models for all schemas, async throughout
- Go (edge agent only): standard library preferred, minimal deps
- React: functional components, React Query for all server state
- No `print()` in Python — structured logging via `structlog` always
- No hardcoded values — all config from `config_service`
- Every function that touches a cheque or EJ record: must emit OTel span
- Every AI call: must be wrapped in Langfuse trace
- Every write to YugabyteDB: must be followed by Immudb audit write

### Testing Requirements
- Unit tests: pytest for Python, go test for Go
- Coverage: > 80% overall, > 95% for agent workflow activities
- Contract tests: every MCP server interface
- Performance tests: CTS agent must complete in < 600ms under test harness
- No mock for: Immudb writes, NGCH submissions (use dedicated test environment)

### Git Conventions
- Branch: `claude/` prefix for AI-assisted work
- Commits: conventional commits (`feat:`, `fix:`, `test:`, `infra:`)
- No secrets in any commit — gitleaks enforced
- PR required for any change to: workflows, vaults, NGCH adapter, audit service

### Forbidden Patterns
- `SELECT *` on any table with PII
- Logging account numbers, amounts, customer names in full
- Any HTTP call without mTLS in production code
- Any credential outside of Vault
- Any AI decision without SHAP computation
- Any NGCH submission outside the `ngch_filer` activity

---

## 16. Build Status & Next Steps

### Completed (as of June 2026)

```
PHASE 1 — Foundation
  [x] Monorepo scaffold
  [x] Shared: auth, RBAC (roles + ABAC), config_service (5-layer hierarchy)
  [x] Shared: audit_event schema + Immudb client (HSM signing)
  [x] Shared: notification dispatcher (Postal email + Meta WhatsApp)
  [x] Shared: event_bus producer + consumer (Kafka, exactly-once)
  [x] Shared: OTel setup (traces + metrics + logs)
  [x] Infra: Helm chart skeleton + bank values template
  [x] CBS Connectors: Finacle (REST), BaNCS (REST), FlexCube (SOAP/XML) — all 3 COMPLETE

PHASE 2 — CTS Core
  [x] Vault: signature_vault + pps_vault (Redis, hashed keys, vault-miss → HUMAN_REVIEW)
  [x] MCP: ngch_adapter (SFTP wrapper, exposes 4 MCP tools)
  [x] Temporal: ChequeProcessingWorkflow + 10 activities (OCR, alteration, signature, PPS,
       CBS balance, CBS stop-payment, fraud, decision, ngch_filer, write_audit)
  [x] Temporal: IETWatchdogWorkflow (T-30s emergency filer, ABANDON parent-close policy)
  [x] Temporal: HumanReviewWorkflow (55-min timeout, signal-driven)
  [x] Temporal: VaultSyncWorkflow (CBS → Redis, 6AM daily)
  [x] API: CTS router — /v1/cts/* endpoints (submit, decision, human-review queue)
  [x] Frontend: CTS ops workstation — human review queue with live polling (useReviewQueue hook)
  [x] CTS modules: compliance/CTS2010, endorsement/batch, scanner/MICR, rrf, reconciliation,
       lot, reports, sub_member (sponsor-bank routing + risk shield)
  [x] CTS Drawee gaps closed (July 2026):
       stop_payment.py activity (Bloom pre-check → CBS confirm → HUMAN_REVIEW/STP_RETURN)
       Amount figures vs words cross-check in ocr.py (Indian parser + mismatch → HUMAN_REVIEW)
       OPA Layer 4 wired into decision.py (government/court-order/policy gate)
  [x] Temporal Presentee Workflows (July 2026):
       OutwardScanWorkflow — scanner → MICR → CTS-2010 → lot assignment → audit
       BatchEndorsementWorkflow — lot seal → stamp all instruments → audit
       NGCHSubmissionWorkflow — build NGCH file → submit → ACK confirm → audit
       SessionReconciliationWorkflow — NGCH settlement → match → RRF generation → audit
  [x] Test coverage: ~1910 tests passing, 95%+ on all CTS workflow activities

PHASE 3 — Observability
  [x] OTel setup in shared/observability/otel_setup.py
  [x] Langfuse setup stub in shared/observability/
  [x] Grafana dashboards ConfigMap — cts-iet-vault.json, cts-fraud-ai.json, ej-normalisation.json
  [x] PrometheusRule CRD — CTSIETBreach, CTSFraudF1Drop, EJATMCriticalHealth, platform alerts
  [x] SHAP panel in ops workstation — ShapExplainer.jsx renders in ReviewPanel "AI Analysis" tab

PHASE 4 — EJ Module (COMPLETE)
  [x] Temporal: EJNormalisationWorkflow — full 8-activity pipeline:
       ingest → fingerprint → llm_parse → validate →
       store_canonical → trigger_dispute_check → update_atm_health → write_audit
  [x] Temporal: DisputeResolutionWorkflow — EJ match + CCTV → auto-resolve or escalate
  [x] Temporal: ATMHealthWorkflow — hourly scheduled, 3-state health machine (HEALTHY/DEGRADED/CRITICAL)
  [x] EJ activities: all 10 registered (8 normalisation + dispute_match + cctv_extract)
  [x] EJ: LLM parser (Llama 3.3 70B prompt structure)
  [x] EJ: CCTV evidence extractor (MinIO object_key pattern)
  [x] EJ: Diagnostic MCP server (consent-gated, OPA-controlled, Immudb audit)
  [x] EJ: worker.py (Temporal worker with all workflows + activities registered)
  [x] Edge: branch-ej-agent Go binary (OEM fingerprint, gzip+AES-256-GCM, SQLite WAL buffer,
       MCP server — tools: list_pending, fetch_ej_file, confirm_receipt;
       resources: ej://atm/{id}/logs/{date}, ej://atm/{id}/health) — 11 Go tests, all pass
  [x] EJ ingestion gateway (FastAPI /v1/ej-ingest/raw-log → Kafka ej.raw.ingested.{bank_id},
       idempotent workflow IDs, test-mode mock Kafka) — 12 tests
  [x] Frontend: EJ Command Center, Incidents, Dispute Console (/ej/disputes),
       ATM Fleet Map (/ej/fleet), Manager Portal, BRE Policy, Notifications
       — EJShell nav updated, all routes wired in App.jsx

PHASE 5 — Hardening
  [ ] Active-active DR drills
  [ ] Chaos Mesh scenarios
  [ ] RBI compliance mapping verification
  [ ] Performance test: 500 cheques in < 600ms
  [ ] Security: penetration test prep
  [ ] Bank onboarding: first pilot bank Helm deploy
```

PHASE 9 — Pre-Pilot Security Remediation (July 2026, IN PROGRESS)
  Context: White-box pentest (2026-07-11) found 3 CRITICAL blockers before any bank pilot.
    Findings ASTRA-01/02/03 tracked as: ASTRA-01 = forgeable test-token auth backdoor on
    every API router; ASTRA-02 = ChequeProcessingWorkflow never actually filed to NGCH or
    wrote audit trail on its real Temporal entry point (only the mocked test harness did);
    ASTRA-03 = an unawaited async config_service.get("env") call made a prod/dev env-gate
    always evaluate true. Full findings in the original pentest report artifact.

  [x] ASTRA-01 — CLOSED for 9/10 routers (commit b726e29, branch claude/auth-local-login-mfa):
       cts, msv, admin, users, audit, disputes, batch, notifications, mcp_connections all now
       delegate to apps.api.dependencies.require_user_context (httpOnly session cookie via
       AuthenticationMiddleware) instead of parsing a forgeable test-token-* Bearer header.
       AuthenticationMiddleware + a Vault-backed SessionTokenService wired into main.py,
       fail-closed on Vault failure. Each router has a regression-guard test proving the old
       backdoor header no longer grants access. ej.py has the identical backdoor — left open,
       deliberately deferred to a separate session per explicit instruction (EJ module is
       out of scope unless explicitly requested).
  [x] ASTRA-02 — CLOSED (commit c145e5c, same branch): ChequeProcessingWorkflow.run(),
       IETWatchdogWorkflow, and HumanReviewWorkflow all now have working Temporal wiring —
       every decision reached is filed to NGCH and written to Immudb on every exit path.
       HumanReviewWorkflow needed adding from scratch (@workflow.defn/@workflow.run/
       @workflow.signal — it had none, despite apps/api/routers/cts.py already sending it a
       live signal). IETWatchdogWorkflow no longer hardcodes CONFIRM on emergency-fire — it
       uses decision_ready()/filing_complete() signals from the parent (or HumanReviewWorkflow)
       so a T-30s emergency-fire during a slow filing uses the real decision, falling back to
       CONFIRM only when no decision was ever reached at all. Also fixed, discovered as a
       blocking prerequisite: synthesise_decision's execute_activity() call passed 3 positional
       args (only 1 is accepted without args=[...]) — would have crashed every cheque reaching
       the happy path in real production, independent of ASTRA-02. Kill-switch dual-checkpoint +
       OPA Layer 4 gate were also completely dark on the real path (kill_switch_status always
       None) — new modules/cts/workflows/activities/kill_switch_lookup.py activity closes this,
       called independently at both checkpoints. First real-Temporal-environment test coverage
       in the project (temporalio.testing.WorkflowEnvironment) — every prior CTS workflow test
       exercised only the parallel run_with_mocks() harness, never the real @workflow.run.
       Message taxonomy aligned: write_audit.py's event types now match the pre-existing,
       richer shared/messages/locales/messages.yaml keys (CTS_NGCH_FILED_CONFIRM/RETURN,
       CTS_WF_HUMAN_CONFIRMED/RETURNED, CTS_WF_REVIEW_TIMEOUT, CTS_WF_IET_WATCHDOG_FIRED,
       new CTS_WF_HUMAN_REVIEW_QUEUED) instead of a separate, unregistered ad-hoc set —
       CTS_WF_IET_WATCHDOG_FIRED already carries CRITICAL severity + NOTIFICATION surface,
       so the platform's single highest-stakes audit event now has WhatsApp/email routing
       with no new routing code needed.
  [ ] ASTRA-03 — the cts.py/msv.py instances are moot (the vulnerable code path was deleted
       entirely as part of the ASTRA-01 fix, not patched in place). The main.py demo-router-gate
       instance of the same unawaited-coroutine bug is still present; confirmed fail-safe
       (demo router never registers, in any env) — low priority, not yet fixed.
  [ ] Deferred by explicit decision, not yet started: ej.py's ASTRA-01 backdoor;
       HumanReviewWorkflow's 55-minute timeout is a flat constant decoupled from the actual
       per-instrument iet_deadline (needs a config-aware redesign); SMB notify/ledger side
       effects exist in run_with_mocks() but are never called from the real run() (same
       "mock diverges from real entry point" shape as ASTRA-02 itself, found a second time).
  [ ] Still open, not investigated this phase: local.py's DB hooks to the real
       platform.local_auth_accounts table (currently in-memory only); RBAC fail-closed
       defaults (rbac.py:210-211); 8 of 22 registered CTS activities and 3 of 8 registered
       CTS workflows still lack @activity.defn/@workflow.defn (worker.py Worker() construction
       fails today independent of the above — confirmed by direct attribute inspection, not
       guessed); no temporalio.contrib.pydantic converter in the installed temporalio version,
       so every Pydantic-typed activity/workflow boundary in the entire codebase deserializes
       as a plain dict in real Temporal execution, not the typed model; every activity's real
       dependency (ngch_adapter, immudb_client, cbs_connector, etc.) is a `=None` default with
       zero injection wired at worker registration.

PHASE 10 — Error → Incident Management (July 2026, Phase 1+2 of 5 COMPLETE)
  Context: "How are we going to manage errors caught by catch blocks — turn them into
    incidents, what severity/SLA, how is closure managed?" Full design written up first
    (Artifact: ASTRA — Error → Incident Management Plan), then built. Core driver, stated
    directly: ASTRA must know about an incident before the end user reports it. 5-phase
    rollout planned; this session shipped Phase 1 (schema + validation) and Phase 2
    (signal emission for CRITICAL/safety-boundary keys) for real, not just designed.

  [x] messages.yaml schema extended: new optional `incident:` block per key
       (incident_class, default_severity P0-P4, escalation_trigger IMMEDIATE|THRESHOLD,
       threshold{count,window_seconds}, owning_team, regulatory_reportable,
       auto_close_eligible, runbook_ref) — shared/messages/registry.py IncidentMetadata
       dataclass, survives the Redis round-trip, deliberately excluded from the browser
       JSON bundle (ops-only concern, not the frontend's business).
  [x] registry.validate() extended: incident: block now MANDATORY on every CRITICAL key
       (30/30 real keys classified — see below), optional-but-must-be-well-formed on
       WARN/ERROR (Phase 4 will widen this). Hard-coded NEVER-condition allowlist
       (CTS_WF_IET_WATCHDOG_FIRED, PLATFORM_AUDIT_WRITE_FAILED,
       PLATFORM_AUDIT_TAMPER_DETECTED) structurally forced to escalation_trigger=
       IMMEDIATE + regulatory_reportable=true — cannot be misconfigured by hand.
  [x] shared/incidents/signal.py — emit_incident_signal(key, bank_id) — the one new call
       site the plan adds to existing catch blocks. No-ops for keys with no incident:
       block (fire-and-forget, can never break the caller's real workflow). Wired into
       modules/cts/workflows/activities/write_audit.py — the single choke-point nearly
       every CTS decision/error already flows through, so this is the highest-leverage
       integration point without touching dozens of call sites. Also signals
       PLATFORM_AUDIT_WRITE_FAILED when write_audit's own Immudb write fails — a P0
       safety-boundary signal in its own right.
  [x] shared/observability/otel_setup.py extended with a MeterProvider (mirrors the
       existing TracerProvider setup exactly) — get_meter() alongside get_tracer().
       In-memory reader by default (dev/test); prometheus_port param lazily imports the
       OTel Prometheus exporter (same lazy-import pattern as the OTLP trace exporter —
       package not installed by default, never a hard dependency).
  [x] shared/messages/build_alerts.py (NEW) — generates
       infra/k8s/monitoring/generated-incident-alerts.yaml, a real PrometheusRule CRD
       mechanically derived from every key's incident: block (30 rules from the 30
       CRITICAL keys today). Grouped by owning_team. Never hand-edited — same
       "generated, do not edit" contract as CTS_Msg_Taxonomy.html, wired into
       `python -m shared.messages.build`'s pipeline right alongside it.
  [x] docs/CTS_Msg_Taxonomy.html generator extended with an Incident Response column
       (severity pill + owning team) per key — "—" for the ~250 keys not yet classified
       (honest, not fabricated).
  [x] All 30 real CRITICAL-severity keys in messages.yaml hand-classified — spans 6
       owning_team queues (cts_clearing_ops 18, bank_infra 6, cts_ai_platform 2, ej_ops 2,
       compliance_review 2). Per-cheque terminal decisions that are individually correct
       (account frozen/closed, stop-payment hit) deliberately set to THRESHOLD not
       IMMEDIATE — the individual event is expected behaviour, only a volume spike is the
       real signal (CBS data issue, policy misconfig, or a coordinated fraud pattern).
  [x] Found + fixed a real, pre-existing UTF-8 encoding bug while building this:
       shared/messages/registry.py and build_docs.py (both read AND write paths) were
       calling .read_text()/.write_text() without explicit encoding="utf-8" — on this
       machine's cp1252 default locale, every em-dash and ₹ symbol in messages.yaml
       (used throughout real message text) was silently corrupted on load. Affects the
       real runtime registry, not just doc-generation tooling — fixed all instances,
       added a regression test.
  [x] 113 new/updated tests, all GREEN — full existing suite re-run (3301 passed), zero
       regressions; incidentally fixed one pre-existing flaky test in test_otel_setup.py
       (asserted against the global OTel provider singleton, which only accepts the first
       configure_otel() call per process — order-dependent across the full suite, now
       checks its own return value instead, matching every sibling test in that file).

  Deliberately NOT built this session (Phase 3/5 of the plan — needs real infra or
  real operational data this dev environment doesn't have):
  [ ] Phase 3 — Alertmanager → Grafana OnCall wiring, escalation-chain Layer 3 config UI
       (no live Alertmanager/OnCall in this dev environment to wire against for real)
  [ ] Phase 4 — widen incident: coverage from CRITICAL-only to all WARN/ERROR keys
       (~150 keys) once Phase 3's pilot data informs real threshold tuning
  [ ] Phase 5 — maker-checker closure enforcement, compliance_officer RBI-reportability
       review workflow, control-mapping.yaml extension

PHASE 11 — Audit/Notification Producer-Consumer Gap Closure (July 2026, COMPLETE)
  Context: Live audit of the platform.audit.events and platform.notifications Kafka
    topics (triggered by a direct question — "so many places we have producer but
    consumer is not written?") found the claim was true, but split into two very
    different categories: most "unconsumed" topics (cts.inward, ej.raw.ingested,
    cts.human.review, ej.health.signals, cts.decisions) turned out to have safe,
    working direct fallbacks already (Temporal start_workflow called inline, or
    Temporal visibility queries, or direct Redis writes) — the Kafka publish was
    always a KEDA-lag-metric / theoretical-analytics side channel, not the real
    mechanism. Two subsystems had no fallback at all: MCP connection audit events
    and MCP connection notifications, both fire-and-forget into Kafka topics with
    zero consumers anywhere in the codebase, on the explicit documented assumption
    that an "audit-service" would exist. It never did — only the producer side of
    shared/audit/stream_buffer.py's Redis Streams design existed either (fully
    built and unit-tested, but never called from any real code path on either end).

  [x] Found and fixed a second, independent bug while investigating: the real
       ImmudbClient (shared/audit/immudb_client.py) only exposes a sync
       write_event(payload_dict) with collection fixed at connect-time, but
       modules/cts/workflows/activities/write_audit.py — CTS's own, previously
       assumed-safe direct-write audit path — calls an async .write(collection=,
       event_type=, bank_id=, instrument_id=, payload=). Every existing test
       mocked this away with an AsyncMock; the real class was never exercised.
       The first real Temporal execution to reach Immudb would have crashed with
       AttributeError. Fixed with shared/audit/immudb_writer.py's AsyncImmudbWriter
       (asyncio.to_thread() adapter, matching shared/storage/minio_client.py's
       established pattern; set_collection()+write_event() run inside the SAME
       to_thread() call so concurrent writes to different collections on one
       ImmudbClient instance can't interleave). worker_activities._build_immudb_client
       now returns the wrapped adapter — zero changes needed to write_audit.py itself,
       since its existing (correct) call shape was always the target contract.
  [x] shared/audit/stream_consumer.py (NEW) — AuditStreamConsumer, the "audit-service
       consumer" stream_buffer.py's own docstring names but never implements. Modelled
       on shared/config/cache_invalidator.py's CacheInvalidator (start/stop lifecycle,
       background asyncio task, per-message handler kept separately testable from the
       poll loop). Per-message failure isolation: one bad message (malformed JSON,
       Immudb write failure) is left un-acked and redelivered next poll; the rest of
       the batch still writes and acks. HSM is optional — writes UNSIGNED with a loud
       warning when unavailable (HSM itself is a separate, already-tracked, not-yet-
       built decision — Vault Transit vs PKCS11) rather than skipping the write
       entirely, which is what modules/cts/workflows/activities/decision.py's existing
       hsm-is-None handling does. Deliberately different: skipping every write until
       HSM lands would mean this consumer never populates the audit trail in the
       meantime, reproducing the exact "wired but does nothing" problem it exists to
       fix. 13 tests GREEN.
  [x] apps/audit_service/main.py (NEW) — runnable worker entrypoint, one per bank
       (matches the per-bank K8s namespace isolation model). FastAPI app with only
       /health/live + /health/ready (microservices.md's mandatory K8s-probe surface)
       — no business-logic endpoints, the consumer runs as a lifespan background task.
       Graceful degradation throughout: missing Redis or Immudb → consumer simply
       doesn't start, readiness reports degraded, liveness still passes. 6 tests GREEN.
  [x] apps/api/routers/mcp_connections.py: _emit_audit() now calls BOTH the existing
       Kafka publish (kept — it's the documented durable-backup path, not removed) AND
       a new buffer_audit_event() call via a new get_audit_stream_writer dependency
       (same DI shape as the existing get_event_publisher/get_preflight_writer — real
       Redis-backed writer when app.state.redis_cts exists, log-only stub otherwise).
       This is the change that actually closes the loop: MCP_CONN_CREATED/UPDATED/
       DELETED/TESTED_OK/TESTED_FAIL/SYNC_TRIGGERED events now reach Immudb via
       AuditStreamConsumer, not just Kafka topics nobody reads.
  [x] Notification gap: investigated whether the same fix pattern applied to
       platform.notifications and found a bigger, genuinely separate problem —
       NotificationRoutingTable.get_spec() (shared/notifications/routing.py) is real,
       tested, and correctly says MCP_CONN_DELETED/TESTED_FAIL should notify — but
       build_requests() needs a `users` list resolving role → real recipients, and
       no user directory exists anywhere in this codebase for any feature, not just
       this one. Did not fabricate a fake recipient (would silently claim delivery
       that never happens, which is worse than the honest gap). Added
       _route_notification() — evaluates the real routing spec, logs the
       unresolved-recipient boundary explicitly (roles that SHOULD be notified,
       priority, reason) — wired into both NOTIFICATION-surface call sites
       (MCP_CONN_DELETED, MCP_CONN_TESTED_FAIL). The existing platform.notifications
       Kafka publish is unchanged. User directory / recipient resolution is a new,
       distinct, not-yet-scoped gap, flagged but not started.
  [x] 30 new/updated tests across the MCP router, all GREEN (71 total in that file).
       Full suite re-run: 3340 passed, same 7 pre-existing unrelated failures as
       before this session, zero new regressions.

### Immediate Next
Pre-pilot security remediation (Phase 9) is in progress — see above for exact status.
Error → Incident Management (Phase 10) Phase 1+2 shipped this session — see above.
Audit/Notification Producer-Consumer Gap Closure (Phase 11) shipped this session.

Remaining work (in priority order):
1. **ASTRA-01 on ej.py** — same test-token backdoor fix pattern already proven on 9 other
   routers, deliberately deferred rather than expanded into EJ module scope without being asked.
2. **Activity/workflow decorator + DI gaps (Phase 9's "still open" list)** — worker.py cannot
   construct a real Worker() today; this blocks ANY of modules/cts/workflows/ from running
   against a real Temporal server, independent of the ASTRA-01/02 fixes already landed.
3. **Incident Management Phase 3** — stand up Grafana OnCall (self-hosted), wire Alertmanager
   routing by owning_team, build the Layer 3 escalation-chain config UI. Needs real infra.
4. **User directory / notification recipient resolution** — Phase 11 found this is a real,
   platform-wide gap (not MCP-specific): no code anywhere resolves "role X at bank Y" to an
   actual email/phone/user_id. Needed before NotificationRoutingTable's business rules can
   ever actually deliver anything, for any feature.
5. **NPCI API Modernisation Phase A** — REST transport + 3-layer auth module (`shared/ngch_auth/`)
   Trigger: NPCI responds to concept note. Code can be built now (§17 has full task list).
6. **Pilot bank deployment validation** — smoke-test `infra/helm/values/banks/saraswat-coop/`
   against a real Kubernetes cluster; verify pre-upgrade migration job and ArgoCD ApplicationSet.
7. **Security hardening audit** — full penetration test prep; verify SQL injection, PII at rest,
   data theft protections are production-grade (OWASP ZAP + manual review).

---

## 17. NPCI API Modernisation — ASTRA Readiness Plan

> **Trigger:** NPCI accepts the concept note submitted in `docs/NPCI-CTS-Modernisation-ConceptNote.html`
> **Question answered here:** If NPCI approves the three-phase evolution (SFTP → JSON REST API →
> Webhook Push → MCP Intelligence Layer), what must ASTRA build or change to be the first bank-side
> vendor ready on Day 1 of each phase?
>
> Author: Nilesh Shah | Last reviewed: June 2026

---

### Context: What NPCI Would Ship vs. What ASTRA Must Build

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

### PHASE A — REST API Readiness (NPCI Phase 1 acceptance → 6 months)

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

### PHASE B — Webhook Receiver (NPCI Phase 2 → 12 months from Phase 1)

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
  [ ] B-7  TLS certificate for webhook endpoint: cert-manager + internal CA, bank provisions
           NPCI-trusted cert via bank's existing PKI (documented in onboarding runbook)
  [ ] B-8  Fallback: if webhook not received within config_service.get("ngch.webhook_timeout_s"),
           fall back to REST polling GET /cts/v1/instruments — auto-detect gap
  [ ] B-9  Helm: new Deployment + Service in astra-cts chart for ngch-webhook-receiver
           with separate resource limits (never share CPU with cts-agent-worker)
  [ ] B-10 Tests: webhook signature verification, duplicate suppression, Kafka publish,
           fallback trigger — 95%+ coverage

Dual-Mode Operation (webhook + polling simultaneously during migration)
  [ ] B-11 Config flag: ngch.inward_source = "webhook" | "polling" | "dual"
           "dual" mode: both active; dedup at Kafka topic level (idempotency key in event envelope)
  [ ] B-12 Grafana panel: inward cheque source split (webhook vs polling %) per bank_id
  [ ] B-13 Target: webhook handles 95%+ of volume within 30 days of go-live
```

---

### PHASE C — MCP Intelligence Client (NPCI Phase 3 → 24 months)

**Priority: MEDIUM — competitive differentiator; ASTRA ahead of all incumbents**

```
NGCH MCP Client Upgrade (modules/cts/mcp/ngch_adapter.py)
  [ ] C-1  Upgrade ngch_adapter from "MCP server wrapping SFTP" to "MCP client calling NPCI MCP server"
  [ ] C-2  MCP tool bindings: submit_instrument, file_decision, query_status,
           get_settlement_report, get_iet_risk_signal, get_batch_position,
           get_counterparty_health, stream_clearing_events
  [ ] C-3  MCP resource subscriptions: inward_cheques/{bank_ifsc} (streaming),
           return_notifications/{bank_ifsc}, settlement_position/{bank_ifsc}/{date},
           iet_risk_signals/live
  [ ] C-4  ChequeProcessingWorkflow: replace activity calls with MCP tool invocations
           where applicable — maintain Temporal exactly-once wrapper around each MCP call
  [ ] C-5  IETWatchdogWorkflow: subscribe to iet_risk_signals/live MCP resource stream
           instead of polling; act on NPCI push signal before T-30s
  [ ] C-6  Agentic orchestration: ChequeProcessingWorkflow becomes an MCP-native agent
           with NPCI as its primary tool server — multi-tool per cheque in single pass

ASTRA Diagnostic MCP exposed to NPCI (consent-gated)
  [ ] C-7  Extend astra-diagnostic-mcp with npci_liaison role (new OPA policy)
           Allowed tools: get_iet_risk_events, get_queue_depths, get_workflow_failures
           — no PII, no instrument IDs, counts only
  [ ] C-8  Bank grants NPCI inspector access via same consent model as ASTRA support
           (time-limited, Immudb-audited, OPA-controlled)
```

---

### CROSS-CUTTING — Readiness Prerequisites (Before Any Phase)

```
Documentation & Integration
  [ ] X-1  docs/npci-api-integration-guide.md — bank IT admin guide for NPCI REST onboarding
           (cert provisioning, API key request process, webhook endpoint registration)
  [ ] X-2  Helm values: new Layer 2 keys for NPCI transport config
           ngch_transport: sftp             # → rest → webhook → mcp
           ngch_rest_base_url: ""           # populated when REST pilot approved
           ngch_webhook_enabled: false      # → true when webhook goes live
           ngch_mcp_server_url: ""          # populated at Phase 3
  [ ] X-3  Bank onboarding runbook update: add NPCI mTLS cert provisioning steps
           (infra/helm/values/banks/{bank_id}/platform.yaml: ngch_cert_ref field)

Testing
  [ ] X-4  Contract tests: mock NPCI REST server (FastAPI) for CI — matches NPCI OpenAPI spec
           Tests cover: auth flow, idempotency, all 50 error codes, rate limit headers
  [ ] X-5  Performance test: NPCI REST transport must not increase p99 CTS latency beyond 600ms
  [ ] X-6  Chaos tests: NPCI REST down → SFTP fallback under 5s; webhook gap → polling kicks in

Security (mandatory before production REST usage)
  [ ] X-7  HSM: NPCI mTLS private key stored in HSM partition (separate from CBS keys)
  [ ] X-8  Vault policy: ngch.* secrets accessible only by ngch_adapter service account
  [ ] X-9  Semgrep rule: any HTTP call to NPCI domain outside ngch_adapter = ERROR
  [ ] X-10 Pen test scope: include NPCI webhook endpoint and HMAC verification bypass attempts

Regulatory
  [ ] X-11 RBI IT Framework: map new NPCI REST/webhook transport to existing control IDs
           (compliance/rbi-it-framework/control-mapping.yaml)
  [ ] X-12 Audit trail: every NPCI API call logged to Immudb with NPCI response code
           (already covered by ngch_filer write_audit activity — verify it covers REST path)
```

---

### Readiness Summary — What Is Already Done vs. What Needs Building

| Capability | Current State | Gap to NPCI REST (Phase A) |
|---|---|---|
| NGCH filing (instrument submit) | SFTP-based ngch_filer.py | Replace transport; keep Temporal activity |
| NGCH filing (returns) | SFTP-based | Same as above |
| IET watchdog | T-30s emergency filer | Add REST status polling + risk-level polling cadence |
| Authentication to NPCI | SFTP key (SSH) | Build 3-layer: mTLS + API Key/HMAC module |
| Idempotency | Temporal workflow ID | Add UUIDv7 idempotency key at NPCI API level |
| Error handling | SFTP error codes | Map full NPCI REST error taxonomy (50 codes) |
| Inward cheque receipt | SFTP poll every 15 min | Webhook receiver service (Phase B) |
| Rate limit awareness | None needed (SFTP) | Parse Retry-After, backoff, alert |
| Observability (NPCI layer) | SFTP transfer logs | OTel spans + Grafana panel for REST/webhook |
| MCP client to NPCI | MCP server wrapping SFTP | Upgrade to MCP client (Phase C) |

**Bottom line:** ~70% of ASTRA's internal plumbing is ready. The gap is entirely in the NPCI-facing transport layer (ngch_adapter + auth module + webhook receiver). No changes needed to: AI activities, vault, Temporal workflow structure, CBS connectors, EJ module, frontend, or audit trail.

---

### Sequencing for First Pilot Bank

```
Month 0-1   NPCI pilot approval received
            → Start A-1 through A-10 (adapter rewrite + auth module)
            → Start X-4 (mock NPCI server for CI)

Month 2     A-11 through A-17 (error handling + rate limits)
            A-18 through A-20 (observability)
            X-7 through X-10 (security prereqs)

Month 3     X-1 through X-3 (docs + Helm values + onboarding runbook)
            X-11 through X-12 (regulatory)
            X-5 through X-6 (performance + chaos tests)
            → First pilot bank Helm deploy with ngch.transport = "rest"

Month 4-6   Monitor pilot; dual-mode sftp+rest
            → If stable: flip ngch.transport = "rest" for all pilot banks

Month 7+    Phase B (webhook receiver) development begins
            Phase C (MCP) — parallel design track
```

---

*NPCI Readiness Plan last updated: June 2026*
*Trigger for next review: NPCI responds to concept note submission*

---

*Last updated: June 2026 | Maintained by Claude Code session*
*All architectural decisions final unless explicitly revised in this file*

---

## 18. Gemini Technical Evaluation — Architecture Hardening (July 2026)

> **Source:** Google Gemini 1.5 Pro evaluation of full ASTRA codebase (1.21 MB, 97 files)
> **Verdict:** "Generation 3 clearing platform" — 5 gaps identified, all resolved below.
> **Date:** July 2026

### Evaluation Scores (Gemini)
| Layer | Score | Status |
|---|---|---|
| Workflow Engine | 10/10 | Elite — IET Watchdog is a masterstroke |
| Kafka Design | 8/10 | Strong — good multi-tenant SMB isolation |
| Vault Strategy | 8/10 | Strong — vectors offload CBS significantly |
| Data Integrity | 7/10 | Solid — partitioned FK needs app-level logic |
| AI Integration | 6/10 | At Risk — 72B models threaten 600ms SLA |
| HA/DR | 4/10 | Critical — no PR-DR strategy for air-gapped sites |

---

### 18.1 Fix A — Cascaded AI Model (L1 Guard → L2 Escalation)

**Problem:** Qwen2-VL 72B for 500 parallel agents causes VRAM queuing → 600ms SLA breach.

**Decision (Final):**
- **L1 Guard:** Qwen2-VL 7B (or quantised 7B) — handles ~90% of cheques in < 100ms
  - vLLM queue: `cts-vision-l1` (separate worker, lighter GPU)
  - If L1 confidence ≥ `ai.cascade.l1_confidence_threshold` AND amount < `ai.cascade.high_value_threshold` → use L1 result, skip L2
- **L2 Full:** Qwen2-VL 72B — escalate when:
  - L1 confidence < `ai.cascade.l1_confidence_threshold` (default: 0.85)
  - OR cheque amount ≥ `ai.cascade.high_value_threshold` (default: ₹50,00,000)
  - OR OPA policy overrides (government cheques, court orders always L2)
  - vLLM queue: `cts-vision-l2` (dedicated A100 GPU nodes)
- **Same pattern for OCR:** GOT-OCR2.0 7B as L1, GOT-OCR2.0 full as L2
- **Result:** ~90% of cheques clear in < 100ms (L1); ~10% use L2 within budget

**Config keys (Layer 3 — hot-reload, per bank):**
```
ai.cascade.l1_confidence_threshold    default: 0.85
ai.cascade.high_value_threshold       default: 5000000  (₹50L)
ai.cascade.l2_escalation_enabled      default: true
ai.cascade.l1_model_vision            default: "qwen2-vl-7b"
ai.cascade.l2_model_vision            default: "qwen2-vl-72b"
ai.cascade.l1_model_ocr               default: "got-ocr2-7b"
ai.cascade.l2_model_ocr               default: "got-ocr2-full"
```

**New vLLM queues:**
- `cts-vision-l1` — Qwen2-VL 7B, RTX 4090 or quantised A100
- `cts-vision-l2` — Qwen2-VL 72B, dedicated A100 80GB
- `cts-ocr-l1` — GOT-OCR2.0 7B
- `cts-ocr-l2` — GOT-OCR2.0 full

**Implementation:** `shared/ai/model_cascade.py` — `CascadeOrchestrator` class
- `call_vision_cascade(image_url, amount, bank_id, context)` → always returns `CascadeResult` with `model_used`, `cascade_level`, `confidence`
- Used by `alteration.py` and `ocr.py` activities

---

### 18.2 Fix B — 15-Minute Delta Vault Sync + Canceled Leaf Bloom Filter

**Problem:** Daily 6AM sync means stop-payment instructions filed mid-day are missed → fraud risk window of up to 18 hours.

**Decision (Final):**

**Tiered Sync Strategy:**
- **Full Sync (6AM daily):** Signatures (heavy — unchanged; full reload acceptable once/day)
- **Delta Sync (every 15 minutes):** Stop-payment instructions + canceled cheque leaf serials only
  - Triggered by: `VaultDeltaSyncWorkflow` on KEDA schedule OR CBS push event
  - Kafka topic: `cts.vault.delta.{bank_id}` (high-priority, separate consumer group)
  - Workflow ID: `cts-vault-delta-{bank_id}-{yyyymmddhhmm}`

**Canceled Leaf Bloom Filter:**
- Redis key: `bloom:canceled:{bank_id}` — probabilistic filter for canceled serial numbers
- Before ANY vLLM call: check MICR serial against Bloom filter
- Bloom hit → route to HUMAN_REVIEW immediately (skip GPU entirely → saves ~500ms)
- Bloom false positive rate: < 0.1% (acceptable — results in unnecessary human review, never auto-confirm)
- Updated by DeltaSyncWorkflow every 15 minutes
- Redis data type: Bloom filter via RedisBloom module OR manual bitarray in CTS Redis cluster

**New Temporal workflow:** `modules/cts/workflows/delta_vault_sync_workflow.py`
- `DeltaVaultSyncWorkflow` — activities: `fetch_delta_stop_payments`, `fetch_delta_canceled_leaves`, `update_bloom_filter`, `write_audit`
- Schedule: every 15 minutes via Temporal schedule (not cron — deterministic, exactly-once)
- Worker: existing `cts-agent-worker` (same task queue, low priority)

**Config keys (Layer 3):**
```
vault.delta_sync_interval_minutes     default: 15
vault.bloom_false_positive_rate       default: 0.001
vault.bloom_expected_items            default: 100000  (per bank)
vault.delta_sync_enabled              default: true
```

---

### 18.3 Fix C — HA/DR Blueprint (Primary-DR for Air-Gapped Sites)

**Problem:** No explicit PR-DR strategy — DC2 is present but synchronisation mechanism was not specified, leaving "Exactly-Once" at risk during DC1 failure.

**Decision (Final):**

**YugabyteDB (RF=3):**
- Replication Factor = 3 across 3 availability zones (or 3 physical racks in single DC)
- `min_replica_count: 2` for writes (quorum write) — no data loss on single-node failure
- Active-Active reads: any node can serve reads; leader for writes is zone-local
- Helm value: `yugabyte.replicationFactor: 3` (was previously unspecified)

**Kafka (min.insync.replicas=2):**
- All CTS topics: `replication.factor=3`, `min.insync.replicas=2`
- Producer config: `acks=all` (already the case for exactly-once) + `min.insync.replicas=2`
- A cheque is not acknowledged as "received" until written to ≥ 2 independent Kafka brokers
- Helm value: `kafka.minInsyncReplicas: 2` in `astra-platform/values.yaml`

**Temporal Dual-Cluster (Warm DR):**
- DC1 = Primary Temporal cluster (serves all workflows during normal operation)
- DC2 = Warm Temporal replica (receives replicated history from DC1 via Temporal's cross-cluster replication)
- On DC1 failure: ArgoCD flips workers to poll DC2 task queues — in-flight workflows resume from last checkpoint
- RTO for Temporal: < 30 seconds (matches platform RTO SLA)
- Config: `temporal.primaryCluster: dc1` + `temporal.drCluster: dc2` in platform values

**Redis (active-passive for vaults):**
- DC1: `redis-cts` primary (active writes + reads)
- DC2: `redis-cts-replica` (passive — follows DC1 via Redis replication)
- On DC1 failure: config-service switches `redis.cts.url` to DC2 replica within 30s
- Vault data is expendable for up to 1 sync cycle — VaultSyncWorkflow re-warms on DC2 after failover

**Helm values updated:**
- `astra-platform/values.yaml` → `ha.yugabyte.rf: 3`, `ha.kafka.min_insync: 2`
- `astra-platform/values.yaml` → `ha.temporal.dr_cluster_enabled: false` (enable per bank at Layer 2)

---

### 18.4 Fix D — Software-Defined Foreign Key Integrity (EJ + Reconciliation)

**Problem:** YugabyteDB partitioned tables cannot enforce FK constraints across partitions → orphaned canonical records possible → reconciliation nightmare for RBI auditors.

**Decision (Final):**

**EJ Integrity Activity (new — 9th step in EJNormalisationWorkflow):**
- After `store_canonical`, before `trigger_dispute_check`: run `verify_canonical_integrity`
- Checks: canonical record exists in DB, `log_id` → `canonical_record` link valid, `canonical_hash` matches stored value
- On failure: write `EJ_INTEGRITY_FAIL` AuditEvent to Immudb → halt workflow → alert bank_it_admin
- Never silently proceed past a failed integrity check

**Reconciliation Orphan Scanner (in SessionReconciliationWorkflow):**
- New activity: `scan_orphaned_records` — daily pass over EJ canonical records with no parent raw log
- Alerts via `platform.notifications` Kafka topic → ops_manager + bank_it_admin
- Never auto-deletes — only alerts (deletion requires compliance_officer sign-off)

**New AuditEventType:** `EJ_INTEGRITY_FAIL` (CRITICAL, surface: [UI, AUDIT, NOTIFICATION])

---

### 18.5 Fix E — Notification Debouncer (Batch & Burst Anti-Spam)

**Problem:** 500 parallel failing agents could generate 500+ WhatsApp messages to an SMB manager in seconds → notification flood → manager ignores all alerts.

**Decision (Final):**

**Batch & Burst Pattern:**
- Window: 60 seconds per `(bank_id, smb_id, event_category)` triple
- Threshold: if ≥ `notification.debounce.threshold` (default: 10) notifications arrive in the window → suppress individual alerts
- On threshold breach: emit one **Batch Summary Alert** with:
  - Count of suppressed events
  - Severity of the most critical event in the batch
  - Dashboard deep-link for the SMB
  - `event_category` (e.g. "VAULT_MISS", "IET_RISK", "FRAUD_SCORE")
- After summary sent: reset window (start fresh 60-second window)
- P0 events (IET breach, kill switch) are NEVER debounced — always immediate

**Implementation:** `shared/notifications/debouncer.py` — `NotificationDebouncer` class
- Backend: Redis (CTS Redis cluster) — sorted set per window key, TTL = 60 seconds
- Integrated into `shared/notifications/dispatcher.py` before channel dispatch
- Config keys (Layer 3, hot-reload):
```
notification.debounce.enabled           default: true
notification.debounce.threshold         default: 10
notification.debounce.window_seconds    default: 60
notification.debounce.exempt_priorities  default: ["P0"]   # never debounced
```

---

### 18.6 Updated Kafka Topics (Fixes A + B)

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `cts.vault.delta.{bank_id}` | Delta Sync Trigger / CBS push | DeltaVaultSyncWorkflow | Stop-payment + canceled leaf delta events |
| `cts.vision.cascade.{bank_id}` | Cascade Orchestrator | L2 vLLM workers | L2 escalation requests from L1-uncertain results |

---

### 18.7 Updated AI Inference Queues (Fix A)

| Queue | Model | Purpose | Module |
|---|---|---|---|
| `cts-vision-l1` | Qwen2-VL 7B | Alteration detection — fast path | CTS only |
| `cts-vision-l2` | Qwen2-VL 72B | Alteration detection — forensic (escalated) | CTS only |
| `cts-ocr-l1` | GOT-OCR2.0 7B | MICR + handwriting — fast path | CTS only |
| `cts-ocr-l2` | GOT-OCR2.0 full | MICR + handwriting — forensic | CTS only |

---

### 18.8 Updated Build Status (Phase 5 — Hardening Additions from Gemini)

```
PHASE 5 — Hardening (in progress, July 2026)
  [x] Fix A: AI cascade (L1/L2) — shared/ai/model_cascade.py (CascadeOrchestrator, L1/L2 routing,
       high-value threshold, l2_disabled escape hatch) + wired into alteration.py (cheque_amount →
       cascade, cascade_level in result) + ocr.py (call_ocr cascade, cascade_level in result)
       — 13 new tests (alteration wiring: 7, OCR wiring: 6), 83 total in these three files
  [x] Fix B: Delta vault sync (15-min) + Bloom filter — DeltaVaultSyncWorkflow added to
       delta_vault_sync_workflow.py (fetch_delta_stop_payments, fetch_delta_canceled_leaves,
       update_bloom_filter activities + DeltaVaultSyncWorkflow orchestrator). CBS degradation
       tracked inline; audit always fires; Bloom skipped on empty delta. 5 new workflow tests
       + 12 activity tests = 17 total GREEN.
  [x] Fix C: HA/DR Helm values — infra/helm/astra-platform/values.yaml ha section:
       yugabyte RF=3 + min_replica_count=2, kafka replication_factor=3 + min_insync=2,
       temporal dr_cluster_enabled (default false, per-bank Layer 2 opt-in),
       redis vault_replication_mode active-passive + 30s failover timeout.
  [x] Fix D: EJ integrity activity — modules/ej/workflows/activities/verify_canonical_integrity.py
       (9th step in EJNormalisationWorkflow, EJ_INTEGRITY_FAIL AuditEvent on mismatch);
       reconciliation orphan scanner in SessionReconciliationWorkflow.
  [x] Fix E: Notification debouncer — shared/notifications/debouncer.py
       (NotificationDebouncer, Redis sorted-set window, P0 bypass, batch summary,
       wired into dispatcher.py)
  [x] RBI IT Framework control mapping — compliance/rbi-it-framework/control-mapping.yaml
       27 controls, all COMPLIANT (was 26 COMPLIANT + 1 PLANNED before Chaos Mesh)
  [x] Chaos Mesh scenario YAMLs — infra/chaos-mesh/ (4 scenarios, 10 manifests):
       01-dc1-failure, 02-redis-cts-node-failure, 03-vllm-gpu-failure, 04-kafka-broker-failure
       Quarterly DR drill schedule Q3 2026 (01+02) → Q4 2026 (03+04)
  [x] First pilot bank Helm values — infra/helm/values/banks/saraswat-coop/
       platform.yaml (CBS=Finacle, MUMBAI zone, SMB sponsor enabled) + cts.yaml
  [x] End-to-End Live Demo Pipeline (July 2026, rewritten to pure frontend July 2026):
       Fully self-contained — no API calls, no backend, no server required.
       Runs on GitHub Pages as-is. Backend code in modules/cts/demo/ kept for future prod.
       apps/web/src/modules/cts/pages/CTSDemoPipeline.jsx (pure JS/React simulation):
         — createSemaphore(5): browser Semaphore, max 5 cheques concurrently
         — presentmentFailure(idx): AMOUNT_MISMATCH/ALTERATION_DETECTED/CTS_IMAGE_QUALITY
         — draweeFailure(idx): STOP_PAYMENT_ACTIVE/SIGNATURE_MISMATCH/ACCOUNT_FROZEN
         — micrData(idx) + extractionData(idx): deterministic OCR outputs per file index
         — CSV generation: toCSV() + URL.createObjectURL() — no server download needed
         — 5-phase PhaseBar, StageChip grid with pulse animations, UploadZone (real or sample)
         — NPCIView (4 drawee bank routing cards), CompleteView (all 4 CSV download buttons)
         — left: item queue; center: stage chips + processing table; right: live event feed
         Route: /cts/demo; Sidebar: "⚡ Live Demo" in Drawee Process section
       37 tests (modules/cts/demo/ Python backend): 26 sync GREEN, 11 async GREEN

  [x] MCP Connection Config API + UI (July 2026):
       apps/api/routers/mcp_connections.py — 8 routes (preflight, CRUD, test, sync)
         SB_CBS / SMB_CBS / SIGNATURE_VAULT / PPS_VAULT / CANCELLED_LEAF connection types
         Pre-flight gate: clearing_allowed=True only when ALL connections ACTIVE
         endpoint_url masked in every response (never raw), SB/SMB scoping enforced
         Kafka: platform.config.changed on every status change (workers reload <30s)
         Kafka: platform.notifications on TESTED_FAIL + DELETED (surface=[NOTIFICATION])
         Kafka: cts.vault.delta.{bank_id} on trigger_sync → fires DeltaVaultSyncWorkflow
         workflow_id: cts-vault-delta-{bank_id}-{yyyymmddhhmm} (temporal.md convention)
         Redis preflight_writer: refreshes preflight:{bank_id} after every status change
         Audit: AuditEvent for all 6 MCP events (MCP_CONN_CREATED/UPDATED/DELETED/etc.)
         PRODUCTION WIRED (July 2026): YugabyteDBConnectionStore (asyncpg, pgbouncer-cts),
           real Kafka publisher via app.state.kafka_producer_cts (Request injection),
           real Redis preflight writer via app.state.redis_cts (5-min TTL),
           _emit_audit publishes to platform.audit.events when publisher injected,
           main.py lifespan: asyncpg pool db_pool_cts (min=2, max=10 per pod)
           All store methods async — in-memory fallback for dev/tests
       infra/migrations/cts/20260701_add_mcp_connection_configs.py — Alembic migration
       apps/web/src/modules/cts/pages/CTSMCPConfig.jsx — React config screen
       shared/audit/audit_event.py — 6 new AuditEventType variants
       shared/messages/locales/messages.yaml — 6 new message keys (247 total)
       60 tests, all GREEN (zero warnings)

PHASE 6 — Multi-Scenario CTS Presentment (July 2026, COMPLETE)
  Context: Three deployment scenarios documented in docs/astra-multi-scenario-cts-plan.html
    Scenario 1: SB+SMB, SMB has own CBS → SMB CBS push via Agency SFTP (CSV every 15 min)
    Scenario 2: Agency+SMB, Agency manages CBS → Agency CC microservice, no push needed
    Scenario 3: Agency+SMB, SMB has own CBS → push + Agency CC relay
    Architecture decisions: ProcessingUnit (PU) as first-class entity; branch→PU is admin mapping
    (not geographic); Vision LLM LAST for presentment, FIRST for drawee; OCR removed (scanner handles).
    Drop-folder model: scanner OEM software writes to configured path, ASTRA file-watcher picks up.
    SMB CBS proxy: originally planned as Go binary at SMB premises — CHANGED to push model.
      SMB's existing CBS batch job pushes CSV to Agency SFTP every 15 min. Zero new software at SMB.

  [x] Phase 1 — Foundation (commit 0f0443f):
      docs/astra-multi-scenario-cts-plan.html — full gap analysis + 8-phase plan
      modules/cts/scanner/mapper.py — ScannerDropFolderMapper, ScannerConfig, ScannedChequeInput
        ScannerOEM: DIGITAL_CHECK, MAGTEK, RDM, OPEX added — 30 tests GREEN
      Alembic migrations (all 9): processing_units, branches, sb_connections, clearing_sessions,
        mismatch_queue, eeh_sessions, scanner_configs, cheque_instruments pu columns,
        ngch_submissions pu columns
      modules/cts/crl/service.py — CRLService (IFSC/MICR → BranchResolution, Redis cache) — 22 tests GREEN

  [x] Phase 2 — EEH/IEH + Branch Portal UI (commits f8c15df → c950597):
      EEH Session Manager, SSE publisher, FastAPI health/session endpoints
      EEH gRPC servicer + proto definition
      Branch Portal UI: BranchDashboard, BranchScanMonitor, BranchMismatchQueue, BranchSessionHistory
      EEH/IEH Helm chart — astra-cts v0.2.0 with Vault sidecar, anti-affinity, mTLS STRICT

  [x] Phase 3 — Presentment Fix: Vision LAST + Mismatch Queue (commit 034f0a9):
      OutwardScanWorkflow: Vision LLM moved to last step (after lot assignment)
      MismatchResolutionWorkflow: HOLD state, 4-hour timeout, GO_AHEAD/REJECTED/TIMEOUT_AUTO_REJECTED
      Kafka: cts.mismatch.{bank_id}.{branch_id} — 21 mismatch tests + 18 outward scan tests GREEN
      MISMATCH_* message keys in messages.yaml

  [x] Phase 4 — Drawee Fix: Vision FIRST + CBS LAST + SMB Human Review (commits 3886d38, 1c173b6, f71c74b):
      ChequeProcessingWorkflow reordered: detect_alteration FIRST, ocr_extract REMOVED,
        validate_cts2010 step 3, check_account_status new step 9 (after cbs_balance)
      human_review_topic() method: smb-scoped when smb_id set
      CTSInwardPipeline + CTSPipelineVisualizer updated
      CTSSMBReviewQueue.jsx at /cts/smb/review-queue — smbOnly gate
      Signature Verify activity: smb_proxy routing added — 21 tests GREEN

  [x] Phase 5 — SMB Portal (commits fcd2b75, 5d13e37, 8617a39):
      CTSSMBDashboard.jsx at /cts/smb/dashboard — inward summary, IET countdown, decisions, quick links
      CTSSMBReports.jsx at /cts/smb/reports — daily summary / RRF / settlement tabs with CSV downloads
      Row-level isolation: UserContext.sponsor_bank_id, RBACPolicy.smb_instrument_filter()
      SMB_ADMIN / SMB_EDITOR / SMB_VIEWER RBAC roles — 5 new RBAC tests GREEN (86 total)
      messages.yaml: CTS_SMB_HUMAN_REVIEW_ASSIGNED / CTS_SMB_DECISION_FILED / CTS_SMB_SETTLEMENT_AVAILABLE

  [x] Phase 6 — Agency Command Center (commit 3c012bc):
      shared/sb_connector/: base.py, sftp_generic.py, bancs_api.py, nelito_api.py — 35 tests GREEN
      ClearingSessionWorkflow: SB_NGCH vs AGENCY_SB_RELAY routing, EMPTY_SESSION outcome — 18 tests GREEN
      AgencyCCWorkflow: build_lot_package → sb_submit → relay Kafka → audit — 26 tests GREEN
      SBInwardForwardingWorkflow: CRL per instrument → PU fan-out, original_ngch_ts preserved
      CTSAgencyCC.jsx at /cts/agency-cc — sbOnly gate, useTheme()
      messages.yaml: 8 CTS_CC_* keys (262 total)

  [x] Phase 7 — SMB CBS Push Ingestion (commit 7d7c8bf):
      ARCHITECTURE: Go binary at SMB DROPPED → SMB CBS pushes CSV via Agency SFTP every 15 min
      modules/cts/smb_ingest/: models.py (StopPaymentRecord, PPSEntry, SignatureRecord — PII hashed)
        parser.py (SMBPushParser — bucket_amount, HMAC-SHA256 account hash)
      SMBVaultPushWorkflow: parse → update_vault → audit; idempotency via file_hash UNIQUE
      Alembic: cts.smb_push_sessions (file_hash UNIQUE)
      CTSAgencyCC.jsx: 4th tab 'SMB Push Sessions'
      messages.yaml: 4 CTS_SMB_PUSH_* keys (266 total) — 52 tests GREEN

  [x] Phase 8 — Hardening (commit 930d1f9):
      E2E test harness — 19 tests GREEN:
        tests/e2e/test_multi_scenario_cts.py — Scenario 1, 2, 3 + cross-scenario invariants
        Bug discovered + fixed: ClearingSessionWorkflow mock contract — seal_all_lots must be
        list[dict], relay key is agency_cc (not submit_to_sb)
      Performance benchmark: tests/performance/test_cts_500_cheque_benchmark.py
        @pytest.mark.performance — requires staging ASTRA_API_URL; 4 test variants
      Chaos Mesh 05-07:
        05-eeh-session-failure: gateway kill, branch network partition, 8s latency injection
        06-sb-connector-timeout: SFTP stall, BANCS_API 503 + Retry-After, Nelito partition
        07-smb-push-delayed: 18-min delay, gateway kill, malformed CSV injection

PHASE 7 — Pluggable Auth Connector (July 2026, COMPLETE)
  Context: Every entity level (SB / SMB / Branch / PU) independently configures its auth
    mechanism via Helm Layer 2 values. Three connectors available: saml | ldap_ad | local.
    ASTRA never stores passwords for SAML path (IdP authenticates). Local connector
    (argon2id) is the last-resort for smallest SMBs with no directory service.
    All connectors produce a uniform ASTRAIdentity — same RBAC path regardless of connector.

  [x] shared/auth/connectors/__init__.py, base.py — ASTRAIdentity (frozen Pydantic, entity_type ∈ {sb,smb,branch,pu},
       connector_used ∈ {saml,ldap_ad,local}), AuthConnector ABC (authenticate + health_check)
  [x] shared/auth/connectors/local.py — LocalAuthConnector (argon2id verify, 5-attempt lockout
       30-min lock, account inactive check, expired-lock bypass, _fetch/_update/_lock hooks)
  [x] shared/auth/connectors/ldap_ad.py — LDAPADConnector (LDAPS-only enforced at config,
       _ldap_bind_and_search hook, AD memberOf → first-match group_role_map, LDAPServerUnreachableError)
       LDAPADConnectorConfig: @field_validator rejects plain ldap:// at construction time
  [x] shared/auth/connectors/saml.py — SAMLConnector (SAML 2.0 assertion parse hook,
       name_id + group claim extraction, group_role_map, ASTRA never sees password)
  [x] shared/auth/connectors/factory.py — AuthConnectorFactory (entity-level routing,
       SMB default + per-smb_id overrides, connector caching, AuthConnectorConfigError on
       missing config or unknown entity_type)
  [x] shared/auth/exceptions.py — added: AuthenticationError, AccountLockedError,
       AuthorizationError, LDAPServerUnreachableError, AuthConnectorConfigError
  [x] infra/migrations/platform/20260705_add_local_auth_accounts.py — platform.local_auth_accounts
       (user_id PK, bank_id, entity_type, entity_id, username UNIQUE per bank, password_hash argon2id,
       role, clearing_zones[], is_active, failed_attempts, locked_until float, created_at, last_login_at)
  [x] messages.yaml: 8 new AUTH_* keys (274 total) — AUTH_LDAP_BIND_SUCCESS/FAILED,
       AUTH_LDAP_GROUP_UNMAPPED, AUTH_LDAP_SERVER_UNREACHABLE (CRITICAL),
       AUTH_LOCAL_LOGIN_SUCCESS/FAILED, AUTH_LOCAL_ACCOUNT_LOCKED (ERROR),
       AUTH_CONNECTOR_CONFIG_MISSING (CRITICAL)
  [x] infra/helm/values/banks/saraswat-coop/platform.yaml — auth: section added:
       SB → saml (ADFS), branch → ldap_ad (LDAPS port 636), pu → ldap_ad,
       smb.default → local, smb.overrides → commented example for pune-ucb LDAP
  [x] 40 tests GREEN (7 base, 11 local, 12 ldap_ad, 10 factory) — ldap3 + argon2-cffi deps

PHASE 8 — Pre-Live Smoke Test Suite (July 2026, COMPLETE)
  [x] Backend: apps/api/routers/admin_smoke_test.py
       GET /v1/admin/smoke-test — run all tests for caller's entity_type
       GET /v1/admin/smoke-test/{test_id} — single test; 403 on EntityScopeMismatchError
       SmokeTestStatus: PASS/WARN/FAIL/SKIP — all_clear=True iff fail==0 (WARN advisory)
       Entity scopes: sb (8 tests), smb (4 tests), branch (3 tests), pu (4 tests)
       Individual runners are stubs returning SKIP — wire real checks per deployment
       10 tests GREEN (tests/apps/api/routers/test_admin_smoke_test.py)
  [x] Frontend: apps/web/src/modules/cts/pages/CTSSmokeTest.jsx at /admin/smoke-test
       SB IT admin sees all 4 entity tabs (SB/SMB/Branch/PU); SMB sees only SMB tab
       Run All Tests animates sequentially per test with live status + latency
       Left-stripe colour encoding: PASS=green, WARN=amber, FAIL=red, RUNNING=violet pulse
       Summary strip: pass/fail/warn counts + ALL CLEAR or FAILURES banner
       Download Report → JSON file for bank IT admin's change management ticket
       Cycles 3 demo scenarios: all-pass → failures → warns on each re-run
       useTheme() + useBankContext() — fully dual-themed, sbOnly gate on entity tabs
  [x] AppShell: ✓ Go-Live Test nav item added to Admin section (perm: config:layer2:change)
  [x] App.jsx: Route /admin/smoke-test wired to CTSSmokeTest
```
