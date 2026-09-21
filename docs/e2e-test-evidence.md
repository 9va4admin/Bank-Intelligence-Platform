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

---

## Entry 2026-09-21 — recorded 21:26 IST (UTC+05:30), repo HEAD `7a071f8`

### What was run (real API + real worker + real infrastructure)
- Real FastAPI process (`uvicorn apps.api.main:app`) with **real password login and real TOTP MFA enrolment**
  (no `DEV_BYPASS`), real endpoints for onboarding (branch, processing unit, link), scanner-session open,
  scan upload-url, image PUT to MinIO, scan submit — which starts the real `OutwardScanWorkflow`.
- Confirmed live: 1 API-submitted scan → workflow COMPLETED → OCR read the image fetched from `s3://`
  (`ocr.hf_cloud_fallback_used micr_found=True payee_found=True`) → first row ever written to
  `cts.agent_decisions` (count 0 → 1).

### Defects found by this real run and fixed (each has a regression test; see git log `2e7f369`..`7a071f8`)
Fresh-database migration failed (33-char revision id; ~35 legacy migrations never in the chain: 12 tables and 9
columns missing in the dev DB) · hub-summary SQL referenced a non-existent column · date passed as str to a DATE
param · 122 response fields typed `str` for timestamps/dates (HTTP 500 against a real DB) · config hot-reload
consumer class missing · no MinIO bucket was ever created · worker MinIO client hard-coded HTTPS · API issues
`s3://` URLs but every image-reading activity used an HTTP client (every API scan was read as blank) ·
`persist_agent_decision` failed silently on every call (UUID column, JSONB param) so decisions were never stored ·
`PLATFORM_ADMIN` could delete login logs · bank SAML/LDAP config was never read by the auth factory ·
22 audit events had no notification routing · dev bank `kbl` was not in `platform.banks` (FK).

### Still NOT covered / open (do not claim otherwise)
1. **Outward clearing stage not run through the API**: lot sealing, endorsement, clearing-session submit, NGCH
   submission, reconciliation. The API-driven path exists (`/outward/lots/seal-all`, `/endorsement/batch`,
   `/outward/clearing-session/submit`) but has not been exercised.
2. **Inward pipeline not re-run** after the date/amount/UUID/persist fixes; only the earlier direct-to-Temporal
   inward runs exist (they pre-date these fixes).
3. `OutwardScanSubmitRequest` has **no fields for teller-entered depositor details**, so via the API the payee
   check depends on rear-image OCR only (no rear images exist in the test set).
4. **No bank-onboarding endpoint or workflow exists**: `platform.banks` is filled only by a dev seed script.
   `kbl` was inserted by hand (labelled DEV SEED).
5. `cts.human_review_items` is referenced only by its migration — nothing reads or writes it; the human-review
   queue has no durable DB record (Redis/Kafka only). Needs a design decision.
6. TOTP secrets live in API memory unless Vault is the secrets backend (dev limitation; MFA flag must be reset
   after each API restart).
7. Unchanged from the earlier entry: real CBS/NGCH/HSM/GPU-vLLM, trained signature and fraud models,
   scanner-grade images, RedisBloom module.

---

## 2026-09-21 22:15 IST — Outward clearing stage via the real API (INCOMPLETE — blocked)

Run: real API (127.0.0.1:8010, login+TOTP MFA), real Temporal worker, YugabyteDB, MinIO. Nothing mocked except the
labelled dev CBS/NGCH stand-ins.

**Verified working live:** 5 scans through `/scan/upload-url` → MinIO PUT → `/scan/submit` → all ACCEPTED;
`/lots/seal-all` sealed a lot; `GET /outward/lots` now returns lots (fixed by commit `d423d46`, lenient asyncpg DATE
codec — previously every `$N::date` query with an ISO-string argument raised inside a swallowed try/except and
returned an empty list; ~15 such queries exist in the API routers). `POST /endorsement/batch` returned 202 and
started `BatchEndorsementWorkflow`.

**Failed live (not fixed yet):**
1. `stamp_endorsement` raised `TypeError: EndorsementTemplate.__init__() got an unexpected keyword argument
   'presenter_name'` (activity and dataclass disagree: dataclass needs bank_name, branch_name, bank_ifsc,
   endorsement_text). Never executed against real code before.
2. `LotStore.fetch_instrument_images` (called by the activity) does not exist.
3. `EndorsementStamper` only appends bytes to the image; the stamped image is discarded and never stored.
4. The outward scan path persists only a masked row in `cts.outward_scan_events` (no full MICR, amount, cheque
   date, image keys); `lot_id` on those rows is NULL; **no row is written to `cts.cheque_instruments`**. The
   lot → NGCH-file builder (`LotStore._fetch_instrument_details`) selects columns that do not exist in that table
   (`image_front_bw_key`, `image_back_bw_key`, `image_front_gray_key`, `width_px`, `height_px`, `dpi`, `bit_depth`,
   `cycle_no`, `payor_bank_rout_no`, `presenting_bank_rout_no`, `trans_code`, `doc_type`).
5. Clearing-session submit was not exercised (test request used an invalid `deployment_mode`; valid values are
   `SB_NGCH` / `AGENCY_SB_RELAY`).

**Not tested:** endorsement result, clearing-session submit, NGCH submission, session reconciliation, RRF.
**Status: outward clearing stage is NOT working end to end.** Fixing it needs an outward instrument record (table or
columns for MICR, amount, date, image keys, lot assignment) written at scan-accept time.

---

## 2026-09-21 23:40 IST — Outward clearing stage, continued (still INCOMPLETE)

Same setup as the 22:15 entry (real API + Temporal worker + YugabyteDB + MinIO; dev CBS/NGCH stand-ins).

**Now verified live, end to end through the API:**
- 3 scans ACCEPTED → each wrote one full `cts.cheque_instruments` row (`direction=OUTWARD`: cheque no, 9-digit MICR
  code, transaction code, amount in paise, cheque date, image refs, lot id) — migration 025.
- Lot assignment now happens on ACCEPT only (was: counted at submit, including rejected scans).
- A scan whose OCR MICR cannot be parsed (`620339 560226375`) is held for human repair (`MICR_UNREADABLE`), not errored.
- `POST /endorsement/batch` → `BatchEndorsementWorkflow` **COMPLETED**: stamp_endorsement, update_lot_status,
  write_audit all ok; lot status ENDORSED (3/3, 0 failed); stamped rear images stored in MinIO
  (`docs/evidence/2026-09-21/endorsed_rear_sample.png`). Note: the test cheque set has no rear images, so a front
  image stands in for the rear and the stamp overlaps printed text.

**Defects found and fixed in this stretch (all with tests, all committed):**
lenient asyncpg DATE codec (`d423d46`); `cheque_instruments` had no partition from 2026-09-01 so every inward and
outward insert failed (migration 026: months to 2028-12 + DEFAULT partition; NO scheduled partition-maintenance job
exists yet); Temporal could not decode `date` fields of dataclass inputs (post-dated hold); five
`RetryPolicy(maximum_attempts=None)` (invalid in this SDK, 0 = unlimited) that made workflow tasks fail forever;
plain-digit / noisy OCR MICR parsing; LotStore was given the async MinIO wrapper instead of the raw client; scan
images live in bucket `cts-images` but LotStore read `astra-cts`; `update_lot_status` wrote non-existent columns
(migration 027); `EndorsementTemplate` constructor mismatch; `fetch_instrument_images` missing; stamper never
stamped; clearing-session submit passed `id_reuse_policy` as a string (request errored/hung).
Stale tests fixed: SMB push parser (17), DEM CT=01, retry-constant assertions.

**Clearing session (`ClearingSessionWorkflow.run`) — real path NEVER worked; found live, NOT yet fixed:**
1. API generates a random `session_id` (`clearsess-xxxx`); `seal_all_lots` looks up `cts.lots.session_id = that id`
   (lots carry the scanner session id) → always EMPTY_SESSION. Live result: workflow "COMPLETED" with EMPTY_SESSION,
   nothing submitted.
2. `seal_all_lots` selects `status='SEALED'` but endorsement moves lots to `ENDORSED`.
3. SB path submits ONE "consolidated" lot (`{session_id}-consolidated`, empty IFSC) although the NGCH file builder is
   per lot; `NGCHSubmissionInput` requires `routing_no` and `clearing_type`, which the caller never passes (validation
   error the moment a non-empty session reaches it).
4. `update_session_status` writes `cts.clearing_sessions.npci_ack_ref` / `updated_at`, which do not exist (table has
   `ngch_session_ref`), and the workflow passes `ngch_reference=` to a model whose field is `npci_ack_ref` (silently
   dropped). No code inserts the `cts.clearing_sessions` row (0 rows; `center_id` UUID NOT NULL).
5. Agency path reads `lot["lot_number"]`; lots have `lot_id`.
6. The existing unit tests exercise only `run_with_mocks`, never `run`.

**Also open:** concurrent scans contend on the single `cts.lots` row (YugabyteDB serialization errors; Temporal
retries succeed but 500-way concurrency is untested); stored endorsed image key ends `.tiff` although the bytes are
JPEG when the source is JPEG; `platform.banks.bank_name` still carries the "DEV SEED" label so it prints on stamps;
`cts.cheque_dedup` table referenced by the dedup module does not exist; one intermittent failure of
`test_real_run_mismatch_held_spawns_child_workflow` (TIMEOUT_AUTO_REJECTED) was seen once and not reproduced in 6 reruns.

**Not tested:** clearing-session submission of lots, NGCH file build (CXF/CIBF, HSM signing), NGCH submission,
session reconciliation, RRF. **Status: outward pipeline works through ENDORSEMENT only.**
