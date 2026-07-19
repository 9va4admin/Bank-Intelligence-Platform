# Gemini Technical Evaluation — Architecture Hardening (July 2026)

> **Source:** Google Gemini 1.5 Pro evaluation of full ASTRA codebase (1.21 MB, 97 files)
> **Verdict:** "Generation 3 clearing platform" — 5 gaps identified, all resolved.
> **Date:** July 2026

---

## Scores

| Layer | Score | Notes |
|---|---|---|
| Workflow Engine | 10/10 | Elite — IET Watchdog is a masterstroke |
| Kafka Design | 8/10 | Strong — good multi-tenant SMB isolation |
| Vault Strategy | 8/10 | Strong — vectors offload CBS significantly |
| Data Integrity | 7/10 | Solid — partitioned FK needs app-level logic |
| AI Integration | 6/10 | At Risk — 72B models threaten 600ms SLA |
| HA/DR | 4/10 | Critical — no PR-DR strategy for air-gapped sites |

---

## Fix A — Cascaded AI Model (L1 Guard → L2 Escalation) ✅ SHIPPED

**Problem:** Qwen2-VL 72B for 500 parallel agents causes VRAM queuing → 600ms SLA breach.

**Decision:**
- L1: Qwen2-VL 7B — handles ~90% of cheques in < 100ms (queue: `cts-vision-l1`)
  - Escalate to L2 if: confidence < `ai.cascade.l1_confidence_threshold` (default 0.85) OR amount ≥ `ai.cascade.high_value_threshold` (default ₹50L) OR OPA override
- L2: Qwen2-VL 72B — forensic (queue: `cts-vision-l2`, dedicated A100)
- Same cascade for OCR: GOT-OCR2.0 7B (L1) → full (L2)

**Config keys (Layer 3, hot-reload):**
```
ai.cascade.l1_confidence_threshold    default: 0.85
ai.cascade.high_value_threshold       default: 5000000
ai.cascade.l2_escalation_enabled      default: true
ai.cascade.l1_model_vision            default: "qwen2-vl-7b"
ai.cascade.l2_model_vision            default: "qwen2-vl-72b"
ai.cascade.l1_model_ocr               default: "got-ocr2-7b"
ai.cascade.l2_model_ocr               default: "got-ocr2-full"
```

**Implementation:** `shared/ai/model_cascade.py` — `CascadeOrchestrator.call_vision_cascade()` and `call_ocr_cascade()`.
Wired into `alteration.py` and `ocr.py`. 13 tests.

**New vLLM queues:** `cts-vision-l1`, `cts-vision-l2`, `cts-ocr-l1`, `cts-ocr-l2`
**New Kafka topic:** `cts.vision.cascade.{bank_id}` (L2 escalation requests)

---

## Fix B — 15-Minute Delta Vault Sync + Canceled Leaf Bloom Filter ✅ SHIPPED

**Problem:** Daily 6AM sync → stop-payments filed mid-day missed → up to 18-hour fraud window.

**Decision:**
- Full sync (6AM daily): signatures — unchanged
- Delta sync (every 15 min): stop-payment instructions + canceled cheque leaf serials only
  - `DeltaVaultSyncWorkflow` on Temporal schedule (deterministic, exactly-once)
  - Kafka topic: `cts.vault.delta.{bank_id}` (high-priority)
  - Workflow ID: `cts-vault-delta-{bank_id}-{yyyymmddhhmm}`
- Bloom filter: `bloom:canceled:{bank_id}` in Redis CTS — check MICR serial BEFORE any vLLM call
  - Bloom hit → HUMAN_REVIEW immediately (saves ~500ms GPU time)
  - False positive rate: < 0.1% (unnecessary human review, never auto-confirm)

**Config keys:**
```
vault.delta_sync_interval_minutes     default: 15
vault.bloom_false_positive_rate       default: 0.001
vault.bloom_expected_items            default: 100000
vault.delta_sync_enabled              default: true
```

**Implementation:** `modules/cts/workflows/delta_vault_sync_workflow.py`. 17 tests.

---

## Fix C — HA/DR Blueprint ✅ SHIPPED

**Problem:** No explicit DC1→DC2 synchronisation mechanism specified; exactly-once at risk during DC failure.

**Decision:**

| Component | Config |
|---|---|
| YugabyteDB | RF=3, min_replica_count=2 (quorum writes) |
| Kafka | replication.factor=3, min.insync.replicas=2 |
| Temporal | DC1 primary + DC2 warm replica (cross-cluster replication); ArgoCD flips on DC1 failure |
| Redis vaults | DC1 active, DC2 passive; config-service switches within 30s on failure |

**Helm values updated:** `infra/helm/astra-platform/values.yaml` — `ha.*` section:
`ha.yugabyte.rf: 3`, `ha.kafka.min_insync: 2`, `ha.temporal.dr_cluster_enabled: false` (per-bank opt-in), `ha.redis.vault_replication_mode: active-passive`

---

## Fix D — Software-Defined FK Integrity (EJ + Reconciliation) ✅ SHIPPED

**Problem:** YugabyteDB partitioned tables cannot enforce FK across partitions → orphaned canonical records.

**Decision:**
- 9th activity in `EJNormalisationWorkflow`: `verify_canonical_integrity` (after `store_canonical`, before `trigger_dispute_check`)
  - Checks: record exists, `log_id` → `canonical_record` link valid, `canonical_hash` matches
  - On failure: write `EJ_INTEGRITY_FAIL` AuditEvent → halt workflow → alert bank_it_admin
- Reconciliation orphan scanner in `SessionReconciliationWorkflow`: daily pass, alerts only (never auto-deletes)

**Implementation:** `modules/ej/workflows/activities/verify_canonical_integrity.py`

---

## Fix E — Notification Debouncer ✅ SHIPPED

**Problem:** 500 parallel failing agents → 500+ WhatsApp messages in seconds → alert fatigue.

**Decision:**
- 60-second window per `(bank_id, smb_id, event_category)` triple
- If ≥ threshold notifications in window → suppress individuals → emit one Batch Summary Alert
- P0 events (IET breach, kill switch) are NEVER debounced

**Config keys:**
```
notification.debounce.enabled           default: true
notification.debounce.threshold         default: 10
notification.debounce.window_seconds    default: 60
notification.debounce.exempt_priorities  default: ["P0"]
```

**Implementation:** `shared/notifications/debouncer.py` — `NotificationDebouncer` (Redis sorted-set window).
Integrated into `shared/notifications/dispatcher.py` before channel dispatch.
