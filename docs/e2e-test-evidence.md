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

---

## 2026-09-22 10:15 IST — Outward clearing session + NGCH submission — WORKING end to end (dev-stub NGCH)

Same real stack as the 22:15/23:40 entries (real API, Temporal worker, YugabyteDB, MinIO; dev CBS/NGCH stand-ins
only). Continuation of the 2026-09-21 23:40 entry, which left the clearing-session stage completely broken.

**Verified live, in this order, through the real API:** scan (3 cheques ACCEPTED, one full `cheque_instruments`
row each) → lot sealed → `POST /endorsement/batch` (BatchEndorsementWorkflow COMPLETED, real stamped image in
MinIO) → `POST /outward/clearing-session/submit` → `ClearingSessionWorkflow` COMPLETED with
**outcome=SUBMITTED**, a real dev-stub NGCH reference (`NGCH-DEV-E58E231286845AC1`), `cts.lots.status='SUBMITTED'`,
`cts.clearing_sessions.status='SUBMITTED'` with `ngch_session_ref` set, and (fixed in the same stretch, verified
by unit test only — see below) `cts.cheque_instruments` moved to `status='FILED'` with `ngch_instrument_ref` set.

**Every one of these was a real, previously-unexamined bug — the clearing-session code path had never worked
before today.** Each was found by an actual run against real infra, fixed with a failing-then-passing test, and
re-run live:
1. `seal_all_lots` looked up lots by a caller-invented session id no lot ever carried, and by `status='SEALED'`
   after endorsement had already moved them to `ENDORSED` — always returned zero lots.
2. `cts.clearing_sessions.center_id` is a required FK to `cts.processing_centers` → `cts.clearing_zones`, and
   nothing anywhere creates either — self-healing get-or-create added.
3. The session submitted ONE fake "consolidated" lot with an empty IFSC to NGCH; fixed to submit one
   `NGCHSubmissionWorkflow` per real lot.
4. `update_session_status` called with `ngch_reference=` against a model field named `npci_ack_ref` — pydantic
   silently dropped it; and the SQL wrote columns (`npci_ack_ref`, `updated_at`) that don't exist on the table.
5. **`cts.cheque_instruments` had no partitions from 2026-09-01 onward** — every insert (inward AND outward)
   was failing platform-wide until migration 026.
6. Temporal's data converter could not decode a `date` field on a plain dataclass — the post-dated-cheque hold
   workflow was silently broken.
7. Five `RetryPolicy(maximum_attempts=None)` across the workflow modules are invalid in this Temporal SDK
   (`0` means unlimited) — every one made its workflow task fail forever on that activity.
8. `NGCHSubmissionWorkflow` called `build_and_upload_ngch_files`, a second, independent, never-working
   implementation written against the inward data model (`cts.cheque_image_metadata`, ids cross-referenced
   against a UUID column) — rewired to the actually-tested `build_ngch_file` (LotStore-backed). Two existing
   unit tests had encoded the wrong one as correct; corrected.
9. HSM signer: no Vault Transit key exists in dev, so `_build_hsm_signer` returned `None` and NGCH signing
   crashed — added `DevStubHSMSigner` (labelled, `ASTRA_ENV=development`-gated, same pattern as the CBS/NGCH
   dev stubs).
10. **Outward NGCH submission had no adapter method at all** — `submit_outward_lot` / `query_status_outward`
    existed on neither `DevStubNGCHAdapter` nor the real `NGCHAdapter`. Added to the dev stub (auto-acknowledges);
    the real adapter now raises `NotImplementedError` with a clear message (there is no NPCI-facing outward
    transport yet — matches `docs/npci-readiness-plan.md`).
11. Separately: the rate-limit middleware called `call_next(request)` a second time whenever the wrapped route
    raised — this silently turned every unhandled route exception across the ENTIRE API into a client-visible
    hang instead of a 500. Also fixed clearing-session submit not catching `WorkflowAlreadyStartedError` on its
    deterministic workflow id.
12. `mark_lots_submitted` only updated the lot row, leaving `cheque_instruments` stuck at `ACCEPTED` forever —
    fixed to also set `status='FILED'`, `filed_at`, `ngch_instrument_ref`. **Verified by unit test only — not
    re-run live** (would need a fresh scanner session for 2026-09-22; the existing lot was already consumed by
    the successful run above).

**Known, documented, un-fixed gaps in this same path:**
- `submit_to_ngch`'s `cibf_file_path` is always `None` — `LotStore.build_ngch_file` uploads the CIBF image
  bundle to MinIO but does not return its key.
- Real NGCH concurrency (multiple lots/sessions racing on `cts.lots` row updates) produced YugabyteDB
  serialization errors during earlier concurrent scanning; Temporal retries absorbed them for low concurrency,
  untested at scale.
- `cts.processing_centers` / `cts.clearing_zones` are populated only by this self-healing code path — no
  onboarding flow creates them ahead of time.
- `platform.banks.bank_name` for `kbl` still carries a "DEV SEED" label, visible on the endorsement stamp.

**Not yet tested at all:** session reconciliation (`fetch_ngch_settlement_report` / `match_submitted_vs_settled`),
RRF generation. **Status: outward pipeline is verified working end-to-end through NGCH submission. Reconciliation
and RRF are the next untested stage.**

---

## 2026-09-22 20:20–20:45 IST — Inward pipeline, real re-run through the real API (post date/amount/UUID/persist fixes)

Real stack: real Temporal worker (bank_id=kbl, all dependencies genuinely connected — CBS dev-stub fixture,
Redis, YugabyteDB, MinIO, Immudb, Kafka; no mocks), real FastAPI on :8010 with real password+TOTP login. This is
the first inward run **through the real API** (all earlier inward runs went direct-to-Temporal) and the first
inward run since the date-parser/amount-parser/UUID/strict-compliance fixes landed.

**What was run:** 18 real KBL inward cheques (`docs/cheques/KBL/IW CHQ/`), account numbers and amounts read by eye
off each image (not OCR-derived) and seeded into a CBS dev-stub fixture (`scratchpad/cbs_dev_fixture_kbl.json`,
all ACTIVE with sufficient balance — this run exercises the OCR/decision path, not CBS edge cases). Images
uploaded to the real MinIO (`s3://cts-images/inward/kbl/{cheque_no}.jpg`), submitted one per instrument via
`POST /v1/cts/inward/{instrument_id}/submit`, results read back via `GET /v1/cts/decisions/{instrument_id}` (see
defect below) and cross-checked directly against Temporal (`handle.result()`) for ground truth.

**Result:** 18/18 workflows COMPLETED, 0 failures, 0 timeouts. **18/18 decision = HUMAN_REVIEW, 0 STP_CONFIRM.**
14 for `ocr_quality_low_confidence_fields: ['date', 'payee', 'amount_words', 'amount_figures']`; 4
(`496100`, `644628`, `915526`, and one more) for `ocr_quality_MODEL_UNAVAILABLE` (the HF cloud OCR fallback got
401'd — this dev environment's worker process did not have `ASTRA_SECRET_DEMO_HF_TOKEN` set, a real environment
gap in this run, not a pipeline defect; local GOT-OCR2 is also down in this dev environment, so these 4 fell
through to Tesseract-only quality). Raw per-cheque results:
`docs/evidence/2026-09-22/inward_real_run_post_fix_18_cheques.json`.

**A real defect found and fixed in this run:** `GET /v1/cts/decisions/{instrument_id}`
(`apps/api/routers/cts_inward.py`) reported `workflow_status: "RUNNING"` for **every single one of the 18
cheques**, despite Temporal confirming all 18 had genuinely COMPLETED with a real decision. Root cause:
`ChequeProcessingWorkflow.run` returns a plain `dict` (no dataclass return type), so the route's
`result.decision` / `result.rationale` (attribute access) raised `AttributeError` on every completed workflow —
silently swallowed by a bare `except Exception: pass`, which fell through to the `"RUNNING"` default. Confirmed
live by querying Temporal directly (`handle.result()` returned `{"decision": "HUMAN_REVIEW", ...}`, a dict) while
the API endpoint simultaneously reported `RUNNING` for the same workflow. **This endpoint had never correctly
reported a completed inward decision before this run — every prior "it works" claim about this endpoint was
untested against a real completed workflow.** Fixed: dict-key access (with an attribute-access fallback), and
the bare `except` now logs a warning instead of swallowing silently. Regression test:
`test_completed_workflow_with_dict_result_reports_the_real_decision`. Verified live, post-fix, against the same
18 real completed workflows — all 18 now report the correct `HUMAN_REVIEW` status and rationale. Commit `1c297f9`.

**Also observed, NOT fixed in this run (flagged separately, `task_b93686f5`):** `store_postdated_hold.db_error
error="'coroutine' object has no attribute 'decode'"` fired repeatedly for instrument `841390-*` — this is an
**outward** cheque number, picked up via a leftover Kafka outward-scan-trigger message from an earlier session,
not one of this run's 18 inward submissions. Confirms a real, currently-broken "forgot to await" bug in
`store_postdated_hold`, out of scope for this entry, spawned as a separate follow-up task.

**Known gaps in this specific run (labelled, not hidden):**
- HF cloud OCR fallback token not configured in this worker process → 4/18 cheques fell to Tesseract-only OCR
  quality (`ocr_quality_MODEL_UNAVAILABLE`), correctly routed to human review either way.
- `feedback_emit.accumulator_unreachable` (×4) — `FeedbackAccumulatorWorkflow` is not running in this dev
  environment; each cheque's decision signal had nowhere to land. Known, pre-existing gap.
- `worker_activities.cascade_orchestrator_unavailable` — no local vLLM cluster; expected in this dev environment.
- CBS fixture is hand-seeded with all-ACTIVE accounts (teller-style stand-in, same as the outward runs) — this
  run validates the OCR-quality → human-review path, not CBS status/stop-payment/PPS edge cases.

**Still NOT covered for inward:** signature/PPS vault HIT scenarios (fixture has no seeded signatures), a
cheque that actually clears the OCR-confidence gate and reaches STP_CONFIRM or an AUTO_RETURN outcome (all 18
in this real sample stopped at the OCR-quality gate — consistent with the 2026-09-21 direct-to-Temporal finding
that OCR quality, not pipeline logic, is the dominant blocker on this photographed, sub-CTS-2010-DPI image set),
`HumanReviewWorkflow`'s reviewer-decision signal path (queued but not actioned in this run), `IETWatchdogWorkflow`
actually firing (no cheque ran past its IET deadline in this run).

---

## 2026-09-22 21:20–21:35 IST — `store_postdated_hold` fix: 4 stacked bugs, each found live by fixing the last

Follow-up to the `store_postdated_hold.db_error` finding flagged in the previous entry. Real stack throughout:
real Temporal worker (bank_id=kbl), real YugabyteDB, real `PostDatedHoldWorkflow` started directly via a real
Temporal client (`shared.temporal.converter.pydantic_data_converter` — required for the workflow's `date`-typed
input field to encode at all). No mocks anywhere in this verification pass; each fix below was confirmed live
before moving to the next, not assumed from the diff.

**Bug 1 (the one reported):** `store_postdated_hold` / `mark_hold_cancelled`
(`modules/cts/workflows/activities/postdated_hold_activities.py`) called `config_service.get("db.cts.dsn")`
without awaiting it — `config_service.get` is a coroutine function, so `dsn` was a `coroutine` object, not a
string. `asyncpg.connect(dsn)` then failed deep inside asyncpg's own DSN parsing:
`'coroutine' object has no attribute 'decode'`, exactly as reported. Fixed by switching to
`await config_service.get_secret("db.cts.dsn")` — both the missing `await` and the correct method, matching
the convention `worker_activities.py`'s `_build_db_pool` already uses for this same key.

**Bug 2 (found live immediately after fixing bug 1):** the very next live run failed differently —
`RuntimeError: config_service.initialise() has not been awaited`. This activity imports the raw
`config_service` module-level singleton with no defensive check, unlike `outward_scan_activities.py`'s
`validate_cts2010` and `persist_outward_instrument.py`, which already carry `if not config_service._ready:
await config_service.initialise()` for exactly this reason. Bug 1's coroutine error had been masking this
entirely — a plain `config_service.get(...)` call (unawaited) never actually executes the method body, so
`_assert_ready()` was never reached until bug 1 was fixed. Fixed with the same established guard.

**Bug 3 (found live immediately after fixing bug 2):** `conn.execute(...)` then failed on the `$3::date`
argument: `invalid input for query argument $3: '2026-09-27' ('str' object has no attribute 'toordinal')` —
asyncpg's default DATE codec only binds from a real `date` object, and `release_date` is passed through as
the ISO string it already is on the activity's dict input. Same failure mode already solved elsewhere in this
codebase (`shared/db/codecs.py`'s `register_lenient_codecs`, commit `d423d46`, used by
`persist_outward_instrument.py`) — just never applied to this module. Fixed by calling
`register_lenient_codecs(conn)` right after connecting, in both activities.

**Bug 4 (found live immediately after fixing bug 3):** the next argument failed the same way —
`invalid input for query argument $4: '...' (expected a datetime.date or datetime.datetime instance, got
'str')` for `held_at`/`cancelled_at`. `register_lenient_codecs` only registers a codec for the DATE type, not
TIMESTAMPTZ. Fixed locally in this module (`_parse_timestamptz()`, not by widening the shared codec, to keep
the blast radius to what was actually tested here) for both fields.

**Verified live, end to end, after all 4 fixes:** started a real `PostDatedHoldWorkflow` via a real Temporal
client against the real worker; the real `store_postdated_hold` activity wrote a real row to
`cts.postdated_holds`:
```
{'instrument_id': 'POSTDATED-FIX-VERIFY-FINAL2', 'bank_id': 'kbl',
 'release_date': datetime.date(2026, 9, 27), 'status': 'PENDING',
 'held_at': datetime.datetime(2026, 9, 22, 16, 5, 35, 585926, tzinfo=datetime.timezone.utc),
 'cancel_reason': None, 'cancelled_at': None,
 'created_at': datetime.datetime(2026, 9, 22, 16, 5, 35, 793870, tzinfo=datetime.timezone.utc)}
```
Correct types throughout — a real `date` and real `datetime` objects, not strings. Commit `f03e470`.
10 regression tests (`tests/modules/cts/workflows/activities/test_postdated_hold_activities.py`), each
confirmed RED against the pre-fix code before being fixed GREEN (bug 2's guard tests were reverted and
re-run live to confirm RED, per TDD discipline — bugs 1/3/4 were reproduced RED naturally since the test file
was written before each corresponding fix). Wider suite: `tests/modules/cts/workflows/` 1580 passed, 0
regressions.

**A 5th, separate bug found in this same live verification, NOT fixed here (out of scope, flagged
separately, `task_c127dd2a`):** with the activity now genuinely persisting, the *workflow* itself
(`PostDatedHoldWorkflow.run`, `modules/cts/workflows/postdated_hold_workflow.py:95`) then failed its own
workflow task: `AttributeError: module 'temporalio.workflow' has no attribute 'sleep'` on
`await workflow.sleep(timedelta(days=days_remaining))`. This is a wrong/nonexistent Temporal SDK API call,
not an activity-layer bug — `.claude/rules/temporal.md` itself documents `workflow.sleep()` as the correct
deterministic-sleep API, which may mean that rule needs correcting too. **`PostDatedHoldWorkflow` cannot
currently complete a real run past this point** — the DB write happens (confirmed above), but the workflow
then fails its task repeatedly. This is the actual current status: the persistence layer this entry set out
to fix is fixed and verified; the workflow that calls it is separately broken one level up.

---

## 2026-09-23 — `PostDatedHoldWorkflow.run()` fix: `workflow.sleep()` does not exist in this SDK

Follow-up to the previous entry's 5th finding. **`.claude/rules/temporal.md` was itself wrong** — it stated
"`asyncio.sleep()` inside a workflow — use `await workflow.sleep()` (deterministic)". Checked directly
against the installed SDK: `temporalio==1.7.1` has no `workflow.sleep` attribute at all. That rule's own
example had apparently never been run for real before this. Corrected in the same change (new "Deterministic
Sleep" section in the rules file), and it now also flags that the same broken call exists, unfixed, in two
other workflows (`feedback_workflow.py:302`, `platform_health_check_workflow.py:204` — spawned as
`task_87a6ffd2`, out of scope here).

**Root cause, and why this was never caught:** every call to the missing `workflow.sleep()` fails the
workflow *task* (not the workflow itself, and not an activity) — Temporal retries a failing workflow task
forever by default, so the workflow never reaches a terminal FAILED state. A plain `await
client.execute_workflow(...)` therefore hangs forever rather than raising, and the project's existing test
file for this workflow (`tests/modules/cts/workflows/test_postdated_hold_workflow.py`) tested only pure
helper functions and dataclasses, never `.run()` against a real Temporal environment — so nothing could have
caught this before a live run.

**Fix:** `workflow.wait_condition(lambda: self._cancelled, timeout=timedelta(days=days_remaining))`, wrapped
in `try/except asyncio.TimeoutError: pass` — the same idiom already used correctly elsewhere in this
codebase (`hold_escalation_workflow.py`, `human_review_workflow.py`, `iet_watchdog_workflow.py`). **Not just
an API rename — a real behavioural fix**: the old code (even if `workflow.sleep()` had existed) only checked
`self._cancelled` *after* a full, uninterruptible sleep; `wait_condition` wakes the workflow the instant
`cancel_hold` arrives, which is what this workflow's own docstring already claimed ("accepts a cancel_hold
signal … before its release date") but never actually did.

**TDD, against a real Temporal time-skipping environment (not mocked)** —
`tests/modules/cts/workflows/test_postdated_hold_workflow.py::TestPostDatedHoldWorkflowRealRun`, 2 new tests
(`test_sleep_to_release_date_completes_and_releases`, `test_cancel_signal_wakes_the_wait_before_the_release_date`),
each confirmed RED first. **The RED confirmation itself needed a different approach than usual**, because of
the "retries forever" failure mode above: a plain `await handle.result()` against the buggy code never
returns, so a bounded check was used instead — `asyncio.wait_for(handle.result(), timeout=15)`, then on
timeout, `fetch_history()` inspected for a `workflow_task_failed_event_attributes` event whose message
contains `"has no attribute 'sleep'"`. Confirmed present against the unfixed code; confirmed absent, with a
fast correct result, after the fix. Also required pointing the test's `WorkflowEnvironment` at
`shared.temporal.converter.pydantic_data_converter` — the default converter can't encode
`PostDatedHoldInput.release_date` (a plain `date` field) at all, a separate (harmless here) gap the default
test setup would otherwise hit first.

**Verified live, against the real Temporal docker stack — no mocks, no time-skipping:** started a real
`PostDatedHoldWorkflow` with `release_date` 30 days out (so the fix's fast-wake behaviour, not just "it
doesn't crash," is what's actually being proven), signalled `cancel_hold` after 3 real seconds, received
`PostDatedHoldResult(status='CANCELLED', released_at=None)` in seconds — not 30 days. Confirmed the real row
in `cts.postdated_holds`:
```
{'instrument_id': 'SLEEPFIX-LIVE-VERIFY-001', 'bank_id': 'kbl', 'status': 'CANCELLED',
 'cancel_reason': 'live-verify stop-payment',
 'held_at': datetime.datetime(2026, 9, 22, 21, 26, 42, ...),
 'cancelled_at': datetime.datetime(2026, 9, 22, 21, 26, 45, ...)}  # ~3s later, matching the live test
```
The RELEASED path's child-`ChequeProcessingWorkflow`-start was **not** separately live-verified in this
entry (it needs a real `ChequeWorkflowInput`-shaped `original_workflow_data`, which is a different concern
from this fix) — the cancel path already exercises the same `wait_condition` fix this entry is about, against
real infra, without that dependency.

16/16 tests in the file pass; wider `tests/modules/cts/workflows/` suite: 1582 passed, 0 regressions.
Commit (fix + tests + rules correction) pending push alongside this entry.

**Status: `PostDatedHoldWorkflow` now genuinely completes a real run past the sleep line.** Combined with the
previous entry, both `store_postdated_hold` (persistence) and the workflow's own orchestration are fixed and
live-verified end to end for the cancel path. The release (no-cancel) path's full chain into
`ChequeProcessingWorkflow` remains untested.

---

## 2026-09-23 — The "one-click" launcher (`scripts/start.ps1` / `dev-init.py`) never actually worked either

User asked for a single script to reliably bring up the whole platform. Checked `scripts/start.ps1` +
`scripts/dev-init.py` (the generator behind it) against everything a real worker actually needs — found the
"official" env generator had almost the same class of gap this week's manual sessions kept hitting: **6 real,
silent-degradation bugs**, none of them raising an error a user would notice.

1. Immudb: generator wrote `ASTRA_SECRET_IMMUDB_ADMIN_PASSWORD` (never read anywhere); the real code needs
   `IMMUDB_HOST`/`IMMUDB_PORT` (plain) + `ASTRA_SECRET_IMMUDB_USERNAME`/`PASSWORD` — none of the four were set.
   Every launcher-started worker had `immudb_client_unavailable` — no audit trail, silently.
2. MinIO: `ASTRA_SECRET_MINIO_ENDPOINT` was never set (only the access/secret keys) —
   `minio_client_unavailable` on every run; lot storage and the OCR feedback corpus never worked.
3. PII pepper: generator wrote a bank-namespaced key; the code reads a plain `ASTRA_SECRET_PII_HASH_PEPPER`.
   Signature/PPS/account vaults never initialised on any launcher-started run.
4. CBS: `CBS_CONNECTOR_TYPE`/`CBS_BASE_URL` were never set — the dev-stub CBS connector never loaded, so
   every real cheque's account/balance/stop-payment/PPS check silently degraded.
5. `dev-init.py`'s final banner printed passwords (`Admin@Astra2026!` etc.) that do not match the actual
   seeded password (`Astra@1212`, confirmed against `seed_users()`'s own `ph.hash()` calls) — anyone
   following the printed instructions literally could not log in.
6. `start.ps1` never launched `apps/sig_detector` or `apps/indic_ocr` at all — both are real HTTP services
   the worker calls directly (`services.sig_detector.url`, `services.indic_ocr.url`), not routes the API
   gateway merely proxies. Signature detection and Indic-script OCR refinement were silently unavailable
   from every launcher-started session. Also fixed a stale `:5173` frontend label (real port is 4000, per
   `apps/web/vite.config.js`).

**Fixed** in `scripts/dev-init.py` (correct keys for all of the above, plus a new
`scripts/dev_cbs_fixture.json` generator — empty and safe by default: unknown accounts route to human
review, never a silent pass) and `scripts/start.ps1` (launches both AI sidecars too).

**Verified live, for real, end to end — not just read the diff:** killed every python/node process, ran
`python scripts/dev-init.py --bank-id kbl` (regenerating all three files from the fixed generator, zero
manual overrides), then `powershell scripts/start.ps1 -BankId kbl` as one real command. All five components
came up healthy from that single run:
- API `/health/ready`: `{"config_service":true,"redis_cts":true,"temporal":true,"kafka_cts":true,"session_service":true}`
- CTS worker: confirmed actually polling (`cts-processing-kbl` shows a live poller via Temporal's own
  task-queue API, not just a log line)
- IndicOCR sidecar (:8021): `{"status":"ready","backend":"paddle"}`
- Signature Detector sidecar (:8020): `{"status":"ok"}`
- Vite frontend (:4000): HTTP 200

Then logged in through the **real browser UI** — password + a real TOTP QR enrollment (secret read directly
from the live page's DOM, code computed with `pyotp`, not guessed) — to the real Clearing Operations
Dashboard. Commit: fix(scripts) landed alongside this entry.

**Not covered by this fix:** the dashboard's own header shows "Saraswat" demo-data branding regardless of
`--bank-id kbl` — a cosmetic seed-data labelling detail, not touched here. `dev-init.py`'s separate
`apps.api.dev_auth_server` "PLATFORM SUPER ADMIN" banner (a different, parallel auth mechanism from the
`seed_users()` DB accounts fixed here) was not reconciled — both exist, out of scope for this fix.

---

## 2026-09-23 — The same `workflow.sleep()` bug, fixed in the two files flagged as follow-ups

`feedback_workflow.py:302` (`ModelRetrainWorkflow`'s shadow-eval poll loop) and
`platform_health_check_workflow.py:204` (`PlatformHealthCheckWorkflow`'s 60s alert loop) both called
`workflow.sleep(...)`, which doesn't exist in `temporalio==1.7.1` — the identical bug fixed in
`postdated_hold_workflow.py` earlier the same day, flagged there as two open follow-ups. Both are pure polling
loops with no signal to interrupt on, so both are fixed with `workflow.wait_condition(lambda: False,
timeout=...)` wrapped in `try/except asyncio.TimeoutError`, per `.claude/rules/temporal.md`'s Deterministic
Sleep section.

**Same root cause as before, confirmed again:** neither workflow's existing test file ever executed `.run()`
against a real Temporal environment — `test_feedback_workflow.py` covered only `FeedbackEmitWorkflow` (signal
routing, mocked); `test_platform_health_check_workflow.py` covered activities directly and
`run_with_mocks()` (deliberately Temporal-free). Exactly why this shipped in both files undetected.

**TDD, against a real Temporal time-skipping environment (not mocked)** — one new test class per file:
- `TestModelRetrainWorkflowRealRun` (`test_feedback_workflow.py`): fake `dispatch_retrain_job` /
  `run_shadow_evaluation` (returns `new_accuracy=0.95` so the poll loop exits after exactly one sleep
  interval, keeping the test fast under the real 7-day max wait) / `promote_model`. Confirmed the workflow
  reaches `promote_model` — meaning the sleep line actually executed — instead of failing the workflow task.
- `TestPlatformHealthCheckWorkflowRealRun` (`test_platform_health_check_workflow.py`): fake all 5 check
  activities returning `needs_alert=False`; advance the time-skipping server 150s past one 60s tick; assert
  the workflow is still healthily `RUNNING` (not failed) and no `WorkflowTaskFailed` event exists in history;
  cancel it (the workflow is `while True` by design, a singleton per-bank loop).

**RED confirmed first for both** — same lesson as `postdated_hold_workflow.py`: a plain `await
handle.result()` hangs forever against this bug class (Temporal retries a failing workflow task
indefinitely), so RED used a bounded check (`asyncio.wait_for` + history inspection) instead. For the
health-check workflow, the RED check's own `env.sleep()` call additionally hit an internal RPC timeout —
because a continuously-failing workflow task stalls the time-skipping server's time advancement entirely,
itself a useful confirmation alongside the `AttributeError`. Both GREEN after the fix: 74/74 tests pass in
the two files; wider `tests/modules/cts/workflows/` suite: **1584 passed, 0 regressions**.

**Live-verified against the real (non-accelerated) Temporal docker stack — partially, honestly:** started a
real `PlatformHealthCheckWorkflow` against the real worker; 4 real checks (IET, human review, vault coverage,
scanner fleet) executed and completed successfully against real infra with **zero `WorkflowTaskFailed`
events** over a 150-second real wait. Could not get real-time confirmation of the sleep line itself firing a
second tick — a **separate, newly discovered, unrelated bug** blocked it first: the 5th activity
(`sweep_stuck_workflows`) and, independently, `ModelRetrainWorkflow`'s first activity (`dispatch_retrain_job`)
both got stuck at `ACTIVITY_TASK_SCHEDULED` and never reached `ACTIVITY_TASK_STARTED`, for minutes, despite a
confirmed live poller on the task queue. Reproduced identically with a **completely fresh worker process**
(ruling out simple long-running-worker resource exhaustion). Calling `sweep_stuck_workflows()` directly
(bypassing Temporal) returns correctly in under a second — the activity's own code is not the problem.
Flagged separately, out of scope here (`task_31cafdcb`). The time-skipping test environment above already
gives full, decisive proof of the fix itself; the real-infra run corroborates it as far as the unrelated
dispatch bug allowed it to run.

**Status:** all three known `workflow.sleep()` call sites in this codebase (`postdated_hold_workflow.py`,
`feedback_workflow.py`, `platform_health_check_workflow.py`) are now fixed and test-covered. A new, unrelated
activity-dispatch bug is open (`task_31cafdcb`) — real activity tasks intermittently never reach a confirmed-
polling worker, root cause not yet found.

---

## 2026-09-23 — Activity-dispatch stall root-caused: not a code bug, a Windows/multi-Worker interaction

Follow-up to the previous entry's open finding (`sweep_stuck_workflows` / `dispatch_retrain_job` stuck at
`ACTIVITY_TASK_SCHEDULED` forever). Systematically ruled out, each checked live:

1. **Not a registration gap** — both activities confirmed present via direct introspection of the real
   `_registered_activities()` call the worker actually uses: 94 activities registered, **zero duplicate
   names**, both `sweep_stuck_workflows` and `dispatch_retrain_job`/`run_shadow_evaluation` present. (Note:
   the `ALL_ACTIVITIES` list in `worker.py` that appears to include them is explicitly commented "NOT what
   gets passed to Worker()" — a red herring checked and ruled out first.)
2. **Not Worker Versioning / build-id pinning** — `GET .../task-queues/.../versioning-rules` returned
   `NOT_FOUND`; no rules configured.
3. **Not resource exhaustion** — reproduced identically with a completely fresh worker process.
4. **Not a bug in the activity itself** — calling `sweep_stuck_workflows()` directly (no Temporal) returns
   correctly in under a second.
5. **Not a bug in the activity + Temporal combination either** — the decisive test: ran `sweep_stuck_workflows`
   through a **minimal, isolated single-`Worker()` setup** (its own dedicated task queue, only this one
   workflow + this one activity registered, same activity code, same real Temporal server) — **it completed
   correctly and fast.** This is the first test in this whole investigation that actually isolated the
   variable that matters.

**What's different about the real worker:** `modules/cts/worker.py`'s `run_worker()` runs **four `Worker()`
instances concurrently in one process** (`async with processing_worker, hr_standard_worker,
hr_highvalue_worker, hr_veryhigh_worker:`), plus `asyncio.create_task()` for a Kafka human-review consumer, an
outward-scan trigger, and drop-folder watchers — all sharing one event loop. That same function already
carries this comment, a few lines below where the stall was observed:
> "asyncio.Event.wait() can be cancelled by Temporal's Rust-bridge task dispatch on Windows SelectorEventLoop
> when live workflows are present. Poll in short sleeps instead — functionally equivalent, avoids the issue."

— i.e. a **related Windows/temporalio Rust-bridge asyncio interaction bug was already found and partially
worked around in this exact function**, for a different symptom. Confirmed this Windows Python defaults to
`ProactorEventLoop`, not `SelectorEventLoop` (the comment names). The activity-dispatch stall is very likely
the same underlying class of issue in a different manifestation — multiple concurrent `Worker()` instances
plus background asyncio tasks straining the interaction between temporalio's Rust core and Python's asyncio
event loop on Windows specifically.

**Not yet confirmed:** whether this is Windows-dev-machine-only (this repo's actual production target is
Kubernetes/Linux per `CLAUDE.md` §2.1) or would also affect a Linux deployment — that's the key open question,
since it changes whether this is a real production risk or a dev-environment-only limitation. Re-scoped and
re-flagged (`task_9cdaf7e6`) with this precise framing, replacing the earlier, less-targeted `task_31cafdcb`.
