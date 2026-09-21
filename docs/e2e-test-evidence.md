# ASTRA — End-to-End Test Evidence Log

> **Purpose:** a dated, verifiable record of what has actually been run against live code, so that
> "was this ever really tested?" can be answered from evidence, not memory.
> **Rule:** entries are append-only. Every claim points to a commit, a result file, or both.
> **Honesty rule:** this log records what ran and what did NOT. It must never say "complete"
> for something that was only partly exercised.

---

## Entry 2026-09-21 — recorded 19:36 IST (UTC+05:30), repo HEAD `f4d1e98`

### What "real" means in this entry
Real Temporal server + a real worker process polling it, running the real activity code, on the real
cheque images in `docs/cheques/KBL/`, with real Redis, YugabyteDB, MinIO, ImmuDB and Kafka
containers. OCR ran against the actual images through the Hugging Face cloud model (config-gated
dev fallback — there is no GPU / vLLM in this environment).

This is different from the pytest suite, which substitutes fake activities (`_fake_ocr_extract`,
`_fake_write_audit`, …). The pytest suite tests workflow *logic*; it is not evidence of a real run.

### Stand-ins used (labelled in code and in every digest)
| Component | Stand-in | Why |
|---|---|---|
| CBS | `shared/cbs_connector/dev_stub.py` — dev-only, refuses outside `ASTRA_ENV=development` | no CBS available |
| NGCH | `modules/cts/mcp/dev_stub_ngch.py` — same gate, exactly-once preserved | no NPCI sandbox |
| Signature model | generic ImageNet ResNet-18 (`shared/ai/local_signature_embedder.py`) | the trained Siamese network **does not exist** in this repo |
| Fraud scoring | rule-based fallback | no trained XGBoost/SHAP artifact exists in this repo |
| Policy engine | in-process `PolicyEngine` (CLAUDE.md §2.6) | OPA container dropped by decision |
| Depositor/payee account numbers | synthetic, entered teller-style | no deposit slips exist |
| Outward rear image | front image passed as rear | no rear images exist |
| CTS-2010 image compliance (dev bank only) | `cts.strict_image_quality=false` explicit config row | test images are 96-dpi photos, not scanner captures |

### Inward pipeline — `ChequeProcessingWorkflow` (20 real KBL inward cheques)
- Evidence: `docs/evidence/2026-09-21/inward_real_run_4_at_a_time.json`,
  `inward_real_run_20_at_once.json` (per-cheque decision, rationale, and the list of activities that
  actually ran, taken from Temporal history).
- Result (20 at once, 76.6 s wall): 17 HUMAN_REVIEW, 3 STP_RETURN, **0 STP_CONFIRM**, 0 failures.
  Sequential-4 vs parallel-20 gave identical outcomes for 17/20; the 3 differences were cloud-OCR
  variation between runs.
- Activities observed running for real in Temporal history: `mark_leaf_presented`, `ocr_extract`,
  `get_kill_switch_status`, `detect_alteration` (degraded), `check_security_features`,
  `check_stop_payment`, `lookup_pps`, `detect_signatures`, `verify_signature`, `score_fraud`
  (rule-based), `validate_cheque_series`, `check_cbs_balance`, `check_account_status`,
  `synthesise_decision`, `persist_agent_decision`, `write_audit`, `file_to_ngch` (dev stub),
  plus child workflows `IETWatchdogWorkflow`, `HumanReviewWorkflow`, `FeedbackEmitWorkflow`.
- **Caveat — these inward runs pre-date three fixes** (shared date parser, shared amount parser,
  strict-compliance default). One inward decision in them (`644628`, "Undated cheque" auto-return)
  was wrong because of the date-parser bug. **Inward has not been re-run since those fixes.**
- Most cheques stop at the OCR-quality gate (date box, amount words/figures) — that is the main
  accuracy blocker, not a pipeline fault.

### Outward pipeline — `OutwardScanWorkflow` (19 real KBL outward cheques)
- Evidence: `docs/evidence/2026-09-21/outward_real_run_19_cheques.json`,
  digest `docs/astra-outward-real-digest.html`.
- Result (final run): 7 ACCEPTED, 4 MISMATCH_HELD, 2 POST_DATED_HELD, 6 CTS_REJECTED;
  0 activity failures, 0 workflow failures, 0 timeouts.
- Seeded, labelled test cases behaved as designed: frozen payee → held, payee not in vault → rejected,
  name mismatch → held. Post-dated cheque (dated 09/10/2026) → `POST_DATED_HELD` with the
  `PostDatedHoldWorkflow` child started.
- Activities observed running for real: `ocr_extract`, `check_cheque_dedup`,
  `extract_rear_payee_details`, `validate_payee_account` (AccountVault → CBS stub),
  `cross_check_ngch_metadata`, `validate_cts2010`, `detect_signatures`, `check_security_features`,
  `run_vision_presentment_check` (degraded/cloud path), `write_audit`,
  `record_outward_scan_event`, `persist_agent_decision`.

### Load / concurrency test (AI activities STUBBED — pipeline-only, not an AI speed test)
- Stub: `modules/cts/dev/load_test_activities.py` (dev-only, labelled `LOAD-TEST-STUB`).
- Evidence: `load_test_ai_stubbed_full_manual_console.txt`, `load_test_ai_stubbed_full_stp_console.txt`,
  `load_test_ai_stubbed_full_manual.json`, `load_test_ai_stubbed_100_cheque_profiling_run.json`.
- 620 cheques (20 / 100 / 500 at once), stop mode FULL_STP: 620/620 completed, 0 failed,
  620 STP_CONFIRM, exactly 620 NGCH filings (dev stub) — no duplicates, no losses.
- Throughput flat at ~2 workflows/s. Container CPU during a burst: Temporal server ~250 %,
  its Postgres ~170–190 %, Kafka rising; worker, YugabyteDB, ImmuDB, Redis mostly idle.
  Conclusion: the single-container dev Temporal on Docker Desktop is the ceiling here.
- **This says nothing about the 600 ms SLA or AI throughput** (no GPU here; AI was stubbed).
  The staging benchmark `tests/performance/test_cts_500_cheque_benchmark.py` has never been run.

### NOT covered (do not claim otherwise)
1. **Outward clearing stage is untested end to end:** `ClearingSessionWorkflow`, lot sealing,
   `BatchEndorsementWorkflow`, `NGCHSubmissionWorkflow`, `SessionReconciliationWorkflow`, RRF.
   (`OutwardScanWorkflow` deliberately leaves lot grouping to `ClearingSessionWorkflow`.)
2. **Inward re-run after the date/amount fixes** — pending.
3. Real CBS, real NGCH, HSM, GPU/vLLM, trained signature model, trained fraud model, OPA (dropped),
   Langfuse, MLflow, RedisBloom module (dev Redis lacks `BF.*`; the bloom fails open).
4. Real scanner captures (test images are 96-dpi photos) and real rear images.
5. Registration gaps still open: `VaultSyncWorkflow` activities (7), `ChequeRepresentationWorkflow`,
   `check_scanner_fleet_for_alert`, `emit_vault_batch_alert`.
6. Migration chain: ~35 legacy files in `infra/migrations/cts/` root remain outside `versions/`
   (only the account-vault and cheque-leaf tables were consolidated, in `20260921_021`).

### Defects this real testing found and fixed (each has a regression test; git log has the detail)
Worker never polled Temporal (blocked event loop) · bloom filter sync/async mismatch made every cheque a
stop-payment hit · CBS connectors' PII pepper was an un-awaited coroutine · dict-input/no-DI on 25+
activities (generic `bind_di_activity`) · `validate_cheque_series`/`validate_ifsc` never registered ·
series check rejected the workflow's own PRESENTED mark · config key-shape mismatches at the decision step ·
human-review consumer used a non-existent writer method and got no DB pool · date parser rejected the printed
8-box date · amount parser crashed on `10,00,000/-` (workflow task retried forever) · Temporal converter could
not encode `date` (post-dated holds looped forever) · CTS-2010 strict compliance defaulted OFF in code ·
`check_security_features` called with 4 args · vision presentment check crashed without vLLM ·
`AccountVault` wrote ISO strings into TIMESTAMPTZ · signature/PPS vaults built without DB pool.

### How to re-verify
```
git log --oneline --since=2026-09-21   # commits behind every claim above
# Start the stack, then a real worker (dev stand-ins via env), e.g.:
#   CBS_CONNECTOR_TYPE=dev_stub NGCH_DEV_STUB=true python -m modules.cts.worker --bank-id kbl
# Submit cheques with the harnesses used for this entry (kept outside the repo in the session
# scratchpad; the result files above are their raw output).
```
The raw per-cheque histories in `docs/evidence/2026-09-21/` list each activity that ran, taken from
Temporal, so a claim can be checked against the workflow history, not against this prose.
