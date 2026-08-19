---
name: project-feedback-loop-audit-2026-08-14
description: Security audit of CTS OCR feedback loop (feedback_workflow.py, feedback_types.py, worker.py, cheque_workflow.py changes) — 2026-08-14
metadata:
  type: project
  modified: 2026-08-14
---

Audit of changes in branch `claude/cool-euler-x02gek` (OCR feedback loop commit `239be0f`).
Modified files: `modules/cts/worker.py`, `modules/cts/workflows/cheque_workflow.py`,
`modules/cts/workflows/feedback_workflow.py`. New file: `modules/cts/workflows/feedback_types.py`.

## CONFIRMED CLOSED from CLAUDE.md §14 open items

All 4 CLAUDE.md open items are genuinely closed in code:
- `rbac.py` fail-open: `bank_type: BankType` required (no default); `permission_level` defaults READ_ONLY
- HumanReviewWorkflow timeout: config-driven via `inp.cts_config.get("human_review_max_wait_minutes", 55)`
- SMB notify: code is wired in `cheque_workflow.py:finalise()` — but see H-1 (import gap)
- `mfa_stores.py` env read: `_ensure_client()` raises RuntimeError, no live env read

## NEW HIGH FINDINGS (2026-08-14)

**H-1: cheque_workflow.py:348 — `mask_amount` called but never imported (NameError)**
- `notify_sub_member_return` args include `mask_amount(inp.presented_amount)` at line ~348
- `mask_amount` is not imported anywhere in cheque_workflow.py
- NameError is silently caught by the surrounding try/except block
- SMB return notifications never fire — HIGH-4 fix is wired but broken by missing import
- Fix: `from shared.utils.masking import mask_amount` at module level

**H-2: feedback_workflow.py:121 — `workflow.info()` passed as DI token**
- `app_state = workflow.info()` in FeedbackAccumulatorWorkflow.run()
- `accumulate_corpus_entry` and `check_retrain_threshold` access `app_state.minio_client` and `app_state.redis_cts`
- `WorkflowInfo` has neither attribute → AttributeError or Temporal serialization error
- Entire corpus accumulation is non-functional → models never retrain
- Fix: Register feedback activities with DI injection via BoundCTSActivities

**H-3: worker.py missing FeedbackEmitWorkflow registration**
- `cheque_workflow.py` (working tree) uses `workflow.start_child_workflow("FeedbackEmitWorkflow", ...)`
- `FeedbackEmitWorkflow` is NOT in `worker.py`'s ALL_WORKFLOWS
- Every FeedbackEmitWorkflow started by a cheque will stay pending/timeout in Temporal
- OCR feedback signals never processed → same outcome as H-2: models never retrain
- Fix: Add FeedbackEmitWorkflow to ALL_WORKFLOWS in worker.py

**H-4: security_violations.py:65-69 — In-memory SuspensionStore not shared across pods**
- SuspensionStore uses `set()` in process memory — not persisted, not shared
- ASTRA runs active-active 2+ pods; a suspended user can route to any other pod and bypass
- The YugabyteDB write (lines 248-278) persists the violation event but not the suspension flag
- is_suspended() reads only in-memory — doesn't query DB
- Fix: Move suspension check to query YugabyteDB platform.security_violations for is_suspended

## MEDIUM FINDINGS

**M-1: scanner_configs.py:267,396,463 and ifsc/repository.py:72-150 — SELECT ***
- database.md forbids SELECT * on any table; explicit column list required
- scanner_configs contains drop_folder_path (filesystem path); ifsc_registry has routing data
- Fix: Replace with explicit column lists

**M-2: ifsc/repository.py:149 — LIMIT {limit} directly interpolated**
- `LIMIT {limit}` uses f-string interpolation instead of `$n` parameterization
- `limit` is typed int so no injection possible, but violates parameterization rule
- Fix: Add `LIMIT ${idx}` and append `limit` to params

**M-3: feedback_activities.py:257,311,374 — config_service.get_secret() for URL**
- MLflow API URL fetched via `get_secret()` — a URL is not a secret
- Should use `config_service.get()` (platform config) not `get_secret()` (Vault path)
- Could silently fail if URL not in Vault secret path

## LOW FINDINGS

**L-1: mfa.py:68-93 — No TOTP replay prevention**
- `verify_code` with window=1 allows same code valid for 90 seconds
- No used-code tracking; same code reusable within window
- Fix: Store last-used TOTP step per user; reject duplicate step

**L-2: FeedbackEmitWorkflow defined in feedback_workflow.py but dead code**
- Class defined, not registered with worker, `FeedbackEmitWorkflow` import in cheque_workflow.py may be unused
- Creates confusion about the feedback mechanism architecture

## What this audit confirmed is solid

- All ASTRA-01 through ASTRA-04 findings remain closed (no regressions)
- IET watchdog wiring in cheque_workflow.py — correct, watchdog spawned first
- JWT RS256 + algorithm pinning — correct
- CSRF double-submit pattern — correct
- Middleware ordering in main.py — AuthenticationMiddleware outermost, sets bank_id before RateLimitMiddleware reads it
- Demo router gated to dev/staging only (main.py:373-374)
- mfa_stores.py VaultTOTPSecretStore correctly requires injected vault client
- No hardcoded passwords/secrets/tokens in any new files
- FeedbackEmitInput.account_suffix uses last 4 digits only (not full account number)
