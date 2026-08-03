# ASTRA Build History — Phase-by-Phase Detail

> This file is the complete build log. CLAUDE.md carries only the summary + Immediate Next list.
> Update this file when phases complete; update CLAUDE.md's "Immediate Next" list as priorities shift.

---

## Completed Phases

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
```

---

## PHASE 5 — Hardening (in progress, July 2026)

Planned items still open:
- [ ] Active-active DR drills
- [ ] Performance test: 500 cheques in < 600ms (benchmark exists, needs staging)
- [ ] Security: penetration test prep (OWASP ZAP)
- [ ] Bank onboarding: first pilot bank Helm deploy against real K8s

Completed hardening items (shipped via Phases 5/6 and Gemini fixes — see also docs/gemini-evaluation.md):
- [x] Fix A: AI cascade (L1/L2) — shared/ai/model_cascade.py + alteration.py + ocr.py — 13 tests
- [x] Fix B: Delta vault sync (15-min) + Bloom filter — DeltaVaultSyncWorkflow — 17 tests
- [x] Fix C: HA/DR Helm values — YugabyteDB RF=3, Kafka min.insync=2, Temporal warm-DR, Redis active-passive
- [x] Fix D: EJ integrity activity (9th step EJNormalisationWorkflow) + reconciliation orphan scanner
- [x] Fix E: Notification debouncer — shared/notifications/debouncer.py, P0 bypass, 60s window
- [x] RBI IT Framework control mapping — 27 controls, all COMPLIANT
- [x] Chaos Mesh YAMLs — infra/chaos-mesh/ (4 scenarios, 10 manifests, quarterly drill schedule)
- [x] Pilot bank Helm values — infra/helm/values/banks/saraswat-coop/ (platform.yaml + cts.yaml)
- [x] Live Demo Pipeline — CTSDemoPipeline.jsx (pure frontend, no backend needed) — 37 tests
- [x] MCP Connection Config API + UI — 8 routes, 5 connection types, pre-flight gate, 60 tests

---

## PHASE 6 — Multi-Scenario CTS Presentment (July 2026, COMPLETE)

Three deployment scenarios: SB+SMB own CBS (push), Agency+SMB Agency-managed CBS, Agency+SMB SMB own CBS (relay).
Architecture decisions: ProcessingUnit as first-class entity; Vision LLM LAST for presentment, FIRST for drawee;
drop-folder scanner model; SMB CBS push via SFTP CSV (no Go binary at SMB).

- [x] Phase 1 — Foundation (commit 0f0443f): scenario plan HTML, ScannerDropFolderMapper (4 OEMs, 30 tests),
      9 Alembic migrations (processing_units, branches, sb_connections, etc.), CRLService (22 tests)
- [x] Phase 2 — EEH/IEH + Branch Portal UI (commits f8c15df → c950597):
      EEH Session Manager, SSE publisher, gRPC servicer, Branch Portal UI (4 pages), Helm chart v0.2.0
- [x] Phase 3 — Presentment Fix: Vision LAST + Mismatch Queue (commit 034f0a9):
      OutwardScanWorkflow reordered, MismatchResolutionWorkflow (4-hour timeout), 39 tests
- [x] Phase 4 — Drawee Fix: Vision FIRST + CBS LAST + SMB Human Review (commits 3886d38, 1c173b6, f71c74b):
      ChequeProcessingWorkflow reordered, smb-scoped human_review_topic(), CTSSMBReviewQueue.jsx, 21 tests
- [x] Phase 5 — SMB Portal (commits fcd2b75, 5d13e37, 8617a39):
      CTSSMBDashboard.jsx, CTSSMBReports.jsx, row-level isolation, 3 SMB RBAC roles, 5 tests
- [x] Phase 6 — Agency Command Center (commit 3c012bc):
      shared/sb_connector/ (4 connectors, 35 tests), ClearingSessionWorkflow, AgencyCCWorkflow,
      SBInwardForwardingWorkflow, CTSAgencyCC.jsx, 8 CTS_CC_* message keys (262 total)
- [x] Phase 7 — SMB CBS Push Ingestion (commit 7d7c8bf):
      ARCHITECTURE CHANGE: Go binary at SMB dropped → CSV push via Agency SFTP every 15 min
      modules/cts/smb_ingest/ (models + parser), SMBVaultPushWorkflow, 52 tests
- [x] Phase 8 — Hardening (commit 930d1f9):
      E2E harness (19 tests, 3 scenarios), performance benchmark, Chaos Mesh scenarios 05-07

---

## PHASE 7 — Pluggable Auth Connector (July 2026, COMPLETE)

Entity-level auth config: SB → SAML, branch → LDAP/AD, PU → LDAP/AD, SMB → local (or per-SMB override).

- [x] shared/auth/connectors/: base.py (ASTRAIdentity, AuthConnector ABC), local.py (argon2id, lockout),
      ldap_ad.py (LDAPS-only enforced, memberOf → role_map), saml.py (assertion parse, no password stored),
      factory.py (entity-level routing, connector caching, ConfigError on bad config)
- [x] shared/auth/exceptions.py — AuthenticationError, AccountLockedError, LDAPServerUnreachableError, etc.
- [x] infra/migrations/platform/20260705_add_local_auth_accounts.py — full schema
- [x] messages.yaml: 21 new AUTH_*/TOTP_* keys (287 total)
- [x] saraswat-coop/platform.yaml: auth: section (SB=saml, branch=ldap_ad, smb=local)
- [x] 40 tests GREEN (base 7, local 11, ldap_ad 12, factory 10)

---

## PHASE 8 — Pre-Live Smoke Test Suite (July 2026, COMPLETE)

- [x] apps/api/routers/admin_smoke_test.py — entity-scoped test runners (SB:8, SMB:4, branch:3, PU:4),
      SmokeTestStatus (PASS/WARN/FAIL/SKIP), 10 tests
- [x] CTSSmokeTest.jsx at /admin/smoke-test — animated sequential run, left-stripe colour encoding,
      download JSON report, dual-themed, sbOnly gate on entity tabs

---

## PHASE 9 — Pre-Pilot Security Remediation (July 2026)

White-box pentest 2026-07-11. Three CRITICAL blockers found: ASTRA-01 (forgeable test-token auth backdoor),
ASTRA-02 (ChequeProcessingWorkflow never filed to NGCH/audit on real entry point),
ASTRA-03 (unawaited async config_service.get("env") → env gate always true).

- [x] ASTRA-01 CLOSED for 9/10 routers (commit b726e29): cts, msv, admin, users, audit, disputes,
      batch, notifications, mcp_connections now use require_user_context (httpOnly cookie +
      AuthenticationMiddleware). ej.py deliberately deferred.
- [x] ASTRA-02 CLOSED (commit c145e5c): ChequeProcessingWorkflow.run(), IETWatchdogWorkflow,
      HumanReviewWorkflow all have working Temporal wiring. HumanReviewWorkflow added from scratch.
      IETWatchdogWorkflow emergency-fire uses real decision via signals, not hardcoded CONFIRM.
      synthesise_decision args bug fixed. kill_switch_lookup.py new activity (both checkpoints).
      First real WorkflowEnvironment tests in the project.
- [x] ASTRA-03 CLOSED: config_service.get("env") (async, never awaited) → synchronous get_platform("env").
      CORS origin hardcode also replaced with get_platform().
- [x] Worker un-awaited async bug FIXED: modules/cts/worker.py + modules/ej/worker.py both
      switched to get_platform() for Temporal address/namespace.

Still open:
- [ ] ej.py ASTRA-01 backdoor (deferred)
- [ ] HumanReviewWorkflow 55-min timeout is a flat constant, not tied to per-instrument iet_deadline
- [ ] SMB notify/ledger side effects in run_with_mocks() never called from real run() (ASTRA-02 shape)
- [ ] RBAC fail-closed defaults (rbac.py:210-211)
- [ ] 8 of 22 CTS activities + 3 of 8 CTS workflows missing @activity.defn/@workflow.defn
- [ ] No temporalio.contrib.pydantic converter → every Pydantic-typed boundary deserializes as dict
- [ ] Every activity dependency (ngch_adapter, immudb_client, cbs_connector) is =None, no DI wired

---

## PHASE 10 — Error → Incident Management (July 2026, Phases 1+2 of 5 COMPLETE)

Goal: ASTRA knows about an incident before the end user reports it. 5-phase rollout.

- [x] messages.yaml incident: block schema — incident_class, default_severity P0-P4,
      escalation_trigger IMMEDIATE|THRESHOLD, threshold{count,window_seconds}, owning_team,
      regulatory_reportable, auto_close_eligible, runbook_ref. IncidentMetadata dataclass in registry.py.
      Mandatory on all CRITICAL keys; NEVER-condition allowlist structurally forced to IMMEDIATE +
      regulatory_reportable=true (IET_WATCHDOG_FIRED, AUDIT_WRITE_FAILED, AUDIT_TAMPER_DETECTED).
- [x] shared/incidents/signal.py — emit_incident_signal(key, bank_id); no-ops for unclassified keys.
      Wired into write_audit.py (highest-leverage choke-point); also signals PLATFORM_AUDIT_WRITE_FAILED.
- [x] shared/observability/otel_setup.py — MeterProvider added (get_meter() alongside get_tracer()).
- [x] shared/messages/build_alerts.py — generates infra/k8s/monitoring/generated-incident-alerts.yaml
      (PrometheusRule CRD, 30 rules from 30 CRITICAL keys, grouped by owning_team).
- [x] docs/CTS_Msg_Taxonomy.html — Incident Response column added.
- [x] All 30 CRITICAL keys classified: cts_clearing_ops (18), bank_infra (6), cts_ai_platform (2),
      ej_ops (2), compliance_review (2). Per-cheque terminal decisions set to THRESHOLD not IMMEDIATE.
- [x] UTF-8 encoding bug fixed: registry.py + build_docs.py were missing encoding="utf-8".
- [x] 113 new/updated tests, all GREEN; 3301 total passed, zero regressions.

Still open (needs live infra):
- [ ] Phase 3 — Alertmanager → Grafana OnCall wiring, escalation-chain Layer 3 config UI
- [ ] Phase 4 — widen incident: coverage to WARN/ERROR keys (~150 keys)
- [ ] Phase 5 — maker-checker closure enforcement, compliance_officer RBI-reportability workflow

---

## PHASE 11 — Audit/Notification Producer-Consumer Gap Closure (July 2026, COMPLETE)

- [x] ImmudbClient interface mismatch found + fixed: AsyncImmudbWriter (asyncio.to_thread() adapter)
      in shared/audit/immudb_writer.py — write_audit.py call shape was always correct, class wasn't.
- [x] shared/audit/stream_consumer.py — AuditStreamConsumer: start/stop lifecycle, per-message failure
      isolation, HSM optional (writes UNSIGNED with warning rather than skipping).
- [x] apps/audit_service/main.py — runnable FastAPI worker entrypoint (/health/live + /health/ready),
      consumer as lifespan background task, graceful degradation on missing Redis/Immudb. 6 tests.
- [x] mcp_connections.py _emit_audit() now calls both Kafka publish (durable backup) AND
      buffer_audit_event() via Redis Streams — closes the MCP audit loop to Immudb.
- [x] Notification gap investigated: _route_notification() logs unresolved-recipient boundary
      (roles that SHOULD be notified, priority) without fabricating delivery. User directory
      resolution is a separate gap (flagged, not started).
- [x] Local auth connector gap: YugabyteDBLocalAuthConnector implemented (asyncpg, explicit columns,
      email/phone, never SELECT *). AuthConnectorFactory._build_local() now returns real implementation.
      infra/migrations/platform/20260716_add_local_auth_contact_info.py (additive nullable columns).
- [x] 30 new/updated MCP router tests (71 total), 21 local connector tests. 3340 suite total, zero regressions.

---

## PHASE 12 — TOTP/MFA + MSV + Hardcoded-Value Audit (July 2026, COMPLETE)

- [x] TOTP/MFA pipeline: mfa.py (TOTPMFAService, hand-rolled RFC 6238), mfa_stores.py
      (InMemoryTOTPSecretStore + VaultTOTPSecretStore), enrollment_store.py
      (YugabyteDBAccountEnrollmentStore), auth_service.py (login→MFA→session state machine),
      migration 20260717_add_totp_enrolled.py, routers/auth.py (/v1/auth/login, /mfa/verify,
      /mfa/enrol/begin, /mfa/enrol/confirm, /refresh, /logout, /session).
      VaultTOTPSecretStore accepts injected vault_client from config_service.get_vault_client()
      to avoid double Vault bootstrap.
- [x] MSV module documented: modules/msv/ — Temporal mandate processing, BRE engine
      (AND/OR/majority), signatory vault, CBS sync, signature detector, bulk enrollment.
- [x] Hardcoded-value fixes: fraud.py (500_000 + 180.0 → config_service.get()),
      demo_cloud_extract.py (HF base URL → get_secret()), main.py CORS + env gate,
      CTS/EJ worker.py temporal address → get_platform().
- [x] shared/config/config_service.py — get_vault_client() added (reuse existing hvac.Client).
- [x] shared/event_bus/topics.py — Kafka topic name constants registry (15 topics, single source of truth).
