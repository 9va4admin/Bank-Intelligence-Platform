# API Versioning Rules (ASTRA — Multi-Bank On-Prem)

## Why This Matters More Than SaaS
Bank A may be on chart v1.2, Bank B on v1.5 — both calling your API simultaneously. You cannot remove v1 until every bank has migrated.

## Versioning Scope

| Surface | Versioned? | How |
|---|---|---|
| Public API (api-gateway) | YES | URL prefix `/v1/`, `/v2/` |
| Internal service-to-service | NO | Istio handles; breaking changes = new service deploy |
| Kafka event payloads | YES | `schema_version` field in every event envelope |
| Temporal workflow inputs | YES | `InputV1`, `InputV2` Pydantic models |
| Helm chart values schema | YES | `astra.chart_version` in bank values file |
| OPA Rego policies | YES | `policy_version` in YugabyteDB `policy_versions` table |

## URL Versioning Rules
- All public routes start with `/v{n}/` (integer only — no `/v1.1/` or `/v1-beta/`)
- Both `/v1/` and `/v2/` run simultaneously until v1 sunset date
- v1 is NEVER removed until all banks confirm migration to v2

## What IS a Breaking Change (requires new version)

**BREAKING — must create /v2/ route:**
- Removing or renaming a field in request or response
- Changing a field type, or optional → required
- Changing URL path structure or removing an endpoint
- Changing authentication mechanism or error response structure
- Adding a required request field

**NOT BREAKING — safe to add in /v1/:**
- New optional field in response or request (with documented default)
- New endpoint (new URL, not changing existing)
- Internal implementation changes (same input/output contract)
- Bug fixes, performance improvements

## Implementing a Breaking Change

1. Create `router_v2` **alongside** `router_v1` — never delete v1
2. v2 has the new contract; v1 stays alive and adds these headers: `Deprecation: true`, `Sunset: {date}` (min 6 months from announcement), `Link: </v2/path>; rel="successor-version"`, `Warning: 299 - "This endpoint is deprecated."`
3. v1 route delegates to v2 logic internally — never duplicate business logic
4. Register BOTH routers in `main.py`
5. Update `docs/api/compatibility-matrix.md`

**Pydantic:** Keep `RequestV1`/`ResponseV1` models; add `V2` models. Write `migrate_request_v1_to_v2()` helper — v1 route stays thin.

**Kafka:** Every event envelope must carry `schema_version: "1.0"` (or `"2.0"` etc.). Consumers dispatch by version during migration window; raise `UnknownSchemaVersionError` for unrecognised versions.

## Compatibility Matrix
File: `docs/api/compatibility-matrix.md` — updated on every release. Columns: `| Endpoint | V1 Status | V2 Status | V1 Sunset Date | Banks still on V1 |`. CI fails if a version is removed without updating this file.

## Deprecation Lifecycle

- **Phase 1 (release N):** `/v2/` added; `/v1/` gets deprecation headers; all bank IT admins notified; matrix updated
- **Phase 2 (N to N+2, min 6 months):** Grafana tracks v1 vs v2 call volume per bank; monthly reminders to banks still on v1
- **Phase 3 (sunset):** Confirm zero v1 traffic for all banks → remove `/v1/` route and v1 models → update matrix as REMOVED

**Minimum sunset window:** 6 months OR 2 ASTRA chart releases — whichever is longer. Early sunset requires written sign-off from all affected bank IT admins.

## Forbidden Patterns
- Removing a response field from an existing versioned endpoint
- Adding business logic directly in a v1 route (put in shared service)
- Deleting v1 while compatibility-matrix entry shows "in use"
- Sunset date less than 6 months from deprecation announcement
- Kafka events without `schema_version` field

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Removed endpoints not referenced in code | pre-commit Check 5 (scans against REMOVED entries in compatibility matrix) | Commit blocked |
| Breaking changes detected before merge | CI `api-compat` stage (`infra/ci-checks/check-api-compatibility.sh`) | PR merge blocked |
| Deprecation headers on sunset routes | CI `api-compat` Check 4: scans deprecated routes for missing headers | PR merge blocked |
| Past sunset dates caught before deploy | CI `api-compat` Check 3: fails if sunset date < today | PR merge blocked |
| Kafka events carry `schema_version` | CI `api-compat` Check 5: Semgrep on Kafka producer calls | PR merge blocked |
| 6-month minimum sunset window | `api-breaking-change` skill enforces when creating deprecation | Session-time enforcement |
