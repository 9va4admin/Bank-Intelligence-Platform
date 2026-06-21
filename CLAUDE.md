# ASTRA — Bank Intelligence Platform
## Claude Code Master Index & Project Constitution

> **This file is the single source of truth for Claude Code sessions.**
> Every architectural decision, tech choice, NFR, and design rationale
> is recorded here. Read this fully before writing any code.

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
- Solves the RBI T+3 hour IET (Item Expiry Time) mandate (Jan 2026)
- Missed IET = deemed approval = bank pays regardless of fraud
- One AI agent per inward cheque → decision in < 600ms
- 500 cheques → 500 parallel agents → entire batch < 600ms wall clock
- Target buyers: Any bank participating in CTS clearing — public sector banks (SBI, PNB, BoB, Canara), private sector banks (HDFC, ICICI, Axis, Kotak, Yes, IndusInd), small finance banks, urban co-operative banks, RRBs, foreign banks with Indian operations — any institution that processes inward cheques and is subject to RBI's IET mandate
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
│   └── ai-server/                     ← vLLM wrapper + model routing
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
│   │   │   ├── vault_sync_workflow.py ← CBS → Redis vault sync
│   │   │   └── activities/
│   │   │       ├── ocr.py
│   │   │       ├── alteration.py
│   │   │       ├── signature.py
│   │   │       ├── pps.py
│   │   │       ├── cbs.py
│   │   │       ├── fraud.py
│   │   │       ├── decision.py
│   │   │       └── ngch_filer.py
│   │   ├── vaults/
│   │   │   ├── signature_vault.py
│   │   │   └── pps_vault.py
│   │   └── mcp/
│   │       └── ngch_adapter.py        ← MCP server wrapping NGCH
│   │
│   └── ej/                            ← EJ domain (fully isolated)
│       ├── workflows/
│       │   ├── normalise_workflow.py
│       │   ├── dispute_workflow.py
│       │   └── activities/
│       │       ├── ingest.py
│       │       ├── fingerprint.py
│       │       ├── llm_parse.py
│       │       ├── validate.py
│       │       ├── dispute_match.py
│       │       └── cctv_extract.py
│       ├── parser/
│       │   └── llm_parser.py
│       ├── mcp/
│       │   └── branch_mcp_server.py   ← Edge MCP server (Go, see infra/)
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
│   │   ├── base.py                    ← Abstract CBS interface
│   │   ├── finacle.py
│   │   ├── bancs.py
│   │   └── flexcube.py
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
| `cts.inward.{bank_id}` | NGCH Adapter | CTS Agent Workers (KEDA) | Fan-out per inward cheque |
| `cts.decisions.{bank_id}` | CTS Agents | Audit Service, Analytics | All filed decisions |
| `cts.human.review.{bank_id}` | CTS Agents | Ops Workstation | Human review queue |
| `cts.vault.sync.{bank_id}` | CBS Connector | Vault Sync Worker | Signature/PPS updates |
| `ej.raw.ingested.{bank_id}` | EJ Ingestion Gateway | EJ Parse Workers | Trigger normalisation |
| `ej.canonical.{bank_id}` | EJ Parse Workers | Dispute Engine, Analytics | Normalised records |
| `ej.health.signals.{bank_id}` | EJ Parse Workers | Anomaly Detector | ATM health time-series |
| `platform.audit.events` | All Services | Immudb Writer | Immutable audit stream |
| `platform.notifications` | All Services | Notification Dispatcher | All notification triggers |

---

## 8. Temporal Workflows

### CTS Workflows
| Workflow | Trigger | Activities | Terminal States |
|---|---|---|---|
| `ChequeProcessingWorkflow` | Kafka `cts.inward` event | validate_cts2010, ocr_extract, detect_alteration, verify_signature, lookup_pps, check_cbs_balance, score_fraud, synthesise_decision, file_to_ngch, write_audit, send_notification | STP_CONFIRM, STP_RETURN, HUMAN_REVIEW |
| `HumanReviewWorkflow` | Signal from ChequeProcessingWorkflow | push_to_queue, wait_for_signal (max 55min), receive_decision, file_to_ngch, write_audit | REVIEWER_CONFIRMED, REVIEWER_RETURNED, TIMEOUT_AUTO_RETURNED |
| `VaultSyncWorkflow` | CBS event stream / schedule (6AM daily) | load_signatures_from_cbs, load_pps_from_cbs, warm_redis_vault, verify_vault_integrity | SYNC_COMPLETE |
| `IETWatchdogWorkflow` | Child of ChequeProcessingWorkflow | monitor_countdown, emergency_file_if_30s_remaining | SAFE, EMERGENCY_FILED |

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

## 16. Next Steps (Build Order)

```
PHASE 1 — Foundation (Weeks 1–4)
  [ ] Monorepo scaffold (this structure)
  [ ] Shared: auth, RBAC, config_service, OTel setup
  [ ] Shared: audit_event schema + Immudb client
  [ ] Shared: notification dispatcher (email + WhatsApp)
  [ ] Infra: Helm chart skeleton + bank-template.yaml
  [ ] Infra: Kafka topics, Redis, YugabyteDB schema migrations

PHASE 2 — CTS Core (Weeks 5–8)
  [ ] Vault: signature_vault + pps_vault (Redis)
  [ ] MCP: ngch_adapter (wraps SFTP, exposes MCP tools)
  [ ] Temporal: ChequeProcessingWorkflow + all activities
  [ ] AI: OCR activity (GOT-OCR2 via vLLM)
  [ ] AI: Signature verification activity (Siamese network)
  [ ] AI: Fraud scoring activity (XGBoost + SHAP)
  [ ] Temporal: IETWatchdogWorkflow
  [ ] API: CTS router endpoints
  [ ] Frontend: CTS ops workstation (human review queue)

PHASE 3 — Observability (Weeks 9–10)
  [ ] OTel instrumentation across all CTS services
  [ ] Grafana dashboards: infra + CTS metrics + AI explainability panel
  [ ] Langfuse integration for all LLM calls
  [ ] SHAP panel in ops workstation

PHASE 4 — EJ Module (Weeks 11–14)
  [ ] Edge: branch-ej-agent (Go MCP server)
  [ ] EJ ingestion gateway
  [ ] Temporal: EJNormalisationWorkflow (LLM parser)
  [ ] Temporal: DisputeResolutionWorkflow
  [ ] CCTV adapter (first OEM)
  [ ] Frontend: EJ dashboard + dispute console + fleet map

PHASE 5 — Hardening (Weeks 15–16)
  [ ] Active-active DR drills
  [ ] Chaos Mesh scenarios
  [ ] RBI compliance mapping verification
  [ ] Performance test: 500 cheques in < 600ms
  [ ] Security: penetration test prep
  [ ] Bank onboarding: first pilot bank Helm deploy
```

---

*Last updated: June 2026 | Maintained by Claude Code session*
*All architectural decisions final unless explicitly revised in this file*
