# ASTRA Platform — Operator & Administrator User Manual

> **Classification:** Confidential — Banking Grade  
> **Version:** 1.0 — July 2026  
> **Author:** Nilesh Shah (Ex-NPCI · Piramal · Fullerton/SMFG)  
> **Deployment:** On-Premises · Air-Gapped · Per-Bank  

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [System Architecture](#2-system-architecture)
3. [Roles & Access Control](#3-roles--access-control)
4. [CTS Inward (Drawee) Screens](#4-cts-inward-drawee-screens)
   - [Drawee Workstation](#41-drawee-workstation)
   - [Human Review Queue](#42-human-review-queue)
   - [IET Watchdog](#43-iet-watchdog)
   - [Decisions Log](#44-decisions-log)
   - [Pipeline Visualizer](#45-pipeline-visualizer)
5. [CTS Outward (Presentee) Screens](#5-cts-outward-presentee-screens)
   - [Scanner](#51-scanner)
   - [Image Quality Assessment (IQA)](#52-image-quality-assessment-iqa)
   - [Presentment File](#53-presentment-file)
   - [Endorsement](#54-endorsement)
   - [Session Reconciliation](#55-session-reconciliation)
6. [CTS Vault Screens](#6-cts-vault-screens)
   - [Vault Status](#61-vault-status)
   - [Vault Sync](#62-vault-sync)
7. [SMB Operations Screens](#7-smb-operations-screens)
   - [SMB Dashboard](#71-smb-dashboard)
   - [SMB Review Queue](#72-smb-review-queue)
   - [SMB Reports](#73-smb-reports)
   - [Agency Command Center](#74-agency-command-center)
8. [Branch Portal Screens](#8-branch-portal-screens)
   - [Branch Dashboard](#81-branch-dashboard)
   - [Mismatch Queue](#82-mismatch-queue)
9. [Admin & Config Screens](#9-admin--config-screens)
   - [MCP Connection Config](#91-mcp-connection-config)
   - [Thresholds Configuration](#92-thresholds-configuration)
   - [Pre-Live Smoke Test](#93-pre-live-smoke-test)
   - [User Management](#94-user-management)
   - [Audit Trail](#95-audit-trail)
10. [Live Demo Pipeline](#10-live-demo-pipeline)
11. [Reference: Kafka Topics (CTS)](#11-reference-kafka-topics-cts)
12. [Reference: Database Tables (CTS)](#12-reference-database-tables-cts)
13. [Reference: Temporal Workflows (CTS)](#13-reference-temporal-workflows-cts)
14. [Reference: Notification Messages (CTS)](#14-reference-notification-messages-cts)

---

## 1. Platform Overview

ASTRA (**Automated Settlement and Transaction Recognition Architecture**) is a banking-grade AI platform deployed on-premises inside each bank's own data centre.

**Module covered in this manual: CTS (Cheque Truncation System)**

CTS reimagines India's cheque clearing infrastructure with agentic AI. It handles both sides of CTS clearing:

| Side | Role | What ASTRA Does |
|------|------|-----------------|
| **Inward (Drawee)** | Bank's own cheques arrive from NGCH | One AI agent per cheque → CONFIRM/RETURN decision in <600ms |
| **Outward (Presentee)** | Bank's customers deposit cheques drawn on others | Scanner → MICR → CTS-2010 compliance → lot → endorsement → NGCH submission |

### Critical SLAs

| Metric | Target |
|--------|--------|
| CTS agent decision | <600ms wall clock (p99) |
| **IET breach rate** | **0.000% — absolute zero tolerance** |
| Vault lookup (Redis) | <5ms (p99) |
| DC failover | <30 seconds |
| RPO | 0 (active-active) |

> **IET Zero-Tolerance:** A missed IET (Item Expiry Time) = deemed approval = bank pays regardless of fraud. ASTRA's `IETWatchdogWorkflow` emergency-files at T-30 seconds to guarantee zero breach.

### Deployment Model

- Fully isolated per-bank Kubernetes namespace (`astra-cts-{bank_id}`)
- Zero cloud dependency — 100% on-premises
- ArgoCD GitOps pull model — ASTRA team never has shell access to production
- Three independent Helm charts: `astra-platform`, `astra-cts`, `astra-ej`
- Active-Active across 2 DCs (RPO=0, RTO<30s)

---

## 2. System Architecture

### AI Cascade (L1 → L2)

To stay within 600ms for inward processing, a two-tier vision model is used:

1. **L1 Guard — Qwen2-VL 7B** handles ~90% of cheques in <100ms on RTX 4090.  
   Accepted if: confidence ≥ `ai.cascade.l1_confidence_threshold` (default 0.85) AND amount < `ai.cascade.high_value_threshold` (default ₹50L).
2. **L2 Full — Qwen2-VL 72B** escalated when L1 confidence is insufficient, amount ≥ ₹50L, or OPA policy forces it (government cheques, court orders). Dedicated A100 80GB GPU.

Result: ~90% of cheques clear in <100ms; ~10% use L2. Total batch <600ms wall clock.

### Five-Layer Configuration Hierarchy

| Layer | Who Changes | How | Hot-Reload |
|-------|-------------|-----|-----------|
| 1 — Platform Constraints | ASTRA vendor only | New Helm chart release | No (pod restart) |
| 2 — Deployment Topology | ASTRA vendor + bank_it_admin | PR to repo → ArgoCD sync | No (Helm upgrade) |
| 3 — Business Rules / Thresholds | ops_manager (maker) + bank_it_admin (checker) | Admin UI → DB → Kafka | **Yes (<30 seconds)** |
| 4 — Business Policy Rules (OPA Rego) | compliance_officer (author) + bank_it_admin (approve) | OPA hot-reload | **Yes (OPA bundle)** |
| 5 — User Preferences | Individual user | UI settings | Yes (per-request) |

> **Layer 1 immutable constraint:** `vault_miss_action` is permanently `HUMAN_REVIEW`. No bank can change this to `AUTO_RETURN` through any UI, API, or config layer.

### Key Infrastructure Components (CTS)

| Component | Technology | CTS Use |
|-----------|-----------|---------|
| Workflow Engine | Temporal (self-hosted) | One `ChequeProcessingWorkflow` per inward cheque |
| Event Bus | Kafka (Strimzi) | Fan-out per cheque; audit stream; vault sync |
| Vault | Redis Cluster (`redis-cts`) | Signature vault + PPS vault; <5ms lookups |
| Database | YugabyteDB YSQL (`cts` schema) | All CTS operational records |
| Object Store | MinIO (WORM) | Cheque images; 10-year regulatory retention |
| Immutable Audit | Immudb | Cryptographic append-only; HSM-signed |
| Policy Engine | OPA (Rego policies) | Layer 4 routing decisions |
| AI Vision | Qwen2-VL (7B L1, 72B L2) | Alteration detection |
| AI OCR | GOT-OCR2.0 | MICR line + handwriting extraction |
| Fraud Scoring | XGBoost + SHAP | Structured feature fraud score with explainability |
| Signature Verify | Siamese Neural Network | Custom-trained on bank's own specimens |

---

## 3. Roles & Access Control

### Bank Type Scoping

Every user belongs to either:
- **SB** — Sponsor Bank (direct NGCH member, e.g. Saraswat Co-operative Bank)
- **SMB** — Sub-Member Bank (routes through SB, e.g. smaller UCBs)

All data, downloads, and config panels are automatically scoped to the user's bank type at login. There is no manual override in production.

### RBAC Roles

| Role | Can Do | Cannot Do |
|------|--------|-----------|
| `ops_reviewer` | View human review queue; CONFIRM/RETURN decisions; own zone only | Other zones; config; PII fields |
| `fraud_analyst` | Analytics, fraud scores, SHAP values; read-only | Submit decisions; configure anything |
| `ops_manager` | Everything ops_reviewer + cross-zone analytics + Layer 3 maker + SMB ledger + PII | Approve own threshold changes; manage users |
| `bank_it_admin` | Admin console; Layer 2+3 checker; user management; vault sync trigger | View transaction data; submit decisions |
| `compliance_officer` | Full Immudb audit read; PII; analytics read; OPA Rego policy authoring | Submit decisions; configure Layer 3 |
| `rbi_examiner` | Audit trail (time-scoped to engagement) | Everything else — most restricted role |
| `ml_engineer` | AI metrics, MLflow, inference latency dashboards | Transaction data; config |
| `smb_admin` | Review queue (own SMB); own ledger; own user management | Other SMBs; SB instruments; config |
| `smb_editor` | Review queue (own SMB); ledger (read) | Manage users; configure anything |
| `smb_viewer` | Review queue (read-only); ledger (read) | Submit decisions; configure anything |

**ABAC Overlay:** `ops_reviewer` is further scoped to `clearing_zone` attribute. All roles are scoped to `bank_id` — cross-tenant data access is structurally impossible.

### Authentication Connectors (per entity level)

| Connector | When Used | How |
|-----------|-----------|-----|
| `saml` | SB staff (enterprise IdP — ADFS, Azure AD) | SAML 2.0 assertion. ASTRA never sees password. Group claims → role mapping. |
| `ldap_ad` | Branch / PU staff (Active Directory) | LDAPS only (port 636 enforced at config). `memberOf` → `group_role_map`. |
| `local` | Smallest SMBs with no directory service | argon2id password hash. 5-attempt lockout (30-minute lock). |

All connectors produce a uniform `ASTRAIdentity` — identical RBAC path regardless of authentication method.

---

## 4. CTS Inward (Drawee) Screens

### 4.1 Drawee Workstation

**Route:** `/#/cts`  
**Access:** `ops_reviewer`, `ops_manager`, `fraud_analyst`

**Purpose:** Primary inward clearing operations screen. Real-time state of all inward cheques arriving from NGCH. IET countdowns, AI decisions, queue depths, escalated items.

#### Who Sees What
- **ops_reviewer:** Own `clearing_zone` only. IET countdown per item. CONFIRM/RETURN action buttons.
- **ops_manager:** All zones. Cross-zone aggregation. Layer 3 threshold quick-view.
- **fraud_analyst:** Read-only. Fraud scores, SHAP values, AI confidence metrics. No PII.

#### Background Process (What Happens When a Cheque Arrives)

1. **NGCH Adapter** polls NGCH SFTP (or receives webhook). `PXFParser` extracts per-item `ItemExpiryTime` (IST→UTC). Publishes to `cts.inward.{bank_id}` Kafka.
2. **KEDA auto-scales** `cts-agent-worker` pods on Kafka lag >10 (up to 500 pods, +50 pods every 30s).
3. **`ChequeProcessingWorkflow`** fires per cheque. `IETWatchdogWorkflow` spawned first (ABANDON policy).
4. **STP Decision** → filed to NGCH via `ngch_filer` activity → published to `cts.decisions.{bank_id}`.
5. **HUMAN_REVIEW escalation** → pushed to `cts.human.review.{bank_id}` → `HumanReviewWorkflow` starts 55-minute timer.

#### Tables Written
- `cts.cheque_instruments` — master record (PII columns pgcrypto-encrypted)
- `cts.inward_clearing_items` — IET deadline, decision, return reason code
- `cts.agent_decisions` — AI scores, SHAP values (JSONB), fraud rationale
- `cts.human_review_items` — escalated items with context_bundle
- `cts.ngch_submissions` — exactly-once filing record (`idempotency_key UNIQUE`)
- Immudb `cts_events` — cryptographic audit trail for every state change

#### Success State
STP confirm rate ≥85%. IET breach count = 0. Human review queue draining within 30 minutes. Vault hit rate ≥99%.

#### Failure / Alert States
- **IET Risk:** Grafana alert at T-60 minutes. `IETWatchdogWorkflow` emergency-files at T-30 seconds.
- **AI Degraded:** vLLM down → all cheques auto-route to human review. ops_manager notified.
- **CBS Unreachable:** Degraded mode — image-only path, continue processing. ops_manager + bank_it_admin notified.

#### Notifications

| Event | Message Key | Channel | Recipient |
|-------|-------------|---------|-----------|
| Human review escalation | `CTS_WF_HUMAN_REVIEW_ESCALATED` | UI + WhatsApp | ops_reviewer (zone-scoped) |
| IET breach imminent (<30 min) | `CTS_NGCH_IET_IMMINENT` | UI + WhatsApp + Email | ops_manager (**P0 — never debounced**) |
| Fraud score above threshold | `CTS_WF_FRAUD_HIGH_RISK` | UI + Email | fraud_analyst, ops_manager |
| CBS unreachable | `CTS_WF_CBS_UNREACHABLE_DEGRADED` | UI + WhatsApp | ops_manager, bank_it_admin |
| Alteration detected | `CTS_WF_ALTERATION_DETECTED` | UI + Email | fraud_analyst, ops_manager |

---

### 4.2 Human Review Queue

**Route:** Embedded in Drawee Workstation; dedicated queue panel  
**Access:** `ops_reviewer`, `ops_manager`

**Purpose:** Escalated cheques requiring human CONFIRM/RETURN decision. Each item shows assembled context bundle: cheque images (front/back), OCR output, SHAP explainer, fraud score, all AI findings.

#### Why Items Appear Here (Escalation Triggers)
- OCR confidence < `ocr.min_confidence`
- Alteration detected or suspected by Vision LLM
- Signature match score < `signature.min_match_score`
- Signature vault miss (specimen not in Redis)
- PPS vault miss or PPS amount mismatch
- CBS account frozen / closed / dormant
- Stop payment instruction active
- Fraud score in human-review band (between auto-confirm and auto-return thresholds)
- OPA Layer 4 policy override (government/court-order cheques)
- Amount figures vs. words mismatch in OCR
- vLLM model unavailable (degraded mode)

#### Timer Logic
`HumanReviewWorkflow` starts a **55-minute timer**. No action within 55 minutes → auto-return. `IETWatchdogWorkflow` runs in parallel as a safety backstop — see §4.3 for what it actually does when it fires.

#### On CONFIRM
1. Reviewer clicks CONFIRM → `POST /v1/cts/review/{instrument_id}/decide`
2. API sends Temporal signal `receive_decision` to `HumanReviewWorkflow`
3. `HumanReviewWorkflow` first signals `IETWatchdogWorkflow` with the reviewer's real decision (`decision_ready`) — so if the IET deadline hits mid-filing, the watchdog fires *this* decision instead of guessing
4. Workflow fires `file_to_ngch` → NGCHAdapter → exactly-once CONFIRM to NGCH
5. Signals `IETWatchdogWorkflow` again (`filing_complete`) so it stands down immediately rather than waiting out the rest of its window
6. `write_audit` → HSM-signed AuditEvent → Immudb, event type `CTS_WF_HUMAN_CONFIRMED` (or `CTS_WF_HUMAN_RETURNED` on RETURN). Status = `REVIEWER_CONFIRMED`

If the watchdog wins the filing race (fires first because filing was slow), `HumanReviewWorkflow`'s own `file_to_ngch` call gets NGCH's duplicate-filing rejection, which it treats as success — exactly one filing reaches NGCH either way, and the audit trail still records the reviewer's real decision, not just "something was filed."

#### Success
Queue empties within 30 minutes. No timeout auto-returns. All items actioned before IET deadline.

#### Failure
**Timeout Auto-Return:** `CTS_WF_REVIEW_TIMEOUT` → WhatsApp + Email to ops_manager. Logged as compliance event in Immudb.

---

### 4.3 IET Watchdog

**Not a UI screen — a non-disableable Temporal safety system.**

> `IETWatchdogWorkflow` is spawned as a child workflow (ABANDON policy) before **any** other processing begins for every inward cheque. It cannot be disabled by any configuration layer. IET breach rate = 0.000%.

#### How It Works

1. **Spawned first** — `ChequeProcessingWorkflow` spawns `IETWatchdogWorkflow` with `ParentClosePolicy.ABANDON`. If parent crashes, watchdog survives independently.
2. **Countdown** — waits until T-30 seconds *or* a `filing_complete` signal from the parent (or from `HumanReviewWorkflow`, for human-reviewed cheques), whichever comes first.
3. **Emergency filing** — if it wakes at T-30s with no `filing_complete` signal received, it emergency-files whatever decision was last sent via a `decision_ready` signal (CONFIRM or RETURN — whatever the parent had actually decided, even if it hadn't finished filing yet). **CONFIRM is only used as a last resort**, when no decision was ever signalled at all — this still never makes the outcome worse than doing nothing, since RBI's own deemed-approval default for a missed IET is CONFIRM anyway; the difference is ASTRA now gets an explicit, audited record (`CTS_WF_IET_WATCHDOG_FIRED`) instead of a silent regulatory default.
4. **Duplicate-safe** — idempotency key = parent workflow ID, so if both the parent and the watchdog attempt to file, NGCH's 409 response resolves the race safely; whichever filed first wins, and it is always audited.

> **IET deadlines come from PXF XML `ItemExpiryTime` field (per-item, IST→UTC)**, NOT from the shared `iet_minutes` config. Per-item precision is critical for multi-instrument batches.

---

### 4.4 Decisions Log

**Route:** `/#/cts/decisions`  
**Access:** `ops_manager`, `fraud_analyst`, `compliance_officer`

**Purpose:** Searchable, filterable log of all inward cheque decisions. Shows masked instrument ID, decision type, AI confidence scores, fraud score, filing timestamp. CSV export available.

#### Data Shown (PII Rules Enforced)
- Account display: last 4 digits only (`****4521`) — never raw account number
- Amount: range bucket only (`₹[1L-5L]`) — never exact amount
- SHAP values: `fraud_analyst`, `ops_manager`, `compliance_officer` only
- Reviewer name (if human review): `ops_manager`, `compliance_officer` only

**Tables Read:** `cts.inward_clearing_items`, `cts.agent_decisions`, `cts.ngch_submissions`, `cts.human_review_items`

---

### 4.5 Pipeline Visualizer

**Route:** `/#/cts/inward-pipeline`  
**Access:** `ops_manager`, `bank_it_admin`, `fraud_analyst`

**Purpose:** Visual monitoring of the live CTS inward processing pipeline — per-activity throughput, latency percentiles, queue depths, L1 vs L2 cascade model usage.

#### AI Activity Order (Drawee — as implemented)

| # | Activity | Why This Order |
|---|----------|----------------|
| 1a | `get_kill_switch_status` (checkpoint 1) | Resolved fresh, immediately before the Vision LLM call |
| 1 | `detect_alteration` | Vision LLM first — tampered cheques skip all other GPU cycles. Under Kill Complete (KC), Qwen2-VL is bypassed entirely per checkpoint 1's result |
| 2 | `validate_cts2010` | CTS-2010 compliance check before any AI |
| 3 | `check_stop_payment` | Bloom pre-filter → CBS confirm |
| 4 | `lookup_pps` | PPS vault Redis lookup |
| 5 | `verify_signature` | Siamese network vs Redis specimen |
| 6 | `score_fraud` | XGBoost + SHAP |
| 7 | `check_cbs_balance` | CBS (Finacle/BaNCS/FlexCube) |
| 8 | `check_account_status` | Account frozen/closed check |
| 8a | `get_kill_switch_status` (checkpoint 2) | Re-resolved independently of checkpoint 1 — catches an activation that happened mid-flight during the ~120s Vision LLM call, which checkpoint 1 cannot see |
| 9 | `synthesise_decision` | OPA Layer 4 policy gate + kill-switch backstop (checkpoint 2) — forces HUMAN_REVIEW if either is active |
| 10 | `file_to_ngch` → `write_audit` | Exactly-once via NGCHAdapter + Immudb |

> **Note:** step 2 (`validate_cts2010`) is documented here as originally designed but is not currently invoked by the production workflow — a pre-existing gap, not something introduced by the July 2026 filing/audit fix. Flagged for follow-up.

---

## 5. CTS Outward (Presentee) Screens

### 5.1 Scanner

**Route:** `/#/cts/scanner`  
**Access:** `ops_reviewer` (outward scanning role), `ops_manager`

**Purpose:** Physical scanner management. Staff feed deposited cheques; ASTRA file-watcher monitors the drop folder for new TIFF images per scanner OEM.

#### Supported Scanner OEMs

| OEM | Integration Model |
|-----|------------------|
| Digital Check | OEM software writes TIFF to configured drop folder |
| MagTek | Drop folder |
| RDM | Drop folder |
| OPEX | Drop folder |

#### Background Process

1. File watcher detects image → MICR routing prefix validated via CRL service (Redis cache → YugabyteDB on miss)
2. Publishes to `cts.outward.scanned.{bank_id}` → `OutwardScanWorkflow` triggered
3. CTS-2010 compliance check (dimensions, DPI ≥200, colour mode, border clearance)
4. Lot assignment for current clearing session
5. **Vision LLM sanity check (LAST)** — amount/MICR discrepancy → `MismatchResolutionWorkflow` spawned (4-hour resolution window)

**Tables Written:** `cts.outward_clearing_items`, `cts.cheque_image_metadata`, `cts.clearing_batches`, `cts.mismatch_queue` (if held)

#### Success
Instrument accepted into lot. MICR validated. CTS-2010 compliant. Vision LLM confirms amount matches. Status: ACCEPTED.

#### Failure States
- **CTS-2010 Rejection:** `CTS_WF_CTS2010_FAIL` — specific failing check shown in UI. Re-scan required.
- **Amount Mismatch Hold:** Scanner reads ₹25,000, Vision reads ₹15,000 → instrument held. Branch supervisor must GO_AHEAD or REJECT within 4 hours.

---

### 5.2 Image Quality Assessment (IQA)

**Route:** `/#/cts/iqa`  
**Access:** `ops_manager`, `bank_it_admin`, `ml_engineer`

**Purpose:** Displays IQA results for outward cheques. Each instrument runs 16 quality tests before NGCH submission. Results encoded as `BFG:` + 16 codes in CXF XML `UserField` (submitted to NGCH for NPCI image quality auditing).

#### The 16 IQA Tests

| Test # | What Is Checked | Pass (1) | Fail (0) |
|--------|-----------------|----------|----------|
| T01 | Front B/W image not blank | Content present | Blank image |
| T02 | Back B/W image not blank | Content present | Blank image |
| T03 | Front grayscale not blank | Content present | Blank image |
| T04 | Width ≥590px | Compliant | Too narrow |
| T05 | Height ≥250px | Compliant | Too short |
| T06 | DPI ≥200 | Compliant | Under-resolution |
| T07 | Bit depth correct (1bpp B/W) | Correct | Wrong depth |
| T08–T16 | Pixel-level: MICR band clarity, skew, contrast, physical damage, signature area, field readability | Pass | Advisory (2) or Fail |

---

### 5.3 Presentment File

**Route:** `/#/cts/presentment-file`  
**Access:** `ops_manager`, `compliance_officer`, `smb_viewer` (own instruments only for SMB)

**Purpose:** Shows the outward CXF (CTS Exchange File) for current/past clearing sessions. Lot summaries, NGCH submission status, download of presentment file.

#### CXF File Assembly Pipeline (`build_ngch_file` Temporal activity)

1. **IQAEngine** → 16 tests → `BFG:` + 16-char code string in `CXFItem.UserField`
2. **NGCHSigner (MICRDS)** → signs MICR line via HSM (RSA-SHA256 PKCS#1v15, 256 bytes) → 344-char Base64
3. **NGCHSigner (ImageDS)** → signs front B/W image bytes via HSM → 256-byte raw binary
4. **CIBFAssembler** → concatenates `front_bw + back_bw + front_gray`. Embeds ImageDS at offset 512.
5. **CXFBuilder** → assembles all `CXFItem`s into CXF XML (namespace `urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005`)

> **HSM Requirement:** Every outward instrument = exactly 2 HSM calls (MICRDS + ImageDS). 500 instruments = 1,000 HSM calls per batch. FIPS 140-2 Level 3. Private keys never touch Python memory.

---

### 5.4 Endorsement

**Route:** `/#/cts/endorsement`  
**Access:** `ops_manager`, `ops_reviewer` (outward role)

**Purpose:** Batch endorsement stamping. When a lot is sealed, the bank's endorsement stamp is applied to all instruments before NGCH submission.

**Workflow:** `BatchEndorsementWorkflow`  
**Trigger:** `cts.outward.lot.sealed.{bank_id}` Kafka event  
**Activities:** `stamp_endorsement` → `update_lot_status` → `write_audit`  
**Terminal States:** `ENDORSED` (→ triggers NGCHSubmissionWorkflow), `FAILED`  
**Table:** `cts.clearing_batches` (status: SEALED → ENDORSED → SUBMITTED)

---

### 5.5 Session Reconciliation

**Route:** `/#/cts/reconciliation`  
**Access:** `ops_manager`, `compliance_officer`

**Purpose:** End-of-day reconciliation. Fetches NGCH settlement report, matches submitted vs settled, generates RRF (Return Reason File) for returned instruments.

#### RRF Rules (NPCI CTS-2010 Annexure II)
- **Code 99** (CCH-assigned) — drawee bank can NEVER send this. `ForbiddenReturnReasonError` blocks it at the model level.
- **Code 88** (Other) — requires non-empty `ReturnReasonComment`. Validated at model level.
- **Code 00** (On Realization) — only valid for `ClearingType` = 14.
- **RRF Namespace:** `urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004`

#### Success
All instruments matched. RRF generated. Settlement position written to `cts.settlement_positions`. Status: **RECONCILED**.

#### Failure
Some instruments unmatched → `EXCEPTIONS_FLAGGED`. ops_manager + compliance_officer notified. Manual investigation required within 24 hours (RBI requirement).

---

## 6. CTS Vault Screens

### 6.1 Vault Status

**Route:** `/#/cts/vault`  
**Access:** `ops_manager`, `bank_it_admin`

**Purpose:** Health dashboard for CTS Redis vaults. Last sync time, entry counts, hit rates, stale key counts, vault miss counts per session.

#### Signature Vault
- Redis key: `sig:{bank_id}:{hmac_sha256(account_number)}` — never raw account number
- Value: signature vector (Siamese embedding) + MinIO specimen image key
- Full sync: 6AM daily via `VaultSyncWorkflow`
- **Vault miss → always HUMAN_REVIEW (Layer 1 constraint, immutable)**

#### PPS Vault
- Redis key: `pps:{bank_id}:{hmac_sha256(account_number)}:{cheque_series_start}`
- Value: registered amount, payee name (encrypted), validity window
- Delta sync: every 15 minutes (stop-payments + canceled leaf updates)

#### Canceled Leaf Bloom Filter
- Redis key: `bloom:canceled:{bank_id}`
- Checked before any Vision LLM call — Bloom hit → HUMAN_REVIEW immediately (saves ~500ms GPU time)
- False positive rate: <0.1% (acceptable — results in extra human reviews, never auto-confirms)

**Tables:** `cts.signature_vault_entries`, `cts.pps_vault_entries`

---

### 6.2 Vault Sync

**Route:** `/#/cts/vault-sync`  
**Access:** `bank_it_admin`, `ops_manager`

**Purpose:** Manual sync trigger and sync history display. Shows full sync (6AM daily) and delta sync (every 15 minutes) history, entry counts, CBS response times, failures.

| Sync Type | Workflow | Schedule | Data Synced | Fraud Window Closed |
|-----------|----------|----------|-------------|---------------------|
| Full Sync | `VaultSyncWorkflow` | Daily 6AM | All signatures + PPS | 24h (signatures don't change intraday) |
| Delta Sync | `DeltaVaultSyncWorkflow` | Every 15 minutes | Stop-payments + canceled leaves | **15 minutes** |

> **Before delta sync (legacy risk):** A stop-payment filed at 10:05AM would not reach ASTRA until 6AM next day — an 18-hour fraud exposure window. Delta sync closes this to 15 minutes.

**Kafka:** `cts.vault.sync.{bank_id}` (full), `cts.vault.delta.{bank_id}` (delta)

---

## 7. SMB Operations Screens

### 7.1 SMB Dashboard

**Route:** `/#/cts/smb/dashboard`  
**Access:** `smb_admin`, `smb_editor` (own SMB only); `ops_manager` (SB — consolidated view)

**Purpose:** Main operations dashboard for Sub-Member Bank staff. Inward clearing summary, IET countdown, recent decisions, quick links to review queue and reports.

#### Data Isolation (Enforced at Every Layer)
- All API calls include `bank_type=SMB` and `bank_id={smb_id}` from JWT
- Backend RBAC enforces `smb_id` filter on every DB query — SMB cannot see peer SMB data

#### Background Routing
Inward cheques drawn on SMB arrive at SB's NGCH. `SBInwardForwardingWorkflow` routes to correct PU. **Original NGCH `ItemExpiryTime` timestamp preserved** — IET enforcement uses the correct per-item deadline.

---

### 7.2 SMB Review Queue

**Route:** `/#/cts/smb/review-queue`  
**Access:** `smb_admin`, `smb_editor`, `smb_viewer` (read-only); `ops_reviewer` (SB, SMB-scoped)

**Purpose:** Human review queue scoped to a specific SMB. Identical to SB human review queue but filtered to SMB-only instruments. Timeout auto-return notifies both SMB and SB ops_manager.

#### Escalation Routing
When `smb_id` is set on `ChequeWorkflowInput`, `human_review_topic()` routes to the SMB-scoped review topic — not the general SB review topic.

---

### 7.3 SMB Reports

**Route:** `/#/cts/smb/reports`  
**Access:** `smb_admin`, `smb_viewer` (own SMB only); `ops_manager` (all SMBs)

**Purpose:** Three-tab report screen:
- **Daily Summary:** STP confirm/return counts, fraud flags, human review count
- **RRF:** All returned instruments with reason codes for the session
- **Settlement:** SMB's net clearing position

All CSVs scoped to own IFSC — never contain peer SMB data.

**Tables:** `cts.sub_member_batch_ledgers`, `cts.return_items`, `cts.settlement_positions`

---

### 7.4 Agency Command Center

**Route:** `/#/cts/agency-cc`  
**Access:** `ops_manager` (**SB-only gate** — hidden for SMB users)

**Purpose:** Management screen for Agency Banks routing instruments for multiple SMBs through a single SB connection. Shows clearing session state, lot packaging, SB relay status, and SMB CBS push sessions.

#### Three Agency Scenarios

| Scenario | Description | CBS Push? |
|----------|-------------|-----------|
| SB+SMB, SMB has own CBS | SMB CBS pushes CSV to Agency SFTP every 15 min | Yes — `SMBVaultPushIngestWorkflow` |
| Agency+SMB, Agency manages CBS | Agency CC reads CBS directly | No |
| Agency+SMB, SMB has own CBS | Push + Agency CC relay | Yes |

#### SMB CBS Push Architecture
Deliberately chosen over a Go binary at SMB premises — SMBs' existing CBS batch jobs push CSV to Agency SFTP every 15 minutes. Zero new software at SMB. `SMBVaultPushIngestWorkflow` parses (HMAC-SHA256 account hashing, amount bucketing), updates vault, marks session as processed (idempotent by `file_hash UNIQUE`).

**Tables:** `cts.smb_push_sessions`, `cts.pps_vault_entries`, `cts.signature_vault_entries`, `cts.sb_connections`

---

## 8. Branch Portal Screens

### 8.1 Branch Dashboard

**Route:** `/#/branch`  
**Access:** `ops_reviewer` (branch-scoped), `ops_manager`

**Purpose:** Operations dashboard for branch staff managing physical cheque scanning sessions. Active EEH session state, scanner health per PU, scan counts, recent session history.

#### EEH Session
An EEH (End-to-End Handoff) session tracks which PUs are active, instrument count, open/close times, error counts. Real-time scanner alerts via SSE (Server-Sent Events) — no page refresh needed.

**Tables:** `cts.eeh_sessions`, `cts.processing_units`, `cts.scanner_configs`

---

### 8.2 Mismatch Queue

**Route:** `/#/branch/mismatch`  
**Access:** `ops_reviewer` (branch supervisor), `ops_manager`

**Purpose:** Held outward instruments where Vision LLM's amount reading doesn't match the scanner's MICR-derived amount. Branch supervisor resolves: GO_AHEAD or REJECT.

#### Resolution Flow

1. `OutwardScanWorkflow`: scanner reads ₹25,000, Vision reads ₹15,000 → `MismatchResolutionWorkflow` spawned (ABANDON policy)
2. Written to `cts.mismatch_queue` with status HOLD. Branch supervisor notified via SSE.
3. **GO_AHEAD** → Temporal signal → workflow continues with scanner amount
4. **REJECT** → instrument removed from lot, returned to counter
5. **4-hour timeout** → `TIMEOUT_AUTO_REJECTED` → ops_manager notified

---

## 9. Admin & Config Screens

### 9.1 MCP Connection Config

**Route:** `/#/cts/config/mcp-connections`  
**Access:** `bank_it_admin` (SB only)

**Purpose:** Configuration and live testing of all MCP (Model Context Protocol) server connections. **Pre-flight gate — clearing is blocked if any connection is not ACTIVE.**

#### Connection Types

| Type | Purpose | Scoped To |
|------|---------|-----------|
| `SB_CBS` | Sponsor Bank Core Banking (Finacle/BaNCS/FlexCube) | SB only |
| `SMB_CBS` | Sub-Member Bank CBS | Per SMB |
| `SIGNATURE_VAULT` | Redis signature vault cluster | SB |
| `PPS_VAULT` | Redis PPS vault cluster | SB |
| `CANCELLED_LEAF` | Canceled leaf Bloom filter Redis | SB |

#### Pre-Flight Gate Logic
Before any inward cheque is processed: API checks `preflight:{bank_id}` Redis key. `clearing_allowed = True` ONLY when ALL connections are `ACTIVE`. Any single `INACTIVE` connection blocks the entire clearing session.

#### On Test / Sync
- `POST /{id}/test` → live connectivity test → updates status → publishes `platform.config.changed` → workers reload <30s
- `POST /{id}/sync` → triggers manual `DeltaVaultSyncWorkflow`. Workflow ID: `cts-vault-delta-{bank_id}-{yyyymmddhhmm}`

**Security:** `endpoint_url` is masked in ALL API responses — never returned raw.  
**Audit:** Every MCP event (CREATED/UPDATED/DELETED/TESTED_OK/TESTED_FAIL/SYNCED) → Immudb `AuditEvent`.

---

### 9.2 Thresholds Configuration

**Route:** `/#/cts/config/thresholds`  
**Access:** `ops_manager` (maker); `bank_it_admin` (checker)

**Purpose:** Layer 3 threshold management with mandatory maker-checker. Changes take effect within 30 seconds via Kafka hot-reload.

#### Key Thresholds

| Key | Default | Effect |
|-----|---------|--------|
| `stp_auto_confirm_threshold` | 0.92 | Fraud score below this → STP_CONFIRM |
| `human_review_fraud_threshold` | 0.72 | Fraud score above this → HUMAN_REVIEW |
| `high_value_amount_threshold` | ₹5,00,000 | Cheques above this always use L2 vision model |
| `iet_minutes` | 180 | IET clearing window |
| `ai.cascade.l1_confidence_threshold` | 0.85 | L1 result accepted if confidence ≥ this |
| `vault.delta_sync_interval_minutes` | 15 | Delta vault sync frequency |

> **Immutable (Layer 1):** `vault_miss_action` is permanently `HUMAN_REVIEW`. Cannot be changed to `AUTO_RETURN` by any bank through any mechanism.

#### Maker-Checker Flow
1. ops_manager submits change → written as PENDING to `platform.config_policies`
2. bank_it_admin approves/rejects via Admin UI
3. On approval: AuditEvent written to Immudb **before** config changes (not after)
4. Change written to `platform.config` → `platform.config.changed` Kafka event → all workers reload within 30 seconds

---

### 9.3 Pre-Live Smoke Test

**Route:** `/#/admin/smoke-test`  
**Access:** `bank_it_admin` (SB — all 4 entity tabs); `smb_admin` (SMB tab only)

**Purpose:** Entity-scoped pre-live validation suite. Run before go-live or after any upgrade. Results downloadable as JSON for change management tickets (CAB).

#### Test Scopes

| Entity | Tests | What Is Validated |
|--------|-------|-------------------|
| SB (Sponsor Bank) | 8 tests | CBS connection, vault connectivity, NGCH adapter, Redis clusters, Temporal worker health, Kafka producer, Immudb write, mTLS cert validity |
| SMB (Sub-Member Bank) | 4 tests | SMB CBS connection, vault entries present, SFTP push path writable, review queue accessible |
| Branch | 3 tests | Scanner drop folder accessible, EEH session can be opened, SSE stream reachable |
| PU (Processing Unit) | 4 tests | Scanner config valid, MICR prefix table populated, lot creation succeeds, CTS-2010 test image passes |

#### Status Codes
- `PASS` — test succeeded
- `WARN` — advisory (non-blocking, investigate before go-live)
- `FAIL` — hard failure (must resolve before clearing is allowed)
- `SKIP` — not applicable for this entity type

> `all_clear = True` if and only if `fail_count == 0`. WARN count alone does NOT block `all_clear`.

**API:**  
- `GET /v1/admin/smoke-test` — run all tests for caller's entity_type  
- `GET /v1/admin/smoke-test/{test_id}` — single test (403 on entity scope mismatch)

---

### 9.4 User Management

**Route:** `/#/admin/users`  
**Access:** `bank_it_admin` (SB — all users); `smb_admin` (own SMB users only)

**Purpose:** Create/view/edit/deactivate staff accounts. Assign roles and clearing zones. Force-logout active sessions. All actions Immudb-audited.

#### Local Auth Account Rules (`local` connector — for smallest SMBs)
- Password stored as argon2id hash — never plaintext, never reversible
- 5 consecutive failed logins → account locked for 30 minutes
- Lock auto-expires; `bank_it_admin` can unlock manually
- `smb_admin` can manage own SMB's local accounts; `bank_it_admin` manages all

**Tables:** `platform.users`, `platform.user_roles`, `platform.user_sessions`, `platform.local_auth_accounts`

---

### 9.5 Audit Trail

**Route:** Accessible from Admin and Compliance console  
**Access:** `compliance_officer`, `ops_manager` (read-only); `rbi_examiner` (time-scoped to engagement)

**Purpose:** Immutable, cryptographically-verified audit trail backed by Immudb. Every financial operation, AI decision, config change, user access, and NGCH filing is recorded.

#### Immudb Properties
- **Append-only** — records can never be modified or deleted
- **Cryptographic integrity** — Merkle tree hash verified per record
- **HSM-signed** — every AuditEvent signed with bank's HSM private key before writing
- **Collection:** `cts_events` for all CTS operations

#### rbi_examiner Access
Time-limited to the audit engagement period. Enforced by RBAC middleware — not advisory. No extension without `bank_it_admin` granting a new engagement token.

#### Compliance Status
27 RBI IT Framework controls — all **COMPLIANT**.  
Control mapping: `compliance/rbi-it-framework/control-mapping.yaml`

---

## 10. Live Demo Pipeline

**Route:** `/#/cts/demo`  
**Access:** All authenticated roles | **Fully self-contained — no API calls, no backend required**

**Purpose:** Browser-only simulation of the complete CTS pipeline for product demonstrations, bank evaluations, and training. Runs on GitHub Pages without any server infrastructure.

#### Features
- Upload real cheque images or use built-in sample set
- Browser Semaphore limits to 5 concurrent cheques at once
- Deterministic OCR outputs and failure modes per file index
- 5-phase animated pipeline: Scan → Compliance → AI Analysis → NGCH Filing → Settlement
- StageChip grid with pulse animations per activity
- Live event feed (right panel) with real-time log entries
- NPCI view: 4 drawee bank routing cards
- CSV generation via `URL.createObjectURL()` — 4 downloadable reports (no server dependency)

#### Simulated Failure Modes
- **Presentment side:** `AMOUNT_MISMATCH`, `ALTERATION_DETECTED`, `CTS_IMAGE_QUALITY`
- **Drawee side:** `STOP_PAYMENT_ACTIVE`, `SIGNATURE_MISMATCH`, `ACCOUNT_FROZEN`

---

## 11. Reference: Kafka Topics (CTS)

| Topic | Producer | Consumer | Purpose |
|-------|----------|----------|---------|
| `cts.inward.{bank_id}` | NGCH Adapter | CTS Agent Workers (KEDA) | One message per inward cheque → triggers `ChequeProcessingWorkflow` |
| `cts.decisions.{bank_id}` | CTS Agents | Audit Service, Analytics | All filed inward decisions |
| `cts.human.review.{bank_id}` | CTS Agents | Ops Workstation SSE | Human review queue items |
| `cts.vault.sync.{bank_id}` | CBS Connector | `VaultSyncWorkflow` | Full signature + PPS vault updates (6AM daily) |
| `cts.vault.delta.{bank_id}` | Delta Sync Trigger | `DeltaVaultSyncWorkflow` | Stop-payment + canceled leaf delta updates (every 15 min) |
| `cts.outward.scanned.{bank_id}` | Scanner Service | `OutwardScanWorkflow` | Newly scanned outward instruments |
| `cts.outward.lot.sealed.{bank_id}` | Lot Manager | `BatchEndorsementWorkflow` | Lot sealed, ready for endorsement |
| `cts.outward.submitted.{bank_id}` | `NGCHSubmissionWorkflow` | Audit, Analytics | Outward instruments filed to NGCH |
| `cts.smb.inbound.{bank_id}` | SMB Forwarding Worker | `SMBForwardingWorkflow` | Sub-member instruments for sponsor routing |
| `cts.mismatch.{bank_id}.{branch_id}` | `MismatchResolutionWorkflow` | Branch Portal SSE | Vision/scanner amount mismatch holds |
| `cts.sb.relay.outward.{agency_id}.{sb_id}` | `AgencyCCWorkflow` | SB relay receiver | Agency outward lots relayed to Sponsor Bank |
| `cts.sb.relay.inward.{agency_id}.{sb_id}` | Sponsor Bank | `SBInwardForwardingWorkflow` | Inward cheques from SB relay |
| `platform.audit.events` | All CTS services | Immudb Writer | Immutable audit stream |
| `platform.notifications` | All CTS services | Notification Dispatcher | Email + WhatsApp notification triggers |
| `platform.config.changed` | config-service | CTS workers | Layer 3 hot-reload trigger (<30s propagation) |

---

## 12. Reference: Database Tables (CTS)

All CTS tables live in the `cts` schema. Connection via `pgbouncer-cts` (separate from any other module).

| Table | Purpose | PII? | Retention |
|-------|---------|------|-----------|
| `cts.cheque_instruments` | Master cheque record. `payee_name_enc` + `drawer_enc` in pgcrypto BYTEA. `account_hash` only — never raw account number. | Yes (encrypted) | 10 years (WORM) |
| `cts.inward_clearing_items` | Per-cheque inward record; IET deadline (UTC unix); decision; return reason code | No | 7 years |
| `cts.agent_decisions` | All AI scores, SHAP values (JSONB), fraud rationale, cascade level (L1/L2), final decision | No | 7 years |
| `cts.human_review_items` | Escalated items; context_bundle; reviewer identity; resolution timestamp | Ref only | 7 years |
| `cts.ngch_submissions` | Exactly-once NGCH filing. `idempotency_key UNIQUE`. `ngch_transport` column (sftp/rest). | No | 10 years |
| `cts.signature_vault_entries` | Signature specimens: `account_hash` + Siamese embedding vector + MinIO specimen key | account_hash only | 10 years |
| `cts.pps_vault_entries` | Positive pay registrations: encrypted payee, amount range bucket, validity window | Yes (encrypted) | 5 years |
| `cts.smb_push_sessions` | CBS push file ingestion log. `file_hash UNIQUE` — idempotency guard. | No | 3 years |
| `cts.mcp_connection_configs` | MCP server connection parameters. `endpoint_url` never returned in API responses. | No (URL masked) | Active |
| `cts.mismatch_queue` | Held outward instruments pending branch supervisor resolution | No | 90 days |
| `cts.clearing_batches` | Lot lifecycle: OPEN → SEALED → ENDORSED → SUBMITTED | No | 7 years |
| `cts.outward_clearing_items` | Per-instrument outward record; IQA results; CXF item sequence | No | 7 years |
| `cts.eeh_sessions` | Branch scanning session state; scanner health; SSE events | No | 1 year |
| `cts.processing_units` | PU registry — branch mapping, scanner configs, drop folder paths | No | Active |
| `cts.settlement_positions` | Net clearing position per session; RRF summary | No | 10 years |
| `cts.scanner_configs` | Per-scanner OEM config, drop folder, MICR line format | No | Active |
| `cts.branches` | Branch master — mapped to PUs | No | Active |
| `cts.sb_connections` | Sponsor Bank connections for Agency scenarios | No | Active |

### Platform Tables (shared)

| Table | Purpose |
|-------|---------|
| `platform.users` | Bank staff. `display_name_enc` + `email_enc` (pgcrypto). No passwords stored for SAML users. |
| `platform.config` | Live Layer 3 threshold values per bank |
| `platform.config_policies` | Layer 3 threshold change history (maker + checker + timestamp + Immudb ref) |
| `platform.local_auth_accounts` | Local auth accounts: argon2id hash, lockout state, clearing_zones array |
| `platform.audit_events` | Queryable mirror of Immudb events. **Immudb is authoritative — this is a query cache only.** |

---

## 13. Reference: Temporal Workflows (CTS)

All CTS workflows run on task queue `cts-processing-{bank_id}`. Never shared with any other module.

| Workflow | Trigger | Key Activities | Terminal States | IET Safety |
|----------|---------|----------------|-----------------|-----------|
| `ChequeProcessingWorkflow` | Kafka `cts.inward` | detect_alteration → … → file_to_ngch → write_audit | `STP_CONFIRM`, `STP_RETURN`, `HUMAN_REVIEW` | IETWatchdog child (P0, spawned first) |
| `IETWatchdogWorkflow` | Child of ChequeProcessing (ABANDON policy) | monitor_countdown → emergency_file_if_30s_remaining | `SAFE`, `EMERGENCY_FILED` | **This IS the IET safety mechanism** |
| `HumanReviewWorkflow` | HUMAN_REVIEW signal from parent | push_to_queue → wait_for_signal (55 min) → file_to_ngch → write_audit | `REVIEWER_CONFIRMED`, `REVIEWER_RETURNED`, `TIMEOUT_AUTO_RETURNED` | Watchdog runs in parallel |
| `VaultSyncWorkflow` | Temporal schedule (daily 6AM) | load_signatures_from_cbs → load_pps_from_cbs → warm_redis_vault → verify_vault_integrity | `SYNC_COMPLETE` | N/A |
| `DeltaVaultSyncWorkflow` | Temporal schedule (every 15 min) | fetch_delta_stop_payments → fetch_delta_canceled_leaves → update_bloom_filter → write_audit | `VAULT_UPDATED`, `PARSE_FAILED`, `DUPLICATE_SKIPPED` | Closes 18h fraud window → 15 min |
| `OutwardScanWorkflow` | Kafka `cts.outward.scanned` | capture_image → validate_cts2010 → create_lot_entry → vision_sanity_check → write_audit | `ACCEPTED`, `CTS_REJECTED`, `MISMATCH_HELD` | N/A (outward) |
| `MismatchResolutionWorkflow` | Child of OutwardScan (ABANDON policy) | wait_for_signal (4h) → GO_AHEAD / REJECT | `GO_AHEAD`, `REJECTED`, `TIMEOUT_AUTO_REJECTED` | N/A |
| `BatchEndorsementWorkflow` | Kafka `cts.outward.lot.sealed` | stamp_endorsement → update_lot_status → write_audit | `ENDORSED`, `FAILED` | N/A |
| `NGCHSubmissionWorkflow` | Lot endorsed + session open | build_ngch_file → submit_to_ngch → confirm_acknowledgement → write_audit | `SUBMITTED`, `SUBMISSION_FAILED` | Exactly-once (idempotency_key) |
| `SessionReconciliationWorkflow` | Session close | fetch_ngch_settlement_report → match_submitted_vs_settled → generate_rrf → write_audit | `RECONCILED`, `EXCEPTIONS_FLAGGED` | N/A |
| `ClearingSessionWorkflow` | Lot ready + session open | SB_NGCH vs AGENCY_SB_RELAY routing → seal_all_lots | `SESSION_SUBMITTED`, `EMPTY_SESSION` | N/A |
| `AgencyCCWorkflow` | ClearingSessionWorkflow (relay) | build_lot_package → sb_submit → relay_kafka → write_audit | `SUBMITTED_TO_SB`, `SB_REJECTED` | N/A |
| `SBInwardForwardingWorkflow` | Kafka `cts.sb.relay.inward` | CRL per instrument → PU fan-out (original_ngch_ts preserved) | `FORWARDED`, `RETURNED_TO_SMB` | Original IET preserved |
| `SMBForwardingWorkflow` | Kafka `cts.smb.inbound` | validate_smb_instrument → route_to_sponsor_lot → forward_to_ngch → notify_smb → write_audit | `FORWARDED`, `RETURNED_TO_SMB` | N/A |
| `SMBVaultPushIngestWorkflow` | SFTP CSV file detected | parse_smb_push_csv → update_vault_entries → write_audit | `VAULT_UPDATED`, `DUPLICATE_SKIPPED`, `PARSE_FAILED` | N/A |

### Workflow ID Conventions

| Pattern | Example | Guarantees |
|---------|---------|-----------|
| `cts-{bank_id}-{instrument_id}` | `cts-saraswat-coop-INS001234` | Exactly-once per instrument |
| `cts-iet-{bank_id}-{instrument_id}` | `cts-iet-saraswat-coop-INS001234` | Watchdog survives parent crash |
| `cts-humanreview-{bank_id}-{instrument_id}` | `cts-humanreview-saraswat-coop-INS001234` | One review per instrument |
| `cts-vaultsync-{bank_id}-{date}` | `cts-vaultsync-saraswat-coop-20260701` | One full sync per day |
| `cts-vault-delta-{bank_id}-{yyyymmddhhmm}` | `cts-vault-delta-saraswat-coop-202607010945` | One delta per 15-min window |

---

## 14. Reference: Notification Messages (CTS)

All messages live in `shared/messages/locales/messages.yaml` — single source of truth.  
Run `python -m shared.messages.build` to push to Redis and regenerate browser bundles.

| Key | Severity | Surface | Recipient |
|-----|----------|---------|-----------|
| `CTS_WF_ALTERATION_DETECTED` | ERROR | UI, AUDIT, NOTIFICATION | fraud_analyst, ops_manager |
| `CTS_WF_ALTERATION_SUSPECTED` | WARN | UI, AUDIT, NOTIFICATION | fraud_analyst |
| `CTS_WF_OCR_AMOUNT_MISMATCH` | ERROR | UI, AUDIT, NOTIFICATION | ops_reviewer, ops_manager |
| `CTS_WF_VAULT_MISS` | WARN | UI, AUDIT, NOTIFICATION | ops_reviewer (zone-scoped) |
| `CTS_WF_CBS_ACCOUNT_FROZEN` | CRITICAL | UI, AUDIT, NOTIFICATION | ops_manager, fraud_analyst |
| `CTS_WF_CBS_UNREACHABLE_DEGRADED` | WARN | UI, AUDIT, NOTIFICATION | ops_manager, bank_it_admin |
| `CTS_NGCH_IET_IMMINENT` | CRITICAL | UI, AUDIT, NOTIFICATION | ops_manager (**P0 — never debounced**) |
| `CTS_WF_PPS_AMOUNT_MISMATCH` | ERROR | UI, AUDIT, NOTIFICATION | fraud_analyst, ops_manager |
| `CTS_WF_FRAUD_HIGH_RISK` | ERROR | UI, AUDIT, NOTIFICATION | fraud_analyst, ops_manager |
| `CTS_WF_HUMAN_REVIEW_TIMEOUT` | ERROR | UI, AUDIT, NOTIFICATION | ops_manager |
| `CTS_WF_CTS2010_FAIL` | ERROR | UI, AUDIT, NOTIFICATION | ops_reviewer (outward) |
| `CTS_SMB_HUMAN_REVIEW_ASSIGNED` | INFO | UI, NOTIFICATION | smb_editor (zone-scoped) |
| `CTS_SMB_DECISION_FILED` | INFO | UI, NOTIFICATION | smb_admin |
| `CTS_SMB_SETTLEMENT_AVAILABLE` | INFO | UI, NOTIFICATION | smb_admin |
| `AUTH_LDAP_SERVER_UNREACHABLE` | CRITICAL | UI, AUDIT, NOTIFICATION | bank_it_admin |
| `AUTH_LOCAL_ACCOUNT_LOCKED` | ERROR | UI, AUDIT | bank_it_admin |

### Notification Debouncer
`NotificationDebouncer` (Redis sorted-set, 60-second window per `(bank_id, smb_id, event_category)`) prevents alert floods:
- ≥10 similar notifications in 60 seconds → suppress individual alerts → emit one batch summary with count + severity + dashboard link
- **P0 events (IET breach, kill switch) are NEVER debounced — always immediate**

---

*ASTRA Platform User Manual v1.0 — CTS Module — Confidential — Banking Grade*  
*Author: Nilesh Shah (Ex-NPCI · Piramal · Fullerton/SMFG) | July 2026*
