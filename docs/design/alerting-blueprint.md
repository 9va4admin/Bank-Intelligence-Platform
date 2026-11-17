# ASTRA Alerting and Notification: Blueprint

Status: proposal for sign-off. Nothing in sections 3 to 12 is built unless marked **[built]**.
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

### Phases (each ends with live evidence in `docs/e2e-test-evidence.md`)

| Phase | Contents | Exit criteria |
|---|---|---|
| **1. Trustworthy core** (before any pilot) | Incident table and dedup; audit before/after (section 6); outbox, retry and fallback; routing matrix backend with defaults from the taxonomy; richer templates (text and HTML); delivery log API; channel health probe | Kill the mail server mid-incident: alert falls back, audit shows every attempt; Immudb down: P0 still sent, audit backlog drains after; duplicate probes produce one incident |
| **2. People and control** | Alert inbox, routing and on-call screens, ack and escalation workflow, contacts with verification and opt-in, test-send, silences | A P0 unacknowledged for N minutes reaches the next level; ack stops it; a non-admin cannot change routing without a checker |
| **3. Scale and integration** | Grouping, digests, quiet hours, SMS, webhook/ITSM, SIEM syslog, regulatory timers, heartbeat and fire drills | Storm of 20 failures yields one incident and one summary; ITSM ticket created and closed by webhook |
| **4. Insight** | MTTA/MTTR and noise reports, tuning suggestions | Monthly report generated from the delivery log |

## 13. Decisions needed from the bank owner

1. **One matrix per bank, or per processing unit / SMB as well?** Recommendation: per bank with optional per-PU and per-SMB overrides (matches the SB/SMB model).
2. **Is acknowledgement and escalation in the first release?** Recommendation: yes; it is what makes P0 trustworthy, and it is Phase 2, right after the core.
3. **Which channels are mandatory for go-live?** Recommendation: email and in-app bell mandatory, WhatsApp optional (needs Meta approval), SMS if the bank already has DLT, webhook if they run an ITSM.
4. **Who owns the incident taxonomy defaults** (`owning_team` to people)? Recommendation: bank IT admin at onboarding, from a template we ship.
5. **Reporting windows for regulatory incidents**: from the bank's compliance officer, entered as configuration.
6. **Gmail exception**: confirm it is pilot-only and set its end date.
7. **Timezone and holiday calendar** source for schedules.

## 14. Test plan (TDD, real systems where possible)

Unit: matching, escalation timing (time-skipping Temporal), dedup and grouping, silences, template rendering and escaping, policy validation invariants. Integration against real stand-ins that speak the protocol: SMTP with TLS and login (exists), WhatsApp HTTP stub (exists), webhook receiver, Immudb (never mocked). Live: outage and recovery drill on the dev stack, mail server kill, Immudb kill, worker kill with the watchdog, alert storm, acknowledgement through the UI in the browser pane. Coverage targets follow the project rules (95% on workflow activities).
