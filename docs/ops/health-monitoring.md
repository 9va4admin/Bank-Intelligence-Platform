# Platform health monitoring and alert email

The health monitor is `PlatformHealthCheckWorkflow`, one per bank (`cts-platform-health-{bank_id}`), started by the worker at start-up. Every 60 seconds it:

1. **Probes every configured dependency** and records latency: Yugabyte (`SELECT 1`), Redis (`PING`), Temporal, Kafka, Immudb (TCP), Vault, MinIO, the AI services
   (vLLM, signature detector, Indic OCR), CBS and NGCH (HTTP; below 500 counts as answering). Targets come from the same configuration the worker already uses; a dependency
   that is not configured is not probed. Extras (CCTV adapters, a second CBS ...) go in `platform_health.extra_probes` (hot-reloadable JSON list of
   `{component, kind: tcp|http|redis|postgres, target, critical, slow_ms}`).
2. **Judges each component** (`modules/cts/health/state_machine.py`): `DOWN` after 3 consecutive failed probes, back to `OK` after 2 good ones, `SLOW` after 3 consecutive probes over the
   component's latency limit. One blip is not an outage. A standing outage is mailed once and then every 30 minutes, not every minute.
3. Runs the existing checks (IET near-breach, human-review queue, vault coverage, scanner fleet, stuck workflows); a condition that persists is mailed once per repeat interval.
4. Mails the recipients on `DOWN`, reminders, `SLOW`, and recoveries.

The dashboard (**Ops > System Health > Platform components**) reads the monitor's state through `GET /v1/ops/components` and says when the monitor itself has stopped
(no tick for 3 minutes), is not running, or cannot be reached. The monitor restarts itself every 1,000 ticks (continue-as-new), carrying its state.

## Configuration

Thresholds (hot-reloadable, Layer 3, in the Admin console): `platform_health.down_after_failures` (3), `platform_health.recover_after_successes` (2), `platform_health.slow_after` (3),
`platform_health.reminder_every_seconds` (1800), `platform_health.extra_probes`, **`alerts.email_recipients`** (a JSON list or comma-separated; empty means no mail is sent).

### Mail server (deployment settings; set in Helm values or the environment, restart to change)

| Setting | Meaning |
|---|---|
| `SMTP_HOST` | mail server. **Unset means email is off**; no provider is assumed. |
| `SMTP_PORT` | default 587 |
| `SMTP_SECURITY` | `starttls` (default), `ssl`, or `none`. Anything else disables email and logs an error; it never stops the worker. |
| `SMTP_USERNAME` | login (omit for an unauthenticated relay) |
| `SMTP_FROM_ADDRESS` | default: the username |
| secret `smtp.password` | `ASTRA_SECRET_SMTP_PASSWORD` in dev; Vault at `secret/astra/{bank_id}/smtp/password` in production |

**Gmail for now** (until the bank's Postal is available): `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_SECURITY=starttls`, `SMTP_USERNAME=<the sending Gmail address>`,
and the secret set to a Gmail **app password** (the account needs 2-step verification; the normal account password does not work). Moving to the bank's server later is a settings change only.

## What is and is not covered

- Covered: dependency up/down/slow with emails and a dashboard; the monitor's own staleness on the dashboard; persisting conditions mailed at a sane rate.
- **Not covered: a dead monitor cannot email you that it is dead.** If the worker is down, nothing runs the probes; the dashboard shows the monitor as stale or not running, and the Kubernetes
  liveness probes on the worker pods (and the bank's own monitoring) are the backstop. An external watcher is the proper fix.
- Not probed: the physical host, disk and memory, and Kubernetes pod state; those belong to the platform team's own tooling (ASTRA deliberately ships no Prometheus/Grafana, see CLAUDE.md 2.5).
- A Gmail account is a stop-gap: it rate-limits and can be blocked as suspicious; do not rely on it for the pilot.
