---
name: feedback-review-output-format
description: How this user wants cts-workflow-reviewer findings presented — ranked, code-verified, scope-explicit
metadata:
  type: feedback
---

When this user asks for a review of a CTS workflow fix, they want:

1. **Confirmed issues ranked by severity, explicitly not a general narrative.** They said this
   directly for the ASTRA-02 review (2026-07-13). Lead with a ranked list (CRITICAL/HIGH/MEDIUM/
   INFO), not a prose walkthrough of the diff.
2. **Direct answers to their explicit numbered questions first or clearly folded into the ranked
   findings** — they typically ask 2-4 specific questions (e.g. "does the new signal coordination
   introduce a NEW double-filing risk", "is ParentClosePolicy.ABANDON correct here") alongside a
   general "find anything else" ask. Answer the named questions explicitly, don't bury them in a
   generic finding list without a clear yes/no/verdict.
3. **Every finding must be traceable to actual code they can re-check** — cite the specific file,
   the specific call site, and (where relevant) confirm via the actual test file whether the
   scenario is or isn't covered by an existing test, rather than speculating. This user writes
   very detailed, code-accurate bug reports themselves (see the ASTRA-02 task description, which
   included exact line-level reasoning) and expects review responses to match that rigor.
4. **They explicitly pre-declare what's out of scope and invite disagreement** — e.g. "What was
   deliberately NOT fixed (out of scope, flag if you disagree)". Respect their stated scope
   boundaries as the primary framing, but if a genuinely severe issue falls just outside their
   named categories (e.g. a fraud/regulatory-control gap when they asked about IET/exactly-once/
   audit-completeness), still raise it — just label it clearly as adjacent-to-scope rather than
   folding it in as if it were squarely what they asked about.
5. **Acknowledge what's genuinely fixed/correct, not just gaps** — this user's own task
   descriptions already show they've done real verification work before asking for review (they
   confirm bugs "by direct code reading before any fix"); mirroring that by explicitly confirming
   what checks out (e.g. workflow ID naming consistency, ABANDON policy correctness, vault-miss
   routing integrity) is useful signal, not filler.
