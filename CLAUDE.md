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
- Target buyers: Urban Co-op Banks, RRBs, mid-tier private banks
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
│   │   ├── cerebrum/                  ← Main Helm chart
│   │   └── values/
│   │       ├── _defaults.yaml         ← Platform defaults (non-overridable)
│   │       ├── bank-template.yaml     ← New bank onboarding template
│   │       └── banks/
│   │           └── example-bank.yaml  ← Example bank config
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

```
LEVEL 1 — Platform Defaults (in code, non-overridable)
  min_tls_version: "1.3"
  audit_trail_enabled: true  # cannot be turned off
  data_localisation: enforced
  hsm_required: true

LEVEL 2 — Bank Config (Helm values/bank-{id}.yaml, maker-checker)
  iet_minutes: 180
  human_review_fraud_threshold: 0.72
  stp_auto_confirm_threshold: 0.92
  max_agent_swarm_size: 500
  cbs_connector_type: finacle
  module_cts_enabled: true
  module_ej_enabled: false
  high_value_amount_threshold: 500000

LEVEL 3 — Module Config (Admin UI, ops manager role)
  special_cheque_routes: [GOVERNMENT, COURT_ORDER]
  ej_pull_schedule: "*/15 * * * *"
  dispute_auto_resolve_categories: [BALANCE_SUFFICIENT, DISPENSE_CONFIRMED]

LEVEL 4 — User Preferences (individual users, UI)
  dashboard_layout, notification_preferences, locale
```

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
