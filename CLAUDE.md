# ASTRA — Bank Intelligence Platform
## Claude Code Master Index & Project Constitution

> **This file is the single source of truth for Claude Code sessions.**
> Read this fully before writing any code.

> **Standing Session Rule:** After every task — commit all changed/created files and push immediately. Never leave files uncommitted at end of task.

---

## 0. Project Identity

| Field | Value |
|---|---|
| Platform Name | **ASTRA** — Automated Settlement and Transaction Recognition Architecture |
| Tagline | Precision Banking. Zero Compromise. |
| Author | Nilesh Shah (Ex-NPCI · Piramal · Fullerton/SMFG) |
| Classification | Confidential — Banking Grade |
| Started | June 2026 |
| Repo | 9va4admin/bank-intelligence-platform |
| Branch convention | `claude/` prefix for AI-assisted development |

---

## 1. Business Context

**Module 1 — CTS (Cheque Truncation System)**
- Handles both sides of CTS clearing:
  - **Outward** (Presentee Bank): scanner capture → MICR extraction → CTS-2010 compliance → lot/batch → endorsement → NGCH submission → session reconciliation + RRF
  - **Inward** (Drawee Bank): solves RBI T+3 hour IET mandate (Jan 2026). Missed IET = deemed approval = bank pays regardless of fraud. One AI agent per cheque → decision < 600ms. 500 cheques → 500 parallel agents → entire batch < 600ms.
  - SMB sponsor routing: Saraswat-class UCBs route outward instruments for smaller UCBs
- Buyers: any Indian bank in CTS clearing — PSBs, private, SFBs, UCBs, RRBs, foreign banks
- 18-month first-mover window before incumbents (Nelito, TCS BaNCS) catch up

**Market:** CTS ₹71 lakh crore / 609M cheques/year (FY25).

---

## 2. Architecture Decisions (All Final — Do Not Revisit Without Recording Here)

### 2.1 Deployment Model
- **Active-Active across 2 Data Centers** — both serve live traffic
- RPO = 0, RTO < 30 seconds for DC failure
- Air-gapped DC3 for backups only (NOT serving traffic)
- All on-premises — zero cloud dependencies (regulatory + data localisation)
- Per-bank: isolated Kubernetes namespace

### 2.2 Multi-Center (Large Banks)
- Regional Processing Centers (RPCs) per clearing zone, each connects to zone NGCH independently
- No outward consolidation — NPCI handles cross-zone settlement
- Central Intelligence Hub aggregates reporting; cross-center signature lookup hub-and-spoke
- PPS vault: always hub-and-spoke

### 2.3 MCP as Integration Standard
- MCP = universal integration layer for AI agents
- NGCH Adapter wraps existing SFTP/API as MCP tools; future: direct NPCI MCP server
- CBS Connector as MCP server (read-only, async)
- MCP transport: always HTTPS with mTLS

### 2.4 On-Premises Deployment & Upgrade Model

Two independent Helm charts: `astra-platform / astra-cts`. Banks own their ArgoCD and pull from ASTRA's OCI registry — ASTRA team has zero direct cluster access. Each bank has `infra/helm/values/banks/{bank_id}/` — no bank data crosses environments. Schema migrations always via Alembic, backwards-compatible for one version, run as K8s Job pre-deploy with auto-rollback on failure.

### 2.5 Observability — No Grafana/Prometheus/Loki/Tempo in Mandatory Stack

**Decision (2026-07-21):** Banks deploying ASTRA on-prem face strict CAB approval for every Docker image. Adding 4 OSS observability containers creates a procurement and security-review burden that may block deployment. These tools also surface raw infra metrics — not the contextual operational signals bank operators actually need.

**What replaced them:**
- **OTel instrumentation stays** — zero Docker cost; library only; spans emitted but not stored in mandatory infra
- **ASTRA Ops Dashboard** — React pages in the existing web app, consuming operational signals from YugabyteDB + Redis + Temporal SDK + Kafka admin client via `apps/api/routers/observability.py`
- **Alert engine** — `PlatformHealthCheckWorkflow` (Temporal, 60s cadence) checks thresholds from config_service → `shared/notifications/dispatcher.py` → WhatsApp + email
- **Optional sidecar chart** — banks that want Grafana/Tempo for developer debugging may install the optional `astra-observability` Helm chart; not shipped by default and not required for production

**Standing rule:** Before adding any new OSS Docker container to the mandatory stack, ask: "Can YugabyteDB + Redis + FastAPI + React handle this well enough?" If yes, build it internally.

---

## 3. Technology Stack (Final — Locked)

### Core Infrastructure
| Component | Technology |
|---|---|
| Container Orchestration | Kubernetes (on-prem) + Helm |
| Auto-scaling | KEDA (Kafka-driven) — 0→500 pods in <2s on lag |
| Service Mesh | Istio — mTLS, zero trust, per-pod identity |
| GitOps | ArgoCD |
| CI/CD | GitLab CI (self-hosted) |

### Application
| Component | Technology |
|---|---|
| Backend API | FastAPI (Python) — async, Pydantic v2 |
| Frontend | React JS + Vite + TailwindCSS + Recharts |
| State Management | React Query (TanStack) |
| Workflow Engine | Temporal (self-hosted, multi-cluster) |

### Data Layer
| Component | Technology |
|---|---|
| Operational DB | YugabyteDB YSQL (active-active, PG-compatible) |
| In-Memory / Vaults | Redis Cluster (6 nodes, 3+3 per DC) |
| Object Store | MinIO (WORM, ILM 3-tier lifecycle) |
| Immutable Audit | Immudb (cryptographic append-only, Merkle tree) |

### AI / ML
| Component | Technology |
|---|---|
| LLM Inference Server | vLLM (on-prem GPU, OpenAI-compatible API) |
| Vision LLM (cheque) | Qwen2-VL 72B → `cts-vision` queue |
| OCR | GOT-OCR2.0 (MICR, handwriting) → `cts-ocr` queue |
| Reasoning LLM | Llama 3.3 70B → `cts-reasoning` queue |
| Signature Verification | Siamese Neural Network (PyTorch, custom trained) |
| Fraud Scoring | XGBoost ensemble + SHAP + LLM explainer |
| Model Registry | MLflow (on-prem) |
| LLM Observability | Langfuse (on-prem) — every inference logged |
| GPU (pilot) | 4× RTX 4090; (production) 4–8× A100 80GB |

### Messaging, Security, Observability
| Component | Technology |
|---|---|
| Event Bus | Apache Kafka (Strimzi) + MirrorMaker 2 (DC replication) |
| Secrets | HashiCorp Vault (dynamic, 24hr rotation) |
| HSM | FIPS 140-2 Level 3 (NGCH PKI signing) |
| Policy Engine | OPA (Rego, business rules) |
| Identity | Bank IdP via SAML 2.0 |
| Observability | OpenTelemetry (instrumentation only, zero Docker cost) + ASTRA Ops Dashboard (React) + alert engine → dispatcher.py · Optional: `astra-observability` Helm chart for dev debugging |
| Notifications | Postal (email) + Meta WhatsApp Business API |

---

## 4. Monorepo Structure

```
cerebrum/
├── apps/
│   ├── web/src/modules/         ← React frontend: cts/, disputes/, observability/
│   │   └── shared/              ← Auth, layout, design system, ThemeContext
│   ├── api/routers/             ← FastAPI: cts.py, disputes.py, audit.py, admin.py, msv.py, platform.py
│   │   ├── middleware/          ← Auth, RBAC, rate limit, tracing
│   │   └── dependencies/        ← require_user_context (central auth chokepoint)
│   └── ai_server/               ← vLLM wrapper: vision.py, reasoning.py, ocr.py
│
├── modules/
│   ├── cts/                     ← CTS domain
│   │   ├── workflows/
│   │   │   ├── cheque_workflow.py          ← Inward: one cheque → one agent
│   │   │   ├── human_review_workflow.py    ← 55-min timeout, signal-driven
│   │   │   ├── iet_watchdog_workflow.py    ← T-30s emergency filer
│   │   │   ├── vault_sync_workflow.py
│   │   │   ├── outward_scan_workflow.py
│   │   │   ├── feedback_workflow.py        ← OCR feedback loop (automated retraining)
│   │   │   ├── mismatch_resolution_workflow.py
│   │   │   └── activities/                ← ocr, alteration, signature, pps, cbs, stop_payment,
│   │   │                                     fraud, decision, ngch_filer, write_audit,
│   │   │                                     kill_switch_lookup, feedback_activities
│   │   ├── feedback/            ← failure_classifier.py, signal_extractor.py, corpus_manager.py
│   │   ├── preprocessing/       ← payee_normalizer.py, name_lexicon.py, zone_extractor.py,
│   │   │                           cheque_dedup.py, ifsc_validator.py, micr_validator.py
│   │   ├── vaults/              ← signature_vault.py, pps_vault.py
│   │   ├── compliance/          ← CTS-2010 validation (cts2010.py)
│   │   ├── endorsement/         ← Batch stamping
│   │   ├── lot/                 ← Lot management
│   │   ├── reconciliation/      ← Session reconciliation engine
│   │   ├── rrf/                 ← Return Reason File generation
│   │   ├── scanner/             ← Physical scanner adapters + MICR
│   │   ├── sub_member/          ← SMB sponsor routing
│   │   ├── worker.py            ← Temporal worker: CTS task queues
│   │   └── mcp/ngch_adapter.py  ← MCP server wrapping NGCH
│   │
│   └── msv/                     ← Multi-Signature Validation (fully isolated)
│       ├── workflows/msv_workflow.py + activities/
│       ├── mandates/            ← models.py, bre_engine.py, assignment.py
│       ├── vaults/signatory_registry.py
│       ├── ai/                  ← signature_detector.py, embedding_model.py
│       └── enrollment/          ← account_enroller.py, bulk_enrollment.py, progress_tracker.py
│
├── shared/
│   ├── auth/                    ← rbac.py, auth_service.py, session_token.py, mfa.py,
│   │                               mfa_stores.py, enrollment_store.py
│   │   └── connectors/          ← base.py, local.py (argon2id), ldap_ad.py, saml.py, factory.py
│   ├── audit/                   ← immudb_client.py, audit_event.py (AuditEvent + HSM sign)
│   ├── config/config_service.py ← single point of access for ALL config + secrets
│   ├── cbs_connector/           ← base.py + finacle.py, bancs.py, flexcube.py (all implemented)
│   ├── notifications/           ← dispatcher.py, email_channel.py, whatsapp_channel.py
│   ├── observability/           ← otel_setup.py, langfuse_setup.py
│   ├── messages/locales/messages.yaml  ← single source of truth for ALL system messages
│   └── event_bus/topics.py      ← Kafka topic name constants (single source of truth)
│
├── infra/
│   ├── helm/                    ← astra-platform/, astra-cts/ + values/banks/{bank_id}/
│   ├── argocd/                  ← app-of-apps.yaml + bank Application templates
│   ├── opa/policies/            ← cts_routing.rego, cts_auto_return.rego
│   ├── migrations/              ← cts/ Alembic migration chain
│   └── k8s/                     ← temporal/, kafka/, redis/, yugabyte/, minio/, immudb/, vault/
└── compliance/
    └── rbi-it-framework/control-mapping.yaml
```

---

## 5. Configuration Hierarchy

Five layers. Lower layers cannot override higher layers. All changes at Layer 2+ are audited.

| Layer | Source | Who Changes | Hot-reload |
|---|---|---|---|
| 1 — Platform Constraints | Helm chart defaults (non-overridable) | ASTRA vendor via new release | No |
| 2 — Deployment Topology | `infra/helm/values/banks/{bank_id}.yaml` | ASTRA + bank_it_admin via PR | No (Helm upgrade) |
| 3 — Business Rules/Thresholds | Admin UI → YugabyteDB → config_service | ops_manager (maker) + bank_it_admin (checker) | YES — 30 seconds |
| 4 — Business Policy Rules | OPA Rego → YugabyteDB → OPA watcher | compliance_officer (author) + bank_it_admin (approve) | YES — OPA live reload |
| 5 — User Preferences | YugabyteDB per-user record | Individual user via UI | YES |

**Layer 1 non-overridable keys:** `min_tls_version: "1.3"`, `audit_trail_enabled: true`, `data_localisation: enforced`, `hsm_required: true`, `exactly_once_ngch: true`, `iet_watchdog_enabled: true`

**Layer 3 key examples:** `iet_minutes: 180`, `stp_auto_confirm_threshold: 0.92`, `human_review_fraud_threshold: 0.72`, `high_value_amount_threshold: 500000`, `vault_miss_action: HUMAN_REVIEW` (never changeable to AUTO_RETURN), `payee_match_threshold: 0.82`, `ocr_feedback_retrain_threshold: 500`, `ocr_promote_min_improvement: 0.02`

**Config-Service:** `shared/config/config_service.py` is the ONLY gateway. No service reads env vars directly. Layer 3 cached in Redis 30s TTL; invalidated on `platform.config.changed` Kafka event. Layer 4 via OPA decision API per request.

---

## 6. User Roles (RBAC)

| Role | Module Access | Data Access | Config Access |
|---|---|---|---|
| ops_reviewer | CTS human queue | Own zone only | None |
| fraud_analyst | CTS analytics | Scores + SHAP, no PII | None |
| ops_manager | CTS full | Cross-zone reports | Layer 3 |
| bank_it_admin | Admin console | Infrastructure only | Layer 2 (maker-checker) |
| compliance_officer | Audit + reports | Read-only audit trail | None |
| rbi_examiner | Audit only (time-scoped) | Read-only, date-scoped | None |
| ml_engineer | AI server + MLflow | Inference logs, no customer data | None |

ABAC on top: `ops_reviewer` scoped to `clearing_zone`; all roles scoped to `bank_id`.

---

## 7. Kafka Topics

> **See `shared/event_bus/topics.py`** — single source of truth for all topic name constants.

Key topic prefixes: `cts.*` (CTS only), `platform.*` (shared services).
CTS inward fan-out: `cts.inward.{bank_id}`. Human review: `cts.human.review.{bank_id}[.{smb_id}]`. SMB: `cts.smb.inbound.{bank_id}`. OCR feedback: `cts.ocr.feedback.{bank_id}`. Audit: `platform.audit.events`. Config changes: `platform.config.changed`.

---

## 8. Temporal Workflows

> **See `modules/cts/workflows/`** — code is authoritative.

**CTS Inward:** `ChequeProcessingWorkflow` (main), `IETWatchdogWorkflow` (T-30s child, always first), `HumanReviewWorkflow` (55-min timeout, signal-driven), `VaultSyncWorkflow` (6AM daily)

**CTS Outward:** `OutwardScanWorkflow`, `BatchEndorsementWorkflow`, `NGCHSubmissionWorkflow`, `SessionReconciliationWorkflow`, `SMBForwardingWorkflow`, `MismatchResolutionWorkflow` (4-hour timeout)

**CTS Feedback:** `FeedbackAccumulatorWorkflow` (persistent per-bank, signals from every decision), `ModelRetrainWorkflow` (auto-triggered, zero human action)

**Platform:** `NotificationWorkflow`, `AuditWriteWorkflow`, `BankOnboardingWorkflow`, `PlatformHealthCheckWorkflow` (60s cadence, alert engine → dispatcher.py)

**Workflow ID pattern (idempotency):** `cts-{bank_id}-{instrument_id}`, `cts-feedback-{bank_id}`, `cts-retrain-{bank_id}-{corpus_type}-{ts}`

---

## 9. MCP Servers

> **See `modules/cts/mcp/`** for implementations.

`ngch-adapter` (NGCH SFTP/API wrapper), `cbs-connector` (read-only, per CBS type), `cctv-adapter` (per vendor), `astra-diagnostic-mcp` (consent-gated, OPA-enforced, non-PII signals only)

---

## 10. Storage Tiers

| Tier | Hardware | Retention | Technology |
|---|---|---|---|
| 0 — Processing | NVMe (in-server) | Minutes–hours | Redis + local disk |
| 1 — Hot | NVMe/SSD networked | 90 days rolling | MinIO (hot) + YugabyteDB |
| 2 — Warm | HDD object store | 91 days–2 years | MinIO (warm, auto-transition day 90) |
| 3 — Cold/WORM | LTO-9 tape or MinIO Glacier | 10 years (legal hold) | MinIO COMPLIANCE mode, object lock |

---

## 11. Security Principles (Non-Negotiable)

1. **Zero Trust** — every request authenticated and authorised, no implicit VPC trust
2. **Least Privilege** — minimum access per service/user, no wildcards
3. **No Secrets in Code/Git** — `gitleaks` pre-commit hook; Vault only
4. **HSM for All PKI** — FIPS 140-2 Level 3; no software-held private keys
5. **mTLS Everywhere** — Istio; every pod has a certificate
6. **Audit Always On** — cannot be disabled; tampering is cryptographically detectable
7. **Data Never Leaves Bank** — zero cloud, zero vendor access, 100% on-premises
8. **Encryption Always** — AES-256 at rest, TLS 1.3 in transit, column-level for PII
9. **No Black-Box AI** — every AI decision has SHAP + human-readable rationale
10. **Exactly-Once** — Temporal idempotency; no duplicate NGCH submissions ever

---

## 12. NFR Summary (Engineering Constitution)

**Critical SLAs:** CTS agent decision < 600ms (p99) · IET breach rate **0.000%** (non-negotiable) · Vault lookup < 5ms · DC failover < 30s · RPO = 0

**Availability:** CTS clearing hours 99.999% · CTS off-hours 99.99%

**AI thresholds:** OCR > 99.0% · Signature precision > 97.0% · Fraud F1 > 0.92 · False positive < 3% · False negative < 1%

**Model drift:** Alert at 2% drop over 7 days · Auto-tighten at 5% · Pull model at 8%

**Graceful degradation (priority order):**
```
LLM down        → rule-based fallback → human review
CBS unreachable → image-only processing → file before IET
Vault stale     → ALL to human review (NEVER auto-return on miss)
NGCH down       → queue in Temporal → file on reconnect (IET watchdog active)
DC1 failed      → DC2 handles 100% automatically
NEVER: silent failure | NEVER: IET breach | NEVER: duplicate NGCH filing
```

**Caching:** Vault = cache-aside + write-through + event invalidation · AI outputs = NEVER cached · Sessions = Redis 15-min TTL · Dashboard = Redis 60-sec TTL

**Auto-scaling:** CTS workers scale on Kafka lag > 10; min 2 pods warm; +50 pods/30s up, -10 pods/60s down

---

## 13. Development Rules for Claude Code

### Before Writing Any Code
1. Check this CLAUDE.md for existing decisions
2. Never re-architect — follow what is here; propose changes if needed

### Code Standards
- Python: FastAPI, Pydantic v2, async throughout; `structlog` (never `print()`)
- React: functional components, React Query for all server state
- No hardcoded values — all config from `config_service`
- Every CTS activity: OTel span required
- Every AI call: Langfuse trace required
- Every YugabyteDB write: Immudb audit write required immediately after

### Testing Requirements (TDD — RED before GREEN, no exceptions)
- Coverage: > 80% overall, > 95% for CTS workflow activities
- No mock for: Immudb writes, NGCH submissions
- Show pytest FAILED output before writing any implementation

### Git Conventions
- Branch: `claude/` prefix; commits: `feat:` / `fix:` / `test:` / `infra:`
- No secrets in any commit; PR required for: workflows, vaults, NGCH adapter, audit service

### Forbidden Patterns
- `SELECT *` on PII tables · Full PII in logs · HTTP without mTLS · Any credential outside Vault
- AI decision without SHAP · NGCH submission outside `ngch_filer` activity

---

## 14. Build Status & Next Steps

> Full history: [docs/build-history.md](docs/build-history.md)

**Completed:** Phases 1–15 (Foundation → CTS Core → Observability → Hardening → Multi-Scenario CTS → Auth Connectors → Smoke Tests → Security Remediation → Incident Management → Audit/Notification Gap Closure → TOTP/MFA + MSV → @workflow.defn/@activity.defn + DI gaps → ASTRA Ops Dashboard + alert engine → POC E2E + Federal Bank onboarding → `__astra-admin` platform super admin + `platform_admin` RBAC role → 9-script Indic transliteration + Malayalam Christian-name lexicon → automated OCR feedback loop: failure classifier + corpus accumulation + `FeedbackAccumulatorWorkflow` + `ModelRetrainWorkflow`)

**Immediate Next (priority order):**
1. **Wire AuthConnectorFactory into real login flow** — `dev_auth_server.py` + `main.py` bypass connectors entirely; SAML/LDAP hooks still raise `NotImplementedError` (deliberately deferred)
2. **Wire `FeedbackAccumulatorWorkflow` into `ChequeProcessingWorkflow`** — feedback loop infrastructure is built but signals are not yet emitted from the main workflow; loop is dormant without this
3. **Fix `check_cheque_dedup` ImportError** — outward scan workflow tests failing; function exists but not exported from `outward_scan_activities`
4. **Pilot bank deployment** — validate `saraswat-coop` Helm values against real K8s cluster
5. **NPCI API Modernisation Phase A** — trigger: NPCI concept note acceptance; see [docs/npci-readiness-plan.md](docs/npci-readiness-plan.md)
6. **Security hardening** — OWASP ZAP + pen test prep

**Open security findings (not yet fixed):**
- `rbac.py:210-211`: fail-open defaults (SB/EDIT)
- `HumanReviewWorkflow`: 55-min timeout is a flat constant, not config-aware (HIGH-1)
- SMB notify side effects missing from real `run()` (HIGH-4)
- `mfa_stores.py:60-61`: direct `os.environ.get("VAULT_ADDR")` — needs config_service

---

## 15. NPCI API Modernisation

> Full plan: [docs/npci-readiness-plan.md](docs/npci-readiness-plan.md) · Trigger: NPCI accepts concept note in `docs/NPCI-CTS-Modernisation-ConceptNote.html`

Phases: A (REST API, 6 months) → B (Webhook push, 12 months) → C (MCP client, 24 months). ~70% of internal plumbing ready; gap is entirely in NPCI-facing transport layer.

*Last updated: 2026-08-13 | All architectural decisions final unless explicitly revised in this file*
