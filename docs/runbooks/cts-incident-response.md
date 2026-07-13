# CTS Incident Response — IET Watchdog, Filing Races, Kill-Switch

> **Audience:** ASTRA support engineers, bank `bank_it_admin`, `ops_manager`
> **Classification:** Confidential — banking grade
> **Last updated:** July 2026 (covers the July 2026 ChequeProcessingWorkflow /
> IETWatchdogWorkflow / HumanReviewWorkflow filing-and-audit fix)
> **Scope:** This runbook covers the specific safety mechanisms in the CTS
> drawee (inward) pipeline — the IET watchdog, the reviewer/watchdog filing
> race, and the RBI Vision AI kill switch. It is not a general incident
> management framework; for platform-wide incident process see the bank's
> own ITSM tooling per the onboarding runbook (§7, change management).

---

## 1. How to Tell What Actually Happened

Every event in this runbook writes a `write_audit` record to Immudb (queryable
via `GET /v1/audit/events?event_type=...` or the Decisions Log UI, §4.4 of the
user manual) and, where noted, a WhatsApp/email notification per
`shared/messages/locales/messages.yaml`'s routing for that event type.

| Event type | Severity | Notified? | What it means |
|---|---|---|---|
| `CTS_WF_IET_WATCHDOG_FIRED` | CRITICAL | Yes | The watchdog, not the normal pipeline, filed this cheque's decision — see §2 |
| `CTS_WF_HUMAN_CONFIRMED` | INFO | No | Reviewer confirmed within the 55-min window — normal |
| `CTS_WF_HUMAN_RETURNED` | WARN | Yes | Reviewer returned within the 55-min window — normal |
| `CTS_WF_REVIEW_TIMEOUT` | ERROR | Yes | No reviewer acted within 55 minutes — auto-returned, see §3 |
| `CTS_WF_HUMAN_REVIEW_QUEUED` | WARN | No | Cheque routed to human review, awaiting a reviewer |
| `CTS_KS_ENGAGED` / `CTS_KS_RELEASED` | CRITICAL / WARN | Yes | Kill switch toggled — see §4 |
| `CTS_KS_APPLIED_KC` / `CTS_KS_APPLIED_KP` | WARN | No | Kill switch was active for this specific cheque |
| `CTS_KS_BACKSTOP_TRIGGERED` | WARN | No | Kill switch activated *during* this cheque's processing — see §4.2 |

An `IETWatchdogWorkflow` that fails outright (not just fires) is a distinct,
more serious case — see §2.3.

---

## 2. The IET Watchdog Fired

**What this means:** for the specific cheque named in the alert, the normal
filing path (`ChequeProcessingWorkflow` directly, or `HumanReviewWorkflow` if
it went to human review) did not complete filing before T-30 seconds. The
watchdog — a structural, non-disableable backstop spawned before any other
processing begins — filed on its own.

### 2.1 First question: what decision did it file?

Check the `decision` field in the `CTS_WF_IET_WATCHDOG_FIRED` audit payload,
and the `signalled` field:

- **`signalled: true`** — the normal pipeline *had* reached a real decision
  (CONFIRM or RETURN) and had already told the watchdog via `decision_ready`,
  it just hadn't finished the NGCH round-trip yet. The watchdog filed the
  *correct* decision. This is a **latency** incident, not a correctness one —
  investigate why filing was slow (NGCH latency, retry exhaustion on a
  transient error), not the decision itself.
- **`signalled: false`** — nobody ever told the watchdog what the real
  decision was; it fell back to CONFIRM. This is the RBI "deemed approval"
  outcome and is only reached when the entire pipeline (fraud scoring, CBS
  checks, human review queueing) never completed at all before T-30s. This
  is a **severe** incident — investigate why the whole workflow stalled
  (Temporal worker down, activity crash-looping, CBS/vault total outage).

### 2.2 Second question: is this a duplicate-filing race, and is that safe?

If both the normal path and the watchdog attempt to file, NGCH's idempotency
key (the parent workflow ID) resolves it: whichever filed first wins, the
second gets a 409 (`DuplicateFilingError`), and that side stands down
without erroring. You should see **exactly one** `CTS_NGCH_FILED_CONFIRM` /
`CTS_NGCH_FILED_RETURN` **or** `CTS_WF_IET_WATCHDOG_FIRED` record per
instrument — never both claiming to have filed. If you see two independent
NGCH acknowledgement IDs for the same instrument, that is a genuine
duplicate-filing bug, not a race — escalate immediately (this violates the
platform's exactly-once guarantee).

### 2.3 The watchdog itself failed (not just fired)

If `IETWatchdogWorkflow`'s own filing attempt exhausts its 3 retries against
a genuinely unreachable NGCH (not a duplicate — see the `cause_type` field on
the failure-path `CTS_WF_IET_WATCHDOG_FIRED` audit record, `failed: true`),
the workflow raises rather than silently reporting SAFE. This means:

- The workflow shows as **FAILED** in Temporal's own UI/monitoring — this is
  deliberate, so it can never be missed as "just another SAFE outcome."
- **This is the most severe case in this runbook**: the platform's last line
  of defence against an IET breach did not succeed. Escalate to NGCH/NPCI
  connectivity investigation immediately; this is the scenario the entire
  watchdog architecture exists to prevent.

---

## 3. Human Review Timed Out (`CTS_WF_REVIEW_TIMEOUT`)

A cheque sat in the human review queue for 55 minutes with no reviewer
action and was auto-returned. This is a **safe-by-design** outcome (RETURN,
never CONFIRM, on timeout) but indicates a process gap, not a system bug.

**Checklist:**
```
[ ] Was the item visible in the ops workstation queue at all?
      (cross-check CTS_WF_HUMAN_REVIEW_QUEUED fired for this instrument)
[ ] Was a reviewer logged in and assigned to this bank_id / clearing zone
    during the window?
[ ] Was the ops workstation itself reachable (not a platform outage)?
[ ] Check queue depth at the time — was this reviewer overloaded?
```

If the queue-push itself failed (Kafka outage), `HumanReviewWorkflow` still
reaches its 55-minute wait and times out safely — the outcome is the same
RETURN either way, but the *reason* differs (nobody could see it, vs. someone
saw it and didn't act). Check for a `human_review.push_to_queue_failed`
log entry (CRITICAL) around the same timestamp to distinguish the two.

---

## 4. Kill Switch Activated

### 4.1 Expected activation (`CTS_KS_ENGAGED`)

A bank operator or ASTRA support (with bank sign-off) engaged the RBI Vision
AI kill switch. `CTS_KS_APPLIED_KC` / `CTS_KS_APPLIED_KP` will fire for every
affected instrument while it's active — this is expected volume, not an
incident by itself. Confirm the `activated_by` field matches who was
supposed to engage it.

### 4.2 Backstop triggered mid-flight (`CTS_KS_BACKSTOP_TRIGGERED`)

The kill switch is checked **twice** per cheque — once immediately before the
Vision LLM call (`detect_alteration`), once again immediately before the
final decision (`synthesise_decision`) — specifically to catch the case
where the switch was engaged *during* the ~120-second Vision LLM call. If
you see `CTS_KS_BACKSTOP_TRIGGERED`, checkpoint 1 did **not** see the kill
switch active (so Vision AI ran normally) but checkpoint 2 did — the
instrument was intercepted before STP could complete and forced to human
review. This is the backstop working correctly, not a bug. If you are
**not** seeing this event fire for instruments that started processing in
the window between an operator engaging the switch and it fully propagating,
that would indicate the checkpoint-2 lookup itself is not running — escalate
as a P0 (this is an RBI-mandated control).

### 4.3 Kill switch config not taking effect

Kill-switch mode is Layer 3 config (`cts.vision_ai.kill_mode.*`, hot-reload,
no restart needed). If an engage/release isn't reflected within ~30 seconds:
```
[ ] Confirm the config write actually landed (Admin UI → Layer 3 change log)
[ ] Confirm platform.config.changed Kafka event was published
[ ] Check cts-agent-worker logs for kill_switch_lookup.resolved entries —
    absence suggests the lookup activity itself isn't being reached
    (verify the pod is on a build that includes the fix — checkpoint 1 and 2
    lookups were only wired in July 2026; a pod running an older image will
    never call get_kill_switch_status at all, and the kill switch will be
    silently inert regardless of config)
```

---

## 5. Escalation Contacts

Bank-specific — see the bank's own onboarding record
(`infra/helm/values/banks/{bank_id}/platform.yaml`) for the current
`bank_it_admin` and `compliance_officer` contacts. ASTRA support engagement
follows the consent-gated diagnostic MCP model — see
`.claude/rules/diagnostic-mcp.md` for what ASTRA support can and cannot see
without a bank-approved session.
