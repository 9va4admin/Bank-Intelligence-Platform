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

## Who watches the monitor

The monitor runs in the worker, so a dead worker cannot email about itself. The **API process runs a watchdog** (`modules/cts/health/watchdog.py`) that asks Temporal every 60 seconds
whether the monitor has ticked in the last 3 minutes, and mails the same recipients (P0, `health_monitor`) if it has not, or cannot be reached; and mails when it is back. The worker and the API are
separate processes and pods, so one dying does not silence the other. If both die, the Kubernetes liveness probes and the bank's own monitoring are the last backstop.

## Other checks

- **Host disk and memory** (of the machine the monitor runs on): probes `disk` and `memory`, non-critical (P1), limits `platform_health.disk_max_percent` / `memory_max_percent` (90), switch off
  with `platform_health.host_probes_enabled`. Add more paths with an `extra_probes` entry of kind `disk` (`target` = path, `limit` = percent).
- **WhatsApp**: set `WHATSAPP_API_URL`, `WHATSAPP_PHONE_NUMBER_ID`, secret `whatsapp.access_token`, and list phones in `alerts.whatsapp_recipients`. Only P0 goes to WhatsApp by default
  (`alerts.whatsapp_min_priority`). Meta requires pre-approved templates named `astra_platform_health_alert` (body: severity, component, message) and `astra_platform_health_recovered`
  (component, how long down, message).
- **Mail security**: certificates are always verified (STARTTLS and SSL). A bank with a private CA sets `SMTP_CA_FILE` to its PEM file.

## Prove it works: one command

```
SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_SECURITY=starttls SMTP_USERNAME=you@gmail.com ASTRA_SECRET_SMTP_PASSWORD=<app password> BANK_ID=<bank> ASTRA_SECRETS_BACKEND=env python scripts/send_test_alert.py --to you@gmail.com
```

It sends a test mail with the worker's exact settings and, if it fails, says why (server unreachable, certificate not trusted, login refused). Exit code 0 means the server accepted the message.

## What is and is not covered

- Covered: dependency up/down/slow with emails and a dashboard; the monitor's own death (API watchdog); host disk and memory; WhatsApp for P0; persisting conditions mailed at a sane rate;
  verified TLS and login against a real TLS+AUTH server (tests); Vault seal state on the system page even without a Vault client.
- Not covered: pod/node state in Kubernetes (the platform team's tooling; ASTRA ships no Prometheus/Grafana, CLAUDE.md 2.5). Disk and memory are the monitor host's, not every node's.
- Not proven here: delivery to a real Gmail inbox (needs your app password; run the command above) and to real WhatsApp (needs the bank's Meta approval). Both are exercised against local stand-ins
  that speak the real protocol.
- A Gmail account is a stop-gap: it rate-limits and can be blocked as suspicious; do not rely on it for the pilot.
