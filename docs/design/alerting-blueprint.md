# ASTRA Alerting and Notification: Blueprint

Status: decisions in section 13 resolved 2026-11-17; sections 15 to 21 added the same day. Nothing in sections 3 to 12 is built unless marked **[built]**.
Scope: platform health, IET/queue/vault/scanner alerts, and any future operational alert. Not customer notifications.

## 1. What an alert is, and the rules it must obey

An alert is an operational obligation: somebody must know, in time, and we must be able to prove who was told, when, and what they did.

1. **Every alert is audited before and after it is sent** (Immudb, HSM-signed). No exceptions.
2. **Never lost**: a failed send is retried, then moved to another channel, then shown as undelivered. Never silent.
3. **Never a flood**: one problem is one incident, not one mail per minute or one per component.
4. **Right person, right channel, right time**: decided by a bank-owned policy, not code.
5. **Acknowledgeable**: an unacknowledged P0 escalates. Acknowledging stops the escalation.
6. **Works when things are broken**: the alert path must not depend on the thing that is down.
7. **No PII, no account numbers, no amounts** in any alert (masking rules apply).
8. **Bank-configurable without code or restart** (Layer 3, maker-checker, audited).
9. **Data stays inside the bank** in production. Gmail is a development/pilot stop-gap only (section 10).

## 2. What exists today, and what is missing

| Area | Today | Gap |
|---|---|---|
| Detection | Probe state machine (down/slow/recovered, flap control), existing checks (IET, queue, vault, scanner, stuck workflows), disk/memory, dead-monitor watchdog **[built]** | No per-alert definition catalogue; thresholds only |
| Incident state | Held in the monitor workflow's memory **[built]** | Not durable or queryable; no history, no ack, no owner |
| Routing | One flat recipient list; WhatsApp P0 floor **[built]** | No severity/component/time matrix, no on-call, no escalation |
| Content | Two plain-text templates **[built]** | No impact, runbook, links, time, incident id; no HTML; no per-channel variants |
| Delivery | Email (verified TLS + login), WhatsApp, in-app bell channel **[built]** | No outbox, no delivery receipts, no fallback chain, no SMS/webhook/ITSM |
| Audit | None | Entire section 6 |
| UI | Components panel on System Health **[built]** | No routing, on-call, templates, silences, incident inbox, delivery log |
| Meta-monitoring | Watchdog for the monitor **[built]** | No channel-health check, no daily heartbeat, no outbox-depth alert |
| Compliance | Incident taxonomy fields exist in `messages.yaml` (class, default severity, owning team, regulatory_reportable) | Nothing consumes them |

Reuse, do not rebuild: the state machine, the incident block in the message registry (it already carries `owning_team`, `default_severity`, `regulatory_reportable`, `escalation_trigger`), `generated-incident-alerts.yaml`, `NotificationDispatcher` with its debouncer and bell channel, and `apps/notification_service` (check its overlap with the dispatcher before adding anything; one delivery service, not two).

## 3. Architecture

```
detectors ──► alert engine (Temporal: PlatformHealthCheck + new AlertIncidentWorkflow per incident)
 probes            │  1. open/update incident (dedup key)           ──► Yugabyte  platform.alert_incidents
 checks            │  2. audit ALERT_RAISED                          ──► Immudb
 watchdog          │  3. resolve routing policy (+ on-call, silences)
                   │  4. audit DISPATCH_INTENDED (per target+channel)
                   │  5. enqueue to outbox ─────────────────────────► platform.alert_outbox
                   ▼
              delivery worker ──► email / WhatsApp / SMS / webhook / bell
                   │  6. audit DELIVERY_ATTEMPTED / SUCCEEDED / FAILED
                   │  7. retry, then fallback channel, then mark UNDELIVERED (visible, loud)
                   ▼
        incident inbox (UI): ack / comment / resolve / escalate timers (AlertIncidentWorkflow)
```

- One **AlertIncidentWorkflow per open incident** (`cts-alert-{bank_id}-{dedup_key}`): owns escalation timers, re-notification, auto-resolve. State is also written to the database so the UI and reports do not query Temporal.
- **Outbox pattern**: the decision to notify is written to the database first; the delivery worker sends from it. A crash never loses or duplicates a notification.
- Delivery stays behind the one dispatcher/notification service; engines never talk SMTP directly.

## 4. Alert catalogue (what can fire)

A registry entry per alert type, code-registered and bank-tunable:

`alert_id`, `component`, `category`, `default_severity`, `dedup_key` rule, `impact_text` (what stops working for the bank), `runbook` link, `owning_team`, `regulatory_reportable`, `auto_resolve` rule, `repeat_after`, and `message keys` (subject, body).

Severity scale (fixed, bank cannot redefine): **P0** immediate action, service or IET at risk; **P1** degraded, act within hours; **P2** warning/slow; **P3** information/recovery.

Initial catalogue: every component probe (down/slow), IET breach risk, human-review queue depth/wait, vault coverage/stale, scanner offline, stuck workflows, DC failover, model drift thresholds (2/5/8%), audit-chain integrity, certificate expiry (30/7/1 days), secret rotation failure, disk/memory, monitor dead, alert channel failing, NGCH filing failure, backup failure, Kafka lag.

## 5. Routing policy (the matrix)

A bank-owned, ordered rule list. First match wins unless a rule says `continue`.

```
rule:
  match:      severity in [...]   component in [...] | owning_team | category | bank_scope (SB / SMB id)
              schedule: business hours | out of hours | holidays (calendar) | always
  targets:    [ {user | role | group | external address}, ... ]
  channels:   per target and per escalation level, e.g. L1: email+bell; L2 (after 5 min): +WhatsApp; L3 (after 15 min): +SMS to manager
  escalation: [ {after_minutes, targets, channels} ... ]     stops on ack
  repeat:     reminder interval while open
  quiet:      P2/P3 held for digest outside hours; P0/P1 never held
```

- **Targets are people, not raw addresses**: users from User Management (so leaving staff drop out automatically), roles, groups; external addresses allowed.
- **On-call rota**: weekly/shift schedule with overrides and holiday calendar; `role: on_call(ops)` resolves at send time. Gap in rota falls to a configured fallback group; an empty resolution is itself a P0 "nobody to notify".
- **Defaults ship pre-filled** from `owning_team` in the incident taxonomy, so a new bank works on day one and can tune.
- **Safety invariants** (structural, like the policy engine): a P0 always has at least one target and one working channel or the policy is rejected on save; an unset policy falls back to the legacy flat list; nothing a bank configures can switch off P0 audit.
- **Contacts**: each person has verified email (click to verify), verified phone, WhatsApp opt-in recorded with timestamp (Meta requires consent), per-channel preferences within what the policy allows.

## 6. Audit (Immudb)

Events, each with a correlation id = incident id, bank id, actor (in payload; `AuditEvent` has no user field), HSM-signed via the existing `AuditEvent` path:

| Event | When |
|---|---|
| `ALERT_RAISED`, `ALERT_UPDATED`, `ALERT_RESOLVED`, `ALERT_SUPPRESSED` | incident lifecycle |
| `DISPATCH_INTENDED` | **before** sending: who, which channel, which rule matched, which template version |
| `DELIVERY_ATTEMPTED`, `DELIVERY_SUCCEEDED`, `DELIVERY_FAILED` | **after** each attempt: provider response class, attempt number |
| `ALERT_ACKNOWLEDGED`, `ALERT_ESCALATED`, `ALERT_COMMENTED` | human actions |
| `ROUTING_POLICY_CHANGED`, `ONCALL_CHANGED`, `TEMPLATE_CHANGED`, `RECIPIENT_CHANGED`, `SILENCE_CREATED`, `CHANNEL_SETTINGS_CHANGED` | configuration (maker and checker both recorded) |

Rules: recipients are written masked or hashed (`n***@gmail.com`), never the body text with sensitive data; an Immudb outage **never blocks a P0 send**: the audit write is queued durably with unlimited retry (`AUDIT_RETRY`) and a loud `audit_backlog` alert fires; the Yugabyte write that changes an incident emits its audit event immediately after, per the platform rule. "Delivered" means the provider accepted it; true inbox/phone delivery is recorded only where the provider gives a receipt (WhatsApp status webhook), and the record says which kind it is.

## 7. Content

- **Template per (alert type, channel, locale)**, wording only in `messages.yaml`; HTML plus plain-text for email, short text for WhatsApp/SMS, structured payload for webhooks.
- **Subject**: `[ASTRA][P0][bank][component] one-line summary`, so mail rules and phones sort it.
- **Body fields**: incident id, severity, component, when it started (bank timezone and UTC), how long, what is affected (impact), current state, what was checked, last error (masked), **what to do** (runbook link and first three steps), dashboard link, ack instruction, who else was notified, escalation time.
- **Recovery** and **reminder** variants; **digest** variant for P2/P3.
- **No ack-by-link without login**: the link opens the incident page; acknowledging requires a session (signed, expiring links are fine for navigation only).
- WhatsApp: pre-approved Meta templates only; maintain the template map and the approval status per template in config, and fall back to email when a template is not approved.
- **Bank overrides**: branding, signature, extra footer, and wording overrides are Layer 3 with preview, test-send and maker-checker; placeholders validated like the registry.

## 8. Delivery engine

- **Channels**: email, WhatsApp, in-app bell **[built]**; add **SMS** (India needs DLT registration of sender and templates; this is a bank-side prerequisite), **webhook** (ServiceNow/Remedy/SIEM, signed, retried), **syslog/CEF** to the bank's SIEM.
- **Per-channel retry** with backoff (bounded), then **fallback channel** per policy, then `UNDELIVERED` shown on the inbox and escalated one level up.
- **Outbox** with state `PENDING, SENDING, SENT, FAILED, UNDELIVERED`, idempotency key per (incident, level, target, channel) so a retry never double-sends.
- **Flood control**: dedup by key; **grouping** with the dependency map (if Yugabyte is down, the 6 failures that follow are children of one incident with a root-cause hint); storm cap per window with an explicit "N more suppressed" summary; digests for P2/P3.
- **Silences/maintenance windows**: scoped by component and time, require a reason, expire automatically, maker-checker for P0 components, audited, shown in the UI and in the alert mails for anything silenced adjacent to a live incident.
- **Time**: all schedules in the bank's timezone (configurable), India holiday calendar.
- **Latency target**: P0 reaches the first channel in under 60 seconds from detection (probe interval and the 3-failure rule are the other contribution: state this honestly in the UI as "detected after N failed checks").

## 9. Admin UI

All screens theme-aware, wording via `msg()`, SB/SMB scoped (SMB admins see and configure only their own scope within SB-permitted ranges), RBAC below.

1. **Alert inbox**: open and recent incidents; ack, comment, resolve; timeline of notifications and deliveries.
2. **Routing matrix**: grid of severity × component/team to targets and channels; escalation editor; "who would be notified for X" simulator.
3. **On-call**: rota calendar, overrides, fallback group.
4. **Contacts and channels**: verification state, WhatsApp opt-in, per-channel health, last successful send, **Send test** button.
5. **Templates**: per alert and channel with preview in light/dark and test-send.
6. **Silences**: create/extend/end, who and why.
7. **Delivery log**: every attempt, filter by incident, person, channel, status; export.
8. **Thresholds** (existing Layer 3 keys) shown beside the alerts they drive.

RBAC: `ops_manager` proposes, `bank_it_admin` approves (existing maker-checker); `ops_reviewer` sees and acknowledges alerts for their scope; `compliance_officer` read-only on log and audit; `rbi_examiner` read-only, date-scoped; ml_engineer sees AI alerts only.

## 10. Security and compliance

- **Data localisation**: Gmail sends alert text through Google. Acceptable for dev and a pilot only while alerts carry no customer data; the production path is the bank's own mail relay. Record this as a documented exception, with an expiry, in the pilot sign-off.
- **Deliverability**: SPF, DKIM, DMARC set up for the sending domain, or alerts land in spam. A delivery check (send, then confirm) is part of go-live.
- **Secrets**: SMTP and WhatsApp credentials only via Vault; rotation tested; never logged.
- **Regulatory timers**: alerts with `regulatory_reportable` open a compliance task for the `compliance_officer` with a deadline clock (RBI/CERT-In cyber-incident reporting windows; the exact periods come from the bank's compliance officer and are configuration, not code).
- **Retention**: incident and delivery records follow audit retention; Immudb is the legal record, the database is the working copy.
- Injection safety: alert text built from probe errors is escaped for HTML and stripped of control characters; errors never carry credentials (already masked **[built]**).

## 11. Making sure the alerting itself works

- **Channel health probe**: periodic SMTP connect+auth and WhatsApp token check (no message sent); failure raises "alert channel failing" over the other channel.
- **Dead-man heartbeat**: a daily "all quiet" message that must arrive; its absence is the signal (the bank's own monitoring or a second system watches for it).
- **Outbox health**: depth and age of the oldest unsent item alerting at thresholds.
- **Fire drill**: scheduled synthetic P0 to an on-call test group, with acknowledgement tracked; failure is reported to the bank admin.
- **Metrics reported on the dashboard**: time to detect, time to notify, time to acknowledge (MTTA), time to resolve (MTTR), notifications per incident, noisiest alerts (tune or retire them).
- The existing watchdog stays: the monitor, the engine and the delivery worker each have an independent liveness check.

## 12. Compatibility and rollout

- New API under `/v1/ops/alerts/...`; Kafka event `platform.alerts` carries `schema_version`; workflow inputs versioned (`InputV1`); migrations backwards compatible for one version, run as pre-deploy jobs.
- The flat `alerts.email_recipients` and `alerts.whatsapp_*` keys keep working: on first start they become the **default rule** of the matrix, so nothing changes for a bank that does nothing.

### Phases (original; superseded by section 21)

| Phase | Contents | Exit criteria |
|---|---|---|
| **1. Trustworthy core** (before any pilot) | Incident table and dedup; audit before/after (section 6); outbox, retry and fallback; routing matrix backend with defaults from the taxonomy; richer templates (text and HTML); delivery log API; channel health probe | Kill the mail server mid-incident: alert falls back, audit shows every attempt; Immudb down: P0 still sent, audit backlog drains after; duplicate probes produce one incident |
| **2. People and control** | Alert inbox, routing and on-call screens, ack and escalation workflow, contacts with verification and opt-in, test-send, silences | A P0 unacknowledged for N minutes reaches the next level; ack stops it; a non-admin cannot change routing without a checker |
| **3. Scale and integration** | Grouping, digests, quiet hours, SMS, webhook/ITSM, SIEM syslog, regulatory timers, heartbeat and fire drills | Storm of 20 failures yields one incident and one summary; ITSM ticket created and closed by webhook |
| **4. Insight** | MTTA/MTTR and noise reports, tuning suggestions | Monthly report generated from the delivery log |

## 13. Decisions (bank owner, resolved)

| # | Decision | How the design applies it |
|---|---|---|
| 1 | Scope order is **Bank, then PU, then SMB, highest to lower priority** | Three policy levels. **Reading adopted (please confirm):** the bank-level policy is a floor that nothing below can remove. Targets **accumulate** (bank + PU + SMB all get the alert); on any conflict (quiet hours, escalation timing, severity handling) the higher level wins; a PU or SMB may add people, channels, or earlier escalation but may not remove or mute a bank-mandated target. An SMB alert also reaches the sponsor bank's targets (SB sees all); an SMB admin sees and edits only the SMB level. |
| 2 | Ack and escalation are in the first release | Moved into Phase 1b (right after the audited core), not Phase 2. |
| 3 | Mandatory channels: email and the on-screen bell. No mobile app | The bell becomes a real, per-user, persistent inbox (section 16). WhatsApp, SMS, webhook stay optional per bank. |
| 4 | The bank admin configures routing as part of the **Go-Live checklist** | Alerting readiness items are added to the existing Go-Live readiness API and screen; go-live stays blocked until they pass (section 19). |
| 5 | Audit trail must be available **now**, before the regulatory windows are known | Audit is the first thing built (Phase 1a). Any incident can be exported as a signed **evidence pack** (timeline, who was told, when, delivery outcomes, acks, config changes) from day one. The reporting windows themselves are configuration the compliance officer fills in later; nothing waits on them. |
| 6 | Gmail end date unknown | A pilot-exception mechanism that does not need a date (section 19): while mail goes through a public provider the System Health page and the Go-Live checklist show a persistent notice and a weekly reminder; setting the end date is optional, and the notice disappears only when the bank's own relay is configured. |

## 14. Test plan (TDD, real systems where possible)

Unit: matching, escalation timing (time-skipping Temporal), dedup and grouping, silences, template rendering and escaping, policy validation invariants. Integration against real stand-ins that speak the protocol: SMTP with TLS and login (exists), WhatsApp HTTP stub (exists), webhook receiver, Immudb (never mocked). Live: outage and recovery drill on the dev stack, mail server kill, Immudb kill, worker kill with the watchdog, alert storm, acknowledgement through the UI in the browser pane. Coverage targets follow the project rules (95% on workflow activities).

## 15. Findings that change the plan (found by reading the code, 2026-11-17)

1. **The bell icon is fake.** `apps/web/src/shared/layout/AppShell.jsx` renders a hard-coded `MOCK_NOTIFICATIONS` list ("IET risk, 22 minutes remaining", "stop payment detected" ...) to every user. A reviewer can be shown an invented critical alert, and a real one never appears. This must be replaced before anything else is pointed at the bell.
2. **A second routing system already exists**: `shared/notifications/routing.py` (`NotificationRoutingTable`, audit event type to roles to channels, P0 to P3). The alert path I built bypasses it. One policy engine must serve both, or banks will configure two places. Plan: the new matrix supersedes it; its 18 event routes seed the matrix defaults.
3. **A Go-Live readiness API exists** (`apps/api/routers/platform.py`, page `/admin/smoke-test`). Alerting readiness is added there, not as a new checklist.
4. **No failure history is stored**: monitor state lives in workflow memory, so a restart or a continue-as-new loses everything except the current status.

## 16. The bell (in-app notifications): real, per user, persistent

- Table `platform.user_notifications` (bank_id, user_id, incident_id, severity, title, body, action link, created_at, read_at, acked_at). Written by the bell channel at dispatch time and audited exactly like email (intent before, outcome after).
- API: `GET /v1/notifications` (cursor, unread count, filter by severity), `POST .../read`, `POST .../read-all`, `POST .../{id}/ack`. Scoped by the user's bank, PU and SMB.
- UI: badge with real unread count; drawer lists real items; clicking opens the incident or the item. **Unread P0 stays pinned** at the top of every page (not dismissible except by acknowledging) with a configurable sound. Refresh by polling every 15 seconds for P0/P1 users (React Query `refetchInterval`), upgradeable to server-sent events.
- Bell delivery is the **fallback of last resort**: it always works when the web app does, so every alert targeted at a person also lands here regardless of email or WhatsApp outcome.
- No mock data in production builds; demo mode, if kept, is labelled and compiled out (existing SB/SMB demo-toggle rule).
- Also carries non-alert events the routing table already defines (reviewer assignment, escalations) so the bell has one source.

## 17. Failures: where historical data is visible

**What is stored (durable, queryable, not workflow memory):**
- `platform.alert_incidents`: one row per incident (opened, acked, resolved, severity, component, scope PU/SMB, dedup key, impact summary, root-cause category, linked change).
- `platform.component_state_history`: every state transition (OK, SLOW, DOWN) with timestamps, so uptime and downtime are computed from facts, not estimated.
- `platform.alert_deliveries`: every notification attempt (also the delivery log of section 9).
- `platform.change_events`: deployments, config changes (with the maker-checker audit id), kill-switch changes, certificate rotations, so failures can be lined up against what changed.
- Business impact counters during an incident: how many items fell to human review because of the degradation, IET-at-risk count, instruments delayed (counts and buckets only, never account or amount detail).
- Partitioned by month on `opened_at`, indexed on (bank_id, opened_at); hot for 2 years, Immudb copy of the lifecycle events is the 10-year legal record; each history row can be **verified against Immudb** from the UI ("verify integrity").

**Where it is seen (Ops, new "Reliability" area):**
1. **Incident history**: filter by date range, component, severity, PU, SMB, status, owner, root-cause category, free text; open any incident to see the full timeline (detected, notified, acknowledged, escalated, resolved) and who did what.
2. **Component timeline**: a strip per component over 24 hours / 7 / 30 / 90 days, down and slow periods shaded, **change events overlaid**, uptime percentage against the NFR (99.999% clearing hours, 99.99% off-hours).
3. **Analytics**: top failing components, recurring failures (same cause more than N times in 90 days), by hour of day, MTTA, MTTR, noisiest alerts, share caught by probes versus reported by a human (detection gap).
4. **Availability report**: monthly, per bank / PU / SMB, CSV and print-ready PDF, for the bank's operations committee, board and RBI examiner (read-only, date-scoped role already exists).
5. **Evidence pack** per incident: signed export for compliance and regulators.
- RBAC and scope: ops roles see their PU/SMB scope; sponsor bank sees all its SMBs; an SMB sees only its own; compliance officer and examiner read-only; fraud analyst and ML engineer see only their own domain.
- Backfill: what exists today (current component states) is the first history row; nothing earlier can be reconstructed and the UI says so.

## 18. Risk mitigation: how and when it is updated

**Principle:** the system records facts automatically; **only a person declares a risk mitigated**, and a second person verifies it. The system never marks a risk closed on its own.

**Objects**
- **Risk register entry**: id, description, category (availability, capacity, security, vendor, process), likelihood, impact, rating, existing controls, residual risk, owner, next review date, mapped RBI IT framework control (`compliance/rbi-it-framework/control-mapping.yaml`).
- **Post-incident review (PIR)** per incident: root cause (category and narrative), contributing factors, detection gap, customer/IET impact, linked risk entry.
- **Mitigation action**: corrective or preventive, owner, due date, status (OPEN, IN_PROGRESS, DONE, VERIFIED, WONT_FIX with reason), evidence (link, config-change audit id, test result), verification note.

**When things update**
| Trigger | What happens |
|---|---|
| Incident resolved (P0/P1) | PIR task created for the owning team; due in `pir_due_days` (config: P0 3, P1 7). Overdue PIR raises its own alert through the routing matrix. |
| PIR submitted | Actions created with owners and due dates; linked to a risk entry (new or existing); risk rating can be raised, never lowered, by the PIR author. |
| Action owner finishes | Owner sets DONE with evidence. A **different** person (verifier: ops manager or compliance, never the owner) sets VERIFIED or sends it back. Both audited. |
| A config threshold, probe, or routing change is the mitigation | The change's maker-checker audit id attaches to the action automatically as evidence. |
| Quiet period after DONE | System schedules an **effectiveness check**: no recurrence of the same dedup key for `effectiveness_days` (default 30), or a stated measure met (for example disk below 70% for 14 days). Result is recorded as "evidence suggests effective" or "recurred"; a person still confirms. |
| Same failure recurs | Incident auto-links to the earlier PIR and risk; the action is reopened; the risk is flagged "mitigation ineffective"; escalated to the risk owner. |
| Action due date passes | Reminder, then escalation per routing matrix; shown on the risk owner's bell and dashboard. |
| Periodic review | Each risk has a review date (default quarterly); reminder to the owner; the review is recorded even when nothing changes. |
| Every change | Written to Immudb with actor, old and new value, time. |

**Where it is seen**: Risk register page (heat map, filter by owner/status/overdue), action tracker (my actions, overdue, awaiting verification), PIR inside each incident, quarterly risk report (export). The incident history shows, for each failure, which risk it belongs to and whether its mitigations are verified.

## 19. Go-Live checklist: alerting readiness (added to the existing readiness API)

Each item is machine-checked where possible; go-live is blocked until all pass.
1. Bank-level routing has at least one P0 target on two channels (email and bell), and the escalation chain ends at a human.
2. On-call rota covers 24 x 7 with no gap (or a fallback group exists); PU and SMB levels configured or explicitly inheriting.
3. Every target's email is verified; WhatsApp opt-in recorded where used.
4. **Test-send succeeded in the last 7 days** on each enabled channel; the bell test reached each administrator.
5. **Audit path proven**: a sentinel alert wrote its intent and outcome events and both were read back from Immudb.
6. Fire drill run: a synthetic P0 was acknowledged by a human within the target time.
7. Mail relay: either the bank's own relay, or the **pilot exception** is acknowledged (notice stays visible and reminds weekly until the bank relay is set; end date optional, entered when known).
8. SPF/DKIM/DMARC check passes for the sending domain (or is recorded as accepted risk).
9. Routing simulator run for one P0, one P1 and one P2 per component class, results saved.
10. Regulatory reporting windows entered by the compliance officer, or marked "pending", which keeps a visible amber item (it does not block).
11. Risk register seeded from the shipped template; every risk has an owner.
12. No stale silences; no open incident older than its policy limit.

## 20. Other holistic items

- **Disaster recovery**: incident and outbox tables live in Yugabyte (active-active); one incident workflow per incident ID guarantees a single escalation timer even across a DC failover; the watchdog and delivery worker run in both DCs.
- **Time**: stored UTC, displayed in the bank timezone; schedules and holidays in bank timezone.
- **Languages**: all wording through the message taxonomy so Hindi can be added without code.
- **Accessibility**: severity never by colour alone (label and icon); keyboard-operable inbox.
- **Performance**: history queries are partition-pruned and paginated by cursor; the bell endpoint is cached for 15 seconds per user.
- **Privacy**: contact details are PII (encrypted column, masked in logs); alert bodies carry no customer data.
- **Testing**: adds a bell end-to-end test in the browser pane (real notification appears, unread count, ack), history and verification tests against real Yugabyte and Immudb, and a risk-lifecycle test (PIR, action, verify, recurrence reopen).

## 21. Revised phases

| Phase | Contents | Exit evidence |
|---|---|---|
| **1a. Audited core** | Incident, state-history and delivery tables; audit before/after on every send; outbox with retry and fallback; dedup; richer templates; delivery log API; **real bell inbox replacing the mock** | Kill SMTP mid-incident: falls back to bell, audit shows each attempt; kill Immudb: P0 still sent, backlog drains; bell shows real unread count in browser |
| **1b. Routing and ack** | Bank, PU, SMB policy levels with accumulate-and-floor rules, on-call, ack and escalation workflow, routing simulator, migration of `routing.py` routes and flat keys | Unacknowledged P0 reaches level 2 on time; ack stops it; a PU rule cannot remove a bank target |
| **2. Screens** | Alert inbox, routing, on-call, contacts, templates, silences, delivery log, Go-Live alerting checks | Admin completes the checklist in the UI; non-admin cannot change routing without a checker |
| **3. Reliability and risk** | Incident history, component timeline, analytics, availability report, evidence pack, PIR, risk register, action tracker, effectiveness checks | A failure is traced from alert to PIR to verified mitigation; recurrence reopens it |
| **4. Scale and integration** | Grouping, digests, quiet hours, SMS, webhook/ITSM, SIEM syslog, regulatory timers, heartbeat and fire drills | Storm of 20 failures gives one incident; ITSM ticket opened and closed by webhook |
