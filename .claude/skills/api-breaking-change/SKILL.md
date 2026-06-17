---
name: api-breaking-change
description: Safely introduce a breaking API change in ASTRA. Covers creating the v2 route, deprecating v1 with correct headers, updating the compatibility matrix, notifying banks, and setting the sunset date.
---

# Skill: Introduce a Breaking API Change

## When to Use
User says: "change the response of {endpoint}", "add required field to {endpoint}", "rename field in {endpoint}", "remove {field} from API response".

First: verify this IS a breaking change. See `rules/api-versioning.md` for the breaking vs non-breaking list.
If it's NOT breaking, just modify the existing v1 endpoint — no versioning needed.

---

## Step 1 — Check What Banks Are Currently Calling This Endpoint

Before writing any code, check Grafana for live traffic:
```
Dashboard: ASTRA > API > Endpoint Traffic by Bank
Filter: endpoint = {path}, version = v1
Shows: which banks are actively calling v1, their call volume, last call timestamp
```

Record these banks — they go in the compatibility matrix "Banks Still on V1" column.
If call volume is zero across all banks, you may be able to skip the 6-month window (with sign-off).

---

## Step 2 — Implement v2 Route

```python
# apps/api/routers/{module}.py

# New v2 Pydantic models in models/requests.py and models/responses.py
class {Resource}RequestV2(BaseModel):
    model_config = ConfigDict(frozen=True)
    # ... new contract

class {Resource}ResponseV2(BaseModel):
    model_config = ConfigDict(frozen=True)
    # ... new contract

# New v2 router (alongside existing v1 router — never replace it)
router_v2 = APIRouter(prefix="/v2/{module}", tags=["{Module} v2"])

@router_v2.{method}("{path}", response_model={Resource}ResponseV2)
async def {handler}_v2(...) -> {Resource}ResponseV2:
    # Full implementation here
    ...
```

---

## Step 3 — Deprecate v1 Route (Add Headers, Delegate to v2 Logic)

```python
from fastapi import Response
from datetime import date

SUNSET_DATE = "2027-{MM}-{DD}"   # minimum 6 months from today

@router_v1.{method}("{path}", response_model={Resource}ResponseV1,
                    summary="[DEPRECATED] Use /v2/{path}")
async def {handler}_v1(
    ...,
    response: Response,
) -> {Resource}ResponseV1:
    # Deprecation headers — all four required
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = SUNSET_DATE
    response.headers["Link"] = f'</v2/{module}{path}>; rel="successor-version"'
    response.headers["Warning"] = f'299 - "Deprecated: migrate to /v2/{module}{path} before {SUNSET_DATE}"'

    # Delegate to v2 logic — do NOT copy-paste the implementation
    v2_input = migrate_{resource}_v1_to_v2(request_body)
    v2_result = await {handler}_v2_logic(v2_input)
    return migrate_{resource}_v2_to_v1(v2_result)
```

---

## Step 4 — Update Compatibility Matrix

Edit `docs/api/compatibility-matrix.md`:
```markdown
| {METHOD} | `{path}` | DEPRECATED | CURRENT | chart-v{N} | {SUNSET_DATE} | {bank-a}, {bank-b} |
```

---

## Step 5 — Notify Affected Banks

Use notification-service to alert every bank listed in "Banks Still on V1":
```python
# Trigger from BankOnboardingWorkflow or admin action
notification = DeprecationNotice(
    subject=f"Action Required: ASTRA API {path} deprecated — migrate by {SUNSET_DATE}",
    affected_endpoint=f"v1{path}",
    successor_endpoint=f"v2{path}",
    sunset_date=SUNSET_DATE,
    migration_guide_url=f"https://docs.astra.internal/api/migration/v1-to-v2/{resource}",
    bank_ids=["bank-a", "bank-b"],   # only banks still on v1
)
await notification_service.send_to_bank_admins(notification)
```

---

## Step 6 — Monitor Migration Progress

Grafana dashboard: "API v1 vs v2 adoption by bank"
- Check weekly until all banks show zero v1 traffic
- Send reminder notification at 3 months if banks haven't migrated
- At sunset date: confirm zero traffic → remove v1 → update matrix to REMOVED

---

## Step 7 — Remove v1 (After Sunset)

Only after ALL banks show zero v1 traffic in Grafana:
```
1. Delete @router_v1.{method}("{path}") handler
2. Delete {Resource}RequestV1 and {Resource}ResponseV1 Pydantic models
3. Delete migrate_{resource}_v1_to_v2() and migrate_{resource}_v2_to_v1() helpers
4. Update compatibility-matrix.md: V1 Status → REMOVED, clear sunset date
5. CI check-api-compatibility.sh will now BLOCK any future code referencing this path
6. Add to release notes under "## Removed APIs"
```

---

## Checklist

```
Before PR:
[ ] Confirmed this IS a breaking change (not just a new optional field)
[ ] Checked Grafana for which banks currently call v1
[ ] v2 route implemented with full tests
[ ] v1 route has all 4 deprecation headers (Deprecation, Sunset, Link, Warning)
[ ] v1 delegates to v2 logic — no duplicate implementation
[ ] compatibility-matrix.md updated with status, sunset date, affected banks
[ ] Sunset date is minimum 6 months from today
[ ] bank_ids listed in matrix are the actual banks from Grafana (not guessed)

After PR merges:
[ ] Deprecation notice sent to all affected bank IT admins
[ ] Grafana dashboard shows v1 traffic per bank
[ ] Calendar reminder set for 3-month halfway check-in
[ ] Calendar reminder set for sunset date action
```
