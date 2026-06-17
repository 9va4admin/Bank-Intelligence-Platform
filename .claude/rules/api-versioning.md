# API Versioning Rules (ASTRA — Multi-Bank On-Prem)

## Why This Matters More Than SaaS
In SaaS you force upgrades. In ASTRA, Bank A may be on chart v1.2 and Bank B on v1.5.
Both are calling your API simultaneously. You cannot remove v1 until every bank has moved.
A deprecated endpoint must remain alive until the last bank on that version upgrades.

---

## Versioning Scope

| Surface | Versioned? | How |
|---|---|---|
| Public API (api-gateway) | YES | URL prefix `/v1/`, `/v2/` |
| Internal service-to-service | NO | Istio handles; breaking changes = new service deploy |
| Kafka event payloads | YES | `schema_version` field in every event envelope |
| Temporal workflow inputs | YES | `InputV1`, `InputV2` Pydantic models |
| Helm chart values schema | YES | `astra.chart_version` in bank values file |
| OPA Rego policies | YES | `policy_version` in YugabyteDB `policy_versions` table |

---

## URL Versioning Rules

```
/v1/cts/inward/{id}/submit          ← current
/v2/cts/inward/{id}/submit          ← new version (when breaking change needed)

Rules:
- ALL public routes start with /v{n}/
- Version number is an integer — no /v1.1/ or /v1-beta/
- Both /v1/ and /v2/ run simultaneously until v1 sunset date
- v1 is NEVER removed until all banks confirm migration to v2
```

---

## What IS a Breaking Change (requires new version)

```
BREAKING — must create /v2/ route:
✗ Removing a field from response
✗ Renaming a field in request or response
✗ Changing a field type (string → int, optional → required)
✗ Changing URL path structure
✗ Removing an endpoint entirely
✗ Changing authentication mechanism
✗ Changing error response structure
✗ Adding a required request field

NOT BREAKING — safe to add in /v1/:
✓ Adding a new optional field to response
✓ Adding a new optional field to request (with documented default)
✓ Adding a new endpoint (new URL, not changing existing)
✓ Changing internal implementation (same input/output contract)
✓ Performance improvements
✓ Bug fixes that don't change the response schema
```

---

## Implementing a Breaking Change (Step-by-Step)

```python
# Step 1 — Create v2 router alongside v1 (never delete v1)
# apps/api/routers/cts.py

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])
router_v2 = APIRouter(prefix="/v2/cts", tags=["CTS v2"])

# Step 2 — v2 has new contract
@router_v2.post("/inward/{instrument_id}/submit", response_model=ChequeSubmitResponseV2)
async def submit_inward_v2(instrument_id: str, body: ChequeSubmitRequestV2, ...):
    ...

# Step 3 — v1 stays alive, adds deprecation headers
@router_v1.post("/inward/{instrument_id}/submit", response_model=ChequeSubmitResponseV1)
async def submit_inward_v1(
    instrument_id: str,
    body: ChequeSubmitRequestV1,
    response: Response,
    ...
):
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2027-06-01"       # minimum 6 months from announcement
    response.headers["Link"] = (
        f'</v2/cts/inward/{instrument_id}/submit>; rel="successor-version"'
    )
    response.headers["Warning"] = '299 - "This endpoint is deprecated. Migrate to /v2/."'
    # Delegate to v2 logic internally — don't duplicate business logic
    v2_result = await submit_inward_v2_logic(instrument_id, migrate_request_v1_to_v2(body))
    return migrate_response_v2_to_v1(v2_result)

# Step 4 — Register BOTH routers
app.include_router(router_v1)
app.include_router(router_v2)
```

---

## Pydantic Model Versioning

```python
# models/requests.py — keep old models, add new ones
class ChequeSubmitRequestV1(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    image_url: str
    # V1 had no bank_id in body (was inferred from JWT)

class ChequeSubmitRequestV2(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    image_url: str
    bank_id: str              # V2 requires explicit bank_id in body
    clearing_zone: str        # V2 adds clearing zone (breaking — was not in V1)

# Migration helper — keeps v1 route logic thin
def migrate_request_v1_to_v2(v1: ChequeSubmitRequestV1, bank_id: str) -> ChequeSubmitRequestV2:
    return ChequeSubmitRequestV2(
        instrument_id=v1.instrument_id,
        image_url=v1.image_url,
        bank_id=bank_id,          # backfill from JWT claim
        clearing_zone="DEFAULT",  # v1 had no zone concept — safe default
    )
```

---

## Kafka Event Versioning

```python
# Every Kafka event envelope must carry schema_version
class KafkaEventEnvelope(BaseModel):
    event_id: str           # UUIDv7
    schema_version: str     # "1.0", "2.0" — never omit
    event_type: str
    bank_id: str
    payload: dict           # versioned payload

# Consumer must handle both versions during migration window:
async def process_event(envelope: KafkaEventEnvelope):
    if envelope.schema_version == "1.0":
        payload = ChequeInwardEventV1.model_validate(envelope.payload)
        payload = migrate_event_v1_to_v2(payload)
    elif envelope.schema_version == "2.0":
        payload = ChequeInwardEventV2.model_validate(envelope.payload)
    else:
        raise UnknownSchemaVersionError(envelope.schema_version)
```

---

## Compatibility Matrix (Mandatory Tracking)

File: `docs/api/compatibility-matrix.md` — updated on every release.
CI fails if a version is removed without this file being updated.

```markdown
| Endpoint | V1 Status | V2 Status | V1 Sunset Date | Banks still on V1 |
|---|---|---|---|---|
| POST /cts/inward/{id}/submit | DEPRECATED | CURRENT | 2027-06-01 | kotak-mah, hdfc-bank |
| GET /cts/decisions/{id} | CURRENT | — | — | all |
| POST /ej/inward/log | DEPRECATED | CURRENT | 2027-03-01 | none — safe to remove |
```

---

## Deprecation Lifecycle

```
PHASE 1 — Announce (at release N)
  - /v2/ route added
  - /v1/ route gets Deprecation + Sunset headers
  - Release notes call out: "v1 deprecated, migrate by {date}"
  - All bank IT admin contacts notified via notification-service
  - compatibility-matrix.md updated

PHASE 2 — Monitor (releases N to N+2, minimum 6 months)
  - Grafana dashboard shows v1 vs v2 call volume per bank
  - Banks still on v1 get monthly reminder notifications
  - ASTRA support tracks which banks are blocking on migration

PHASE 3 — Sunset (release N+2 or after 6 months, whichever is later)
  - Confirm zero v1 traffic in Grafana for all banks
  - Remove /v1/ route
  - Remove v1 Pydantic models
  - Update compatibility-matrix.md: mark V1 as REMOVED
  - CI now flags any reference to removed version as BLOCKER

MINIMUM SUNSET WINDOW: 6 months or 2 ASTRA chart releases — whichever is longer.
Early sunset requires written sign-off from all affected bank IT admins.
```

---

## Forbidden Patterns
- Removing a response field from an existing versioned endpoint
- Changing a field from optional to required in an existing version
- Adding business logic directly in a v1 route (put logic in shared service, call from both)
- Deleting v1 route while any bank's compatibility-matrix entry shows "in use"
- Setting Sunset date less than 6 months from deprecation announcement
- Kafka events without `schema_version` field
