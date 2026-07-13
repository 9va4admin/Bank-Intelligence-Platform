---
name: feedback-diff-real-vs-mock-entrypoints
description: Review technique — always diff the real @workflow.run against run_with_mocks() line-by-line in this codebase's CTS workflows
metadata:
  type: feedback
---

When reviewing any CTS Temporal workflow file in this codebase, always read BOTH the real
`@workflow.run` method AND its `run_with_mocks()` sibling, and diff them line-by-line for
behavior present in one but not the other — do not assume they're equivalent just because
`run_with_mocks()` passes its tests.

**Why:** This is not a one-off bug, it's a recurring pattern in this codebase. ASTRA-02 itself
(a CRITICAL pentest finding) existed because `ChequeProcessingWorkflow.run()` never called
`file_to_ngch`/`write_audit` while `run_with_mocks()` did the equivalent work correctly and every
test only exercised the mock path. During review of the ASTRA-02 fix (2026-07-13), the same
pattern was found a second time in the same file: `run_with_mocks()` implements and tests
sub-member bank notification (`notify_sub_member_return`) and ledger updates
(`emit_batch_ledger_update`) for SMB-tagged instruments; the real `run()` never calls either,
so `ChequeWorkflowResult.sub_member_notified`/`ledger_updated` are always `False` in production
regardless of `smb_id`. See [[astra-02-fix-status]] for the full finding set from that review.

**How to apply:** For any file with both a real `@workflow.run`/`@activity.defn` entry point and
a `run_with_mocks()`/similar test-harness method, build a mental (or literal, in scratchpad)
checklist of every activity call, every conditional branch, and every side-effect the mock
version performs, then confirm each one has a corresponding call in the real method — not just
that the real method "looks complete" on its own. Pay special attention to activity calls that
take extra optional parameters beyond the primary input model (e.g. `kill_switch_status`,
`opa_client`, `immudb_client`) — check whether the real workflow's `args=[...]` list actually
threads those through, since a call with too few positional args will either crash (as
`synthesise_decision` did before this fix) or silently execute with those params defaulted to
`None`, which can dark out entire safety mechanisms (see kill-switch finding in
[[astra-02-fix-status]]) without ever raising an exception.
