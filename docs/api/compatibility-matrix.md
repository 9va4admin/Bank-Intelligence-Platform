# ASTRA API Compatibility Matrix
<!-- AUTO-CHECKED by infra/ci-checks/check-api-compatibility.sh -->
<!-- Update this file whenever an endpoint is deprecated, versioned, or removed -->

## How to Read This Table

| Status | Meaning |
|---|---|
| `CURRENT` | Active, supported, no plans to deprecate |
| `DEPRECATED` | Deprecated — Sunset date set, v2 available, migrate now |
| `REMOVED` | Deleted from codebase — calling this will return 404 |

**Sunset Policy:** Minimum 6 months or 2 chart releases (whichever is longer) between DEPRECATED and REMOVED.
Early removal requires written sign-off from all banks listed in "Banks still using" column.

---

## CTS Module Endpoints

### Inward Clearing (Drawee Bank)

| Method | Endpoint | V1 Status | V2 Status | Deprecated In | Sunset Date | Banks Still on V1 |
|---|---|---|---|---|---|---|
| POST | `/cts/inward/{id}/submit` | CURRENT | — | — | — | — |
| GET | `/cts/inward/{id}/status` | CURRENT | — | — | — | — |
| GET | `/cts/decisions/{id}` | CURRENT | — | — | — | — |
| GET | `/cts/human-review/queue` | CURRENT | — | — | — | — |
| POST | `/cts/human-review/{id}/decide` | CURRENT | — | — | — | — |
| GET | `/cts/vault/signature/{account_hash}` | CURRENT | — | — | — | — |

### Outward Clearing (Presentee Bank — Scanner Agent)

| Method | Endpoint | Auth | V1 Status | Notes |
|---|---|---|---|---|
| POST | `/cts/outward/scan/upload-url` | Session JWT | CURRENT | Provision presigned MinIO PUT URLs; `include_uv=true` for UV lamp models |
| POST | `/cts/outward/scan/submit` | Session JWT | CURRENT | Submit scan after image upload; passes s3:// object URLs to OutwardScanWorkflow |
| POST | `/cts/outward/scan/event` | Session JWT | CURRENT | Lightweight non-submit events: DOUBLE_FEED, IQA_REJECTED, PAPER_JAM, COVER_OPEN |
| GET | `/cts/outward/scan-events` | Session JWT | CURRENT | Read scan events for BranchScanMonitor |

### Scanner Fleet & Agent

| Method | Endpoint | Auth | V1 Status | Notes |
|---|---|---|---|---|
| POST | `/cts/scanner/register` | Session JWT (bank_it_admin) | CURRENT | Provision SDK scanner slot |
| POST | `/cts/scanner/{id}/heartbeat` | Bearer machine token | CURRENT | SDK scanner 30s heartbeat → `scanner_registrations` |
| POST | `/cts/scanner/agent/heartbeat` | Bearer machine token | CURRENT | CGO agent 30s heartbeat → `scanner_tokens`; body carries `active_session_id` |
| GET | `/cts/scanner/agent/status` | Session JWT | CURRENT | Returns ACTIVE/IDLE/OFFLINE for a branch; polled by BranchDashboard |
| GET | `/cts/scanner/fleet` | Session JWT (ops_manager+) | CURRENT | SDK scanner fleet overview |
| GET | `/cts/scanner/{branch_ifsc}/status` | Session JWT (ops_manager+) | CURRENT | Per-branch SDK scanner status |
| DELETE | `/cts/scanner/{id}` | Session JWT (bank_it_admin) | CURRENT | Deactivate SDK scanner registration |

## Platform Endpoints

| Method | Endpoint | V1 Status | V2 Status | Deprecated In | Sunset Date | Banks Still on V1 |
|---|---|---|---|---|---|---|
| GET | `/audit/events` | CURRENT | — | — | — | — |
| GET | `/admin/config` | CURRENT | — | — | — | — |
| POST | `/admin/config` | CURRENT | — | — | — | — |

---

## Kafka Event Schema Versions

> EJ topics (`ej.*`) are no longer in this repo — see `9va4admin/atm-ej-platform`.

| Topic Pattern | V1 Schema | V2 Schema | V1 Sunset | Producers still on V1 |
|---|---|---|---|---|
| `cts.inward.{bank_id}` | CURRENT | — | — | — |
| `cts.decisions.{bank_id}` | CURRENT | — | — | — |
| `cts.outward.scan.{bank_id}` | CURRENT | — | — | — |
| `cts.ocr.feedback.{bank_id}` | CURRENT | — | — | — |
| `platform.audit.events` | CURRENT | — | — | — |
| `platform.notifications` | CURRENT | — | — | — |
| `platform.config.changed` | CURRENT | — | — | — |

---

## Deprecation Process (How to Fill This Table)

When deprecating an endpoint:

1. Add `/v2/` route in code
2. Add `Deprecation`, `Sunset`, `Link`, `Warning` headers to `/v1/` route
3. Update this table: set V1 Status → `DEPRECATED`, fill Deprecated In + Sunset Date
4. List all banks currently calling V1 in "Banks Still on V1" column (pull from Grafana dashboard)
5. Send deprecation notice via notification-service to all listed bank IT admin contacts
6. Add entry to release notes under "## Deprecations"

When removing an endpoint:

1. Verify "Banks Still on V1" column shows `none` (confirmed via Grafana)
2. Remove `/v1/` route and V1 Pydantic models from code
3. Update this table: V1 Status → `REMOVED`, clear Sunset Date
4. CI check will now block any code that references this path

---

## Bank Version Registry
<!-- Which bank is on which ASTRA chart version — updated at each bank upgrade -->

| Bank ID | Bank Name | Chart Version | Last Upgraded | Contact |
|---|---|---|---|---|
| example-bank | Example Bank Ltd | 1.0.0 | 2026-06-17 | itadmin@example-bank.com |
