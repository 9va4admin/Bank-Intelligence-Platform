---
name: astra-02-fix-status
description: Status of the ASTRA-02 CRITICAL pentest finding (IET watchdog blind CONFIRM + no NGCH/audit filing) across review rounds
metadata:
  type: project
---

ASTRA-02 (CRITICAL, from the 2026-07-11 white-box pentest) was: `ChequeProcessingWorkflow.run()`
never called `file_to_ngch`/`write_audit` on any of its 8 exit paths; `IETWatchdogWorkflow`
hardcoded `decision="CONFIRM"` at its emergency-file call site regardless of the real decision;
`HumanReviewWorkflow` had no `@workflow.defn`/`@workflow.run`/`@workflow.signal` at all despite
`apps/api/routers/cts.py` already signalling it in production. Root cause: every test in
`tests/modules/cts/workflows/test_{cheque_workflow,iet_watchdog,human_review_workflow}*.py`
only exercised `run_with_mocks()`, never the real Temporal entry points.

**Round 1 fix (reviewed 2026-07-13, commit not yet captured at review time):** Added
`decision_ready`/`filing_complete` signals to `IETWatchdogWorkflow`; added full `@workflow.defn`
to `HumanReviewWorkflow` with a real `run()` that signals the sibling watchdog before filing;
added a `finalise()` closure in `cheque_workflow.py` that every exit path now routes through,
signalling the watchdog + filing + auditing for STP paths, and starting `HumanReviewWorkflow`
as an `ABANDON` child for the HUMAN_REVIEW path. Also fixed a pre-existing crash: `synthesise_decision`
was called with 3 positional args to `workflow.execute_activity()` (only 1 positional arg is
valid — needs `args=[...]`) — this masked all the deeper issues below, since no cheque could
reach a real decision before this fix regardless of the other three bugs.

**The 3 original bugs are genuinely closed.** The fix also added real
`WorkflowEnvironment.start_time_skipping()` tests exercising the actual `@workflow.run` methods
(not just `run_with_mocks()`) — a direct, correct response to the pentest's root-cause criticism.
`ParentClosePolicy.ABANDON` on the `HumanReviewWorkflow` child spawn is correct (the only policy
that lets review survive the parent returning immediately — same pattern already used for the
watchdog spawn). Workflow ID naming is consistent across all 3 files + the API router
(`cts-{bank_id}-{instrument_id}`, `cts-iet-*`, `cts-humanreview-*`).

**4 new CRITICAL gaps surfaced by this review, all newly *reachable* because of this exact fix**
(latent before, since the workflow crashed on the `synthesise_decision` positional-args bug
before reaching any of them):

1. `IETWatchdogWorkflow.run()`'s `except Exception: return IETWatchdogResult(outcome="SAFE", ...)`
   around its own emergency `file_to_ngch` call is a bare catch — it cannot distinguish
   `DuplicateFilingError` (genuinely safe, parent already filed) from `NGCHUnavailableError`
   after `_NGCH_FILING_RETRY` exhausts all 3 attempts (a genuine, unreported IET breach — NGCH
   was down and nothing ever got filed). Both silently report `SAFE`. Zero logging beyond the
   swallowed exception.
2. `IETWatchdogWorkflow.run()` never calls `write_audit` on ANY path — not success, not failure.
   `write_audit.py`'s own `_VALID_EVENT_TYPES` set already reserves `CTS_IET_EMERGENCY_FILED` for
   this and it's never used. The single highest-stakes outcome in the system (emergency T-30s
   filing) has zero Immudb audit trail — only a `log.critical` structlog line, invisible to
   `compliance_officer`/`rbi_examiner` roles.
3. `DuplicateFilingError` from a genuine parent-vs-watchdog race is completely unhandled at the
   *parent's own* `file_to_ngch` call sites — `cheque_workflow.py finalise()` and
   `human_review_workflow.py run()` both call `file_to_ngch` with no try/except. Since it's
   non-retryable, this propagates out and fails the whole workflow before `write_audit` is ever
   reached — meaning a legitimate reviewer decision (e.g. RETURN) that loses a race to the
   watchdog's blind-CONFIRM fallback is filed nowhere in the audit trail, and the workflow shows
   as a bare infrastructure FAILURE. Confirmed via test inspection this exact race is untested —
   `_fake_file_to_ngch` in `test_human_review_workflow.py` always succeeds unconditionally, never
   simulates a second-caller 409.
4. Kill-switch dual-checkpoint backstop (RBI mandate, "supersedes ALL gates" per `decision.py`'s
   own docstring — see [[project_kill_switch]] in the user's cross-session memory) is entirely
   dark on the real `run()` path: `detect_alteration` is called without `kill_switch_status`;
   `AlterationActivityResult.kill_switch_mode/scope` is never forwarded into `DecisionInput`; and
   `synthesise_decision`'s `args=[DecisionInput(...), inp.cts_config]` never includes
   `kill_switch_status`/`opa_client`. This is NOT the same class of gap as the already-flagged
   "activities take `=None` DI defaults with no worker-side injection" — `kill_switch_status` is
   per-call time-varying data, not a static service dependency, so it needs an explicit lookup
   step threaded through `run()`, not a `functools.partial` binding at Worker construction.

HIGH: `HumanReviewWorkflow`'s `_TIMEOUT_SECONDS = 55*60` is a flat constant, not derived from
`inp.iet_deadline` (whose field comment literally says "for display in ops workstation" — it's
genuinely unused for the wait logic). Safe only when IET is the full 180-minute default;
`ngch_adapter.py`'s own docstring establishes per-instrument `iet_deadline` from NPCI's PXF
`ItemExpiryTime` is authoritative and can be shorter. `push_to_review_queue`'s
`workflow.execute_activity` call is the only one across all 3 files with no explicit
`retry_policy=` — relies on Temporal's implicit unlimited-retry default, risking an indefinite
stall on the workflow's first step during a Kafka outage. SMB notification/ledger side effects
(`notify_sub_member_return`, `emit_batch_ledger_update`) are implemented and tested in
`run_with_mocks()` but never called from the real `run()` — same "mock diverges from real
entry point" pattern as ASTRA-02 itself, found in a second dimension of the same file.

Next review of this area should verify: (a) items 1-4 fixed with a real concurrent-race test
(mock `file_to_ngch` succeeding once then raising `DuplicateFilingError` on retry), (b) whether
kill_switch_status/opa_client wiring was added as a preceding workflow step, (c) whether
`_TIMEOUT_SECONDS` was made IET-deadline-aware.
