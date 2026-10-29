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

### 2.6 Policy Engine — In-Process, No OPA Container by Default

**Decision (2026-09-21):** The OPA container is dropped from the mandatory stack (same CAB/image-approval reasoning as §2.5). Layer 4 business-policy rules are evaluated in-process by `shared/policy_engine.py` (`PolicyEngine.decide(OPAInput) → OPAResult`, same contract as `OPAClient`). Rules are Layer 3 config data — JSON under `cts.policy_rules` in `platform.config_values` — so they hot-reload via config_service (30 s), are audited, and go through maker-checker. Defaults are ported from the former `cts_routing.rego` triggers.

**Structural safety invariants:** a rule can only yield `HUMAN_REVIEW` or `AUTO_RETURN` (never a confirm) · `HUMAN_REVIEW` beats `AUTO_RETURN` · rules unavailable/malformed → `HUMAN_REVIEW` · no match → `PROCEED` (downstream gates still apply).

**External OPA remains optional:** a bank that already runs OPA may set the `opa.url` platform value and the worker will use `OPAClient` instead. The `.rego` files stay as the reference for that path.

### 2.7 IndicOCR Sidecar — PaddleOCR Was Never Installed (fixed 2026-09-22); Handwritten Accuracy Is Open

**Found on a real run (2026-09-22):** `apps/indic_ocr` (the Stage 2 Indic OCR sidecar) had no `requirements.txt` and no Dockerfile — it only ever ran from a hand-assembled local `.venv`, so `paddlepaddle`/`paddleocr` (the primary multi-script engine the whole service exists for) were never installed anywhere. Every real Indic OCR call in dev fell back to Tesseract, confirmed live by `indic_ocr.backend_failed_cascading backend=paddle error='PaddleOCR not installed.'` on every request.

**Fixed:** `apps/indic_ocr/requirements.txt` + `Dockerfile` added. Install is two steps (see the requirements.txt header comment for why): `pip install -r requirements.txt` then `pip install --force-reinstall --no-deps "opencv-contrib-python>=4.9,<5"` — paddleocr 2.7.3 pins an opencv build that predates NumPy 2.0 and crashes on import; a single-pass install leaves three conflicting `cv2` packages on disk. Verified from a clean venv, and against the real `tests/integration/test_indic_ocr_real_service.py` suite (7/7 passing against the live restarted service, not mocked).

**Handwritten Indic accuracy — partially improved, not solved (2026-09-22):** PaddleOCR's and Tesseract's stock models are both trained on printed text. Tested live against a real handwritten Kannada payee name (from an actual KBL cheque): PaddleOCR returned `"YPhg be ?"` (wrong), Tesseract returned empty text, both near-zero genuine confidence.

Added a third tier: `_cloud_vlm_refine_zone()` in `modules/cts/workflows/activities/ocr.py` retries a zone against the cloud vision-LLM fallback (already used for Stage 1, same `cts.allow_cloud_ai_fallback` opt-in gate, off by default) when IndicOCR's own result doesn't clear `indic_min_confidence`. Tested live on the same real crop: correctly read `ಸುಮತಿ ಶೇಟ್ಟಿ` ("Sumati Shetty") on one call — a real improvement over both classical engines.

**But this is not reliable, and must never be treated as authoritative:** repeat live calls on the same illegible crop also produced fluent, self-confident (0.9+) Devanagari text with no relation to the actual (Kannada) image — a confident hallucination, not a low-confidence miss. `_cloud_vlm_refine_zone()` caps whatever confidence the model reports at `_CLOUD_VLM_INDIC_CONFIDENCE_CAP = 0.65`, well under any realistic `min_confidence` gate, so a cloud-VLM-sourced reading can never look like a trusted high-confidence extraction and always still needs the same human-review path a genuine low-confidence result gets (test: `test_cloud_vlm_reading_confidence_is_capped_never_trusted_at_face_value`). Treat this as a best-effort assist that sometimes gets a handwritten Indic name right, not a fix for handwriting OCR — human review remains the real safety net for these fields, same as any other low-confidence OCR outcome.

**Resolution vs. model-choice, tested and ruled on (2026-09-22):** full evidence in [docs/indic-ocr-handwriting-evidence.md](docs/indic-ocr-handwriting-evidence.md). Short version: interpolating a low-DPI photo up to 200-DPI pixel count does not help (still wrong, both local and cloud engines) — but the same engines read Devanagari correctly at ~1.0 confidence on clean text rendered at genuine 200 DPI, so the failure is handwriting-stroke ambiguity, not missing script support. Newer models (Qwen3-VL-8B/32B, and Qwen2.5-VL-72B again) were tested against 3 real Devanagari cheques with eye-verified ground truth: 0/3 correct across every model tried. Gemma 4 31B and Qwen3.8-27B are real, recent models but have no inference provider currently serving them — not tested, not claimed. A genuine 200-DPI scanner capture (not a photo, not an upscale) remains the one untested, credible next lever.

### 2.8 STP Multisignal Rescue — Don't Hard-Gate on OCR Confidence Alone (2026-09-23)

**Decision:** `cheque_workflow.py` no longer hard-exits to `HUMAN_REVIEW` the instant OCR confidence is low
on payee or amount_words specifically — it defers to `synthesise_decision`'s existing multi-signal gate
(fraud + OCR + signature + CBS + PPS together) instead, as long as `inp.account_number` (the account already
known from presentment metadata) is non-empty. `date` and `amount_figures` weakness still exits immediately —
both feed `decision.py`'s hard auto-return gates, where a wrong OCR reading could file an incorrect
`STP_RETURN`. See `modules/cts/workflows/cheque_workflow.py`'s `_MULTISIGNAL_RESCUE_FIELDS` for the exact
scope and reasoning. Bank-configurable: `cts.ocr_multisignal_rescue_enabled` (Layer 3, default `True`,
hot-reload).

**Corrected 2026-09-24:** the gate originally checked an OCR/MICR-derived `account_number_last4` instead of
`inp.account_number`. Real Indian CTS-2010 MICR carries no account number field at all (see §2.9) — that
made the gate structurally unsatisfiable on every real cheque, so the rescue never fired live until this was
found and fixed. [docs/e2e-test-evidence.md](docs/e2e-test-evidence.md)'s 2026-09-24 entry has the full
finding and the first genuine, verified live `STP_CONFIRM` result on real 200-DPI scans (6/10) once fixed.

**Revised 2026-10-13 (bank owner): rescue now defaults to OFF.** An unreadable payee or amount-in-words is called
unequivocally — `HUMAN_REVIEW` — and can no longer continue through the pipeline to `STP_CONFIRM`.
`cts.ocr_multisignal_rescue_enabled` still exists (Layer 3) and a bank may explicitly set it `True`; a payee on
which the two reads disagree (`payee_reread_status=DISAGREE`) is never rescued even then. Related: handwritten cheque
payees are read twice and withheld on disagreement (`_payee_reread`, `cts.payee_reread_min_similarity`, default 0.99).

### 2.9 MICR Never Carries an Account Number (corrected 2026-09-24)

**The real Indian CTS-2010 MICR band is cheque number (6 digits) + city-bank-branch sort code (9 digits),
full stop** — no account number field. `modules/cts/scanner/micr.py`'s `MICRParser.parse_ocr_text()` wrongly
assumed a 23-digit layout with a fabricated 6-digit account segment between the sort code and the
transaction code since the file was first written (2026-09-18) — confirmed wrong from a real, already-working
outward digest showing `MICR Format` (9 digits, standalone) and a *separately* OCR'd `Account Format` field
side by side. The account number is a real, independent field printed on the cheque face, extracted by
asking the vision model for it directly (`account_number` in `_OCR_PROMPT`, reusing the wording already
proven in `apps/api/routers/demo_cloud_extract.py`'s `CLOUD_EXTRACT_PROMPT` for outward) — never guessed out
of MICR digit positions. Any code that needs "the account number for this cheque" should use
`inp.account_number` (known from presentment metadata) for inward, or the real OCR'd `account_number` field
for cross-validation — never derive it from `micr_line`.

### 2.10 Inward Drawee Name — From CBS Account Lookup, Stored Plain (2026-10-13)

**Decision (bank owner):** the inward reviewer's **Drawee Name** comes from the bank's own account record
(CBS `get_account_info(account_number).holder_name`), never from OCR of the cheque face. It is stored as
**plain text** in `cts.inward_drawee_name` (migration `20261013_030`) — an explicit, narrow exemption from the
column-encryption/masking rules in `pii-data-protection.md`, for this one field only; account numbers stay
hashed + last-4 and amounts stay bucketed. Written by the best-effort `record_drawee_name` activity, run
before OCR so even an OCR-low-confidence review has the name; the name is deliberately **not** returned in the
activity result (Temporal history). A failed lookup degrades to "no name" and never changes the decision.
Surfaced as `drawee_name` on the inward queue and decision-log API rows and in the review UI. Outward Payee
Name (front OCR + back endorsement + deposit-slip account → vault) is separate and not yet built.

### 2.12 No Zone Concept - Branch Maps to a Processing Unit (2026-10-29, bank owner)

A bank files to a **single NGCH grid** today, and a bank may have **one or more processing units (PUs)**. A branch maps to exactly one PU
(`branches.pu_id`) - that is the whole model; there are **no clearing zones**. A PU is a group of branches handled together (its own Temporal
queue and Kafka inward topic), not a grid. Done: the one-PU-per-zone index is gone and `clearing_zone` / `ngch_participant_code` are optional
on a PU (migration `20261029_034`); reviewers are scoped to PUs (`UserContext.pu_ids`, JWT claim `pu_ids`, `local_auth_accounts.pu_ids`) and
allocation scopes by `pu_id` (`pu_allows`, item meta `pu_id`, `reviewer-pus:` Redis key); the RRF and CRL no longer carry a zone (NPCI's
specifications in `docs/npci/source/` define no zone element - checked); day-end sealing files every PU's lots under the one bank-default
centre; MICR routing rules and the NGCH routing screen have no zone; no screen shows a zone (a test fails the build if one does). **Retired (2026-10-29):** the RPC consolidation page, its route and nav entry, and `GET /v1/cts/rpc/zones` (a removal agreed with the bank
owner; the API was never released to a bank, so no `/v2` was needed). **Kept on purpose:** the tables `cts.clearing_zones` /
`processing_centers` / `rpc_zones` and the deprecated unused columns (`processing_units.clearing_zone`, `local_auth_accounts.clearing_zones`,
`cheque_instruments.clearing_zone`, `micr_routing_rules.clearing_zone`) - `cts.clearing_sessions` still has foreign keys to the zone and centre
tables (day-end sealing uses one DEFAULT row), so dropping them is a separate migration once sessions stop referencing them, and columns are
dropped by the rename-keep-drop pattern in the database rules.

**Outward (2026-10-29):** the session cut-off is bank configuration (`cts.outward_session_cutoffs`, a list of local "HH:MM", default 14:30;
`outward_session_timezone`; `modules/cts/outward_sessions.py`) and drives allocation urgency, filing of staged decisions
`outward_cutoff_guard_minutes` before the cut-off, and the checker timeout. Outward items carry their branch's PU in the allocation record.
Who may make a decision is `cts.outward_maker_scope` = CENTRAL (default) | BRANCH | BRANCH_FIRST (+ `outward_branch_first_fallback_minutes`),
and who may check is `outward_checker_scope` = ANY | CENTRAL (`modules/cts/outward_scope.py`); a user is branch staff when assigned branches
(`branch_ids`, set in User Management) and central staff when not. Outward buckets, the Allocation panel rows and the original-instrument custody register (branch first, then central storage) are built.

### 2.11 Inward Safety Gates Added After Real-Image Testing (2026-10-13)

Found by running 70 real KBL instruments (Lots 1, 2, 3) end to end; each has tests and, where stated, a live check.
Evidence: [docs/evaluation/inward_evaluation.md](docs/evaluation/inward_evaluation.md),
[docs/npci/inward-conformance-matrix.md](docs/npci/inward-conformance-matrix.md).

- **Duplicate presentment was silently ignored** (the workflow looked for the error name in the wrapper's text;
  Temporal keeps it in the cause chain), and once detected the return path called `finalise()` before it existed.
  Fixed; the leaf vault is idempotent per instrument id. Verified live.
- **`finalise()` is the single exit and reads state set later in the run.** Any such variable must be initialised
  with the others at the top of `run()` (`_instrument_category` was not, so every pre-OCR exit lost its row).
- **An untrained signature verifier never supports an automatic confirm.** Measured: the generic ImageNet embedder
  accepts 53% of impostor pairs at 0.85. `verifier_trained` flows from the embedder to `synthesise_decision`
  (`cts.require_trained_signature_verifier`, default true).
- **A single model read is never enough to return or to show a handwritten name.** Payees are read twice by two
  different models and withheld on disagreement; dates decades from today and "signature absent" go to human
  review instead of an automatic return (`cts.date_implausible_*`, `cts.signature_absent_action`); the amount on the
  image must match the presented amount; the MICR number must match the presented number; the sort code must be in
  the bank's branch master when one is configured (`cts.micr_branch_master`).
- **Image quality (RRC 39)** is a deterministic, calibrated pre-OCR check (`check_image_quality`, `cts.iqa_*`).
- **Unreadable payee / amount-in-words is human review.** The multisignal rescue is OFF by default, including at the
  `config_service` default every workflow reads.
- **Fraud scoring runs on every exit**, including early ones, and uses the loaded model's declared feature names.
  The model in dev is a labelled synthetic stand-in; the path to a real one is
  [docs/fraud/labelled-data-contract.md](docs/fraud/labelled-data-contract.md) and `scripts/train_fraud_model.py`.
- **After the IET watchdog files its emergency decision, the pipeline stands down** (watchdog signals the parent).
- **Evaluation standard:** `scripts/eval_inward.py` scores results against the section 12 targets with 95%
  intervals and states how many labelled samples are needed to prove a target. Nothing is described as meeting a
  target unless the interval clears it.
- **Open policy question (compliance officer):** codes 30/31/32/55 are treated as "customer not at fault" although
  Annexure II does not list them (pinned in `test_npci_return_codes_conformance.py`).
- **Primary NPCI/RBI documents are in `docs/npci/source/` and the return-code list is verified against them** (CTS Specifications for Continuous Clearing, Rev 3.0 (26 Mar 2025),
  Chennai guidelines v2.1). That check found the return-file code table (`rrf/models.py`) used
  invented codes; it is fixed and pinned by `test_rrf_codes_conformance.py`. Annexure II (customer fault) and the
  continuous-clearing timings are still not in the primary set.
- **MICR number, sort code and amount are read twice by different models**; a disagreement goes to review with both
  readings (`_field_rereads`, `cts.field_reread_model`). Measured on 70 real instruments it exposed 3/3 wrong
  cheque numbers, 4/4 wrong sort codes and 4/5 wrong amounts at the cost of ~1 correct read in 8.
- **A failed or timed-out OCR must never fail the workflow** (it files nothing; near the IET deadline the watchdog
  then deems the item approved). It degrades to `HUMAN_REVIEW` (`ocr_activity_failed`); the OCR budget is
  `ocr_activity_timeout_seconds` (default 120). Verified under a total cloud-model outage (402, no credits):
  all 70 instruments went to human review, none failed, none was confirmed or returned automatically.
- **CIIF (PPS issue file) loads into the PPS vault** via `process_ciif` / `POST /v1/cts/vault/upload/pps/ciif`. The spec does not say whether
  Amount is rupees or paise, so `cts.ciif_amount_unit` is required with no default (refused when unset). Vault amounts convert via
  Decimal (the old float conversion turned 0.29 into 28 paise).
- **Human-review allocation (2026-10-28).** SELF / HYBRID / AUTO modes were unreachable: `get_cts_config()` returned only seven dotted keys
  and `app.state.config_service` was never set, so every router and the consumer saw the SELF default. Both fixed (guard test
  `tests/apps/api/test_main_config_wiring.py`). Auto-assignment is now least-loaded with a per-reviewer cap (urgent items, within
  `allocation_urgent_margin_minutes` of their IET, ignore the cap), scoped to the reviewer's clearing zone, retried when nobody is
  free, and rebalanced when someone new logs in; a reviewer opening an item pins it, and admin assign/reassign
  (`POST /v1/cts/admin/review/{id}/assign`) is pinned and audited. Claims are atomic (`SET NX`; the old read-then-write let two
  reviewers both win). Open: nothing sets an inward item's `clearing_zone` yet, so zone scoping is enforced only for items that carry
  one (zone-less items go to anyone); `AuditEvent` has no `user_id` field, so the actor must be in the payload.
- **Review buckets and the SIP hold (2026-10-28, bank owner's design).** Nine buckets: HVC, CA, IP, LVC, FCC, SIP_SUCCESS, SIP_REJECT,
  HR, MISC (`modules/cts/buckets.py`). A cheque that needs a human is classed by kind in the admin's `bucket_priority` order, else HR;
  a system-decided cheque is SIP_SUCCESS or SIP_REJECT. Admins connect reviewers to buckets (`cts.reviewer_bucket_subscriptions`,
  `PUT /v1/cts/admin/reviewers/{id}/buckets`); a reviewer works only those buckets plus MISC, which is self-claim only and receives
  every de-allocated item and any item with no logged-in subscriber for `bucket_overflow_after_minutes` (it keeps `origin_bucket`).
  Auto-assign, claim, admin assign and rebalance all stay inside the bucket. **SIP hold:** when routing is on and a reviewer connected
  to the SIP bucket is logged in, the system decision is held for them (`sip_review_timeout_minutes`, one bank-wide value); a reviewer
  may confirm or overrule, and on timeout the SYSTEM decision is filed (never the human-review auto-return). Never held when too close
  to the IET (`sip_iet_guard_minutes`), for sub-member cheques, or on any failure. Everything is off until `cts.bucket_routing_enabled`.
  Open: real CBS adapters do not yet fill `AccountInfo.account_type`, so CA/IP rely on the bank's account lists
  (`cts.bucket_account_lists`) until each adapter maps its scheme codes; an admin screen for those lists is not built.
- **Maker-checker (2026-10-28).** `cts.maker_checker_enabled` (off by default): a reviewer's first decision (the maker's) is not filed; the item moves to
  the `VAL` bucket and a different person confirms or overrules it (`POST /v1/cts/review/{id}/validate`; the maker is refused at claim, assign and
  validate). No checker within `checker_review_timeout_minutes` files the maker's decision (never past the IET guard). Outward held items use
  `cts.outward_review_stage` and `/outward/review/{id}/validate`. Outward held items share the inward allocation locks and heartbeat pool
  (no buckets): a reviewer holds an item while deciding, AUTO mode assigns on queue poll (HYBRID does not), the maker's decision releases it for a
  checker (never the maker), and a staged decision no checker takes within `checker_review_timeout_minutes` is filed on the maker's word when the
  validation queue is next read (outward has no workflow to time out). Found by the first live 4-user run
  ([report](docs/reports/ASTRA_4User_MakerChecker_E2E_2026-10-28.md), kept untracked): approved admin settings had never been applied, and the reviewer
  queue had always been empty on a real Temporal (it used a search attribute nothing set) - both fixed.
- **Custody of original instruments (2026-10-29).** Accepted outward originals stay at the branch, are handed over in a batch (courier
  reference), are received at central storage by a *different* person (items not in the box become MISSING and the batch a DISCREPANCY),
  are kept to `cts.custody_retention_years`, then disposed of by a manager only after retention ends. `cts.custody_branch_hold_days` flags
  late handovers. Tables `cts.instrument_custody`, `cts.custody_handovers`, append-only `cts.custody_events` (migration `20261029_036`);
  rows are registered lazily from accepted `outward_scan_events`, no workflow hook. Router `cts_custody.py`, screen `CTSCustody.jsx`
  (`/cts/outward/custody`). Open: the 10-year default is a placeholder to confirm with the bank; no per-SMB scoping yet.
- **Never `git add` a whole directory under `docs/`.** Real customer instruments live untracked under
  `docs/cheques/KBL/` and are now ignored; a broad add once pushed 221 of them (history rewritten).

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
| OCR — Stage 1 | GOT-OCR2.0 (MICR, handwriting, all fields) → `cts-ocr` queue |
| OCR — Stage 2 (Indic) | IndicOCR (`apps/indic_ocr`) — cascades PaddleOCR 2.7.3 (devanagari/tamil/telugu/kannada; needs `apps/indic_ocr/requirements.txt` install — see §2.7) → Tesseract 5 + tessdata_fast (covers bengali/gurmukhi/gujarati/odia/malayalam, plus the paddle fallback for the other four) → EasyOCR → CPU sidecar, port 8021 · kill switch: `cts.indic_ocr.kill_mode` (KP/KC) · triggered when Indic script detected in Stage 1 · **printed text only — neither backend reliably reads handwritten Indic script yet, open item, see §2.7** |
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
| Policy Engine | In-process `PolicyEngine` (rules = Layer 3 config; §2.6). External OPA optional via `opa.url` |
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
| ops_reviewer | CTS human queue | Own processing unit(s) only | None |
| fraud_analyst | CTS analytics | Scores + SHAP, no PII | None |
| ops_manager | CTS full | Cross-zone reports | Layer 3 |
| bank_it_admin | Admin console | Infrastructure only | Layer 2 (maker-checker) |
| compliance_officer | Audit + reports | Read-only audit trail | None |
| rbi_examiner | Audit only (time-scoped) | Read-only, date-scoped | None |
| ml_engineer | AI server + MLflow | Inference logs, no customer data | None |

ABAC on top: `ops_reviewer` scoped to processing units (`pu_ids`); all roles scoped to `bank_id`.

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

**Completed:** Phases 1–15. Full phase-by-phase history: [docs/build-history.md](docs/build-history.md)

**Live-code E2E test evidence:** [docs/e2e-test-evidence.md](docs/e2e-test-evidence.md) — dated, append-only record of what was actually run against a real worker + real infra (last entry 2026-09-21 19:36 IST), the stand-ins used, raw result files in `docs/evidence/`, and an explicit **NOT covered** list. Do not describe any pipeline as "fully E2E tested" unless a new entry there says so with evidence. The pytest suite uses fake activities and is not a substitute.

**Immediate Next (priority order):**
1. **Pilot bank deployment** — validate `saraswat-coop` Helm values against real K8s cluster
2. **NPCI API Modernisation Phase A** — trigger: NPCI concept note acceptance; see [docs/npci-readiness-plan.md](docs/npci-readiness-plan.md)
3. **Security hardening** — OWASP ZAP + pen test prep

**Open security findings:** All code-level findings closed as of `4b9a3e1` (2026-08-18). Closed in this sprint: token revocation JTI blocklist, login rate limiting, SSRF in MCP endpoint_url, FastAPI 422 schema disclosure, IDOR (403→404 on cross-bank schedule and cross-SMB MCP connection access). See `docs/astra-vapt-security-architecture.html` for the architecture reference package (DFD, network topology, threat model, port matrix).

**Remaining VAPT blockers (non-code):**
- Staging/pre-prod K8s environment (pilot bank deploy prerequisite)
- CERT-In empanelled vendor (discussions initiated)
- Internal OWASP ZAP pre-scan on live staging environment
- Sanitised test data (cheque images, accounts)

---

## 15. NPCI API Modernisation

> Full plan: [docs/npci-readiness-plan.md](docs/npci-readiness-plan.md) · Trigger: NPCI accepts concept note in `docs/NPCI-CTS-Modernisation-ConceptNote.html`

Phases: A (REST API, 6 months) → B (Webhook push, 12 months) → C (MCP client, 24 months). ~70% of internal plumbing ready; gap is entirely in NPCI-facing transport layer.

*Last updated: 2026-08-17 | All architectural decisions final unless explicitly revised in this file*
