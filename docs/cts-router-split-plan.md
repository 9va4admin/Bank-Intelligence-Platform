# CTS Router Split — Complete Plan & Decision Record

**Date decided:** 2026-09-09  
**Author:** Nilesh Shah  
**Status:** APPROVED — ready to execute, not started  
**Repo:** `bank-intelligence-platform` (CTS-only monorepo)

---

## 1. The Problem

`apps/api/routers/cts.py` has grown to **8,040 lines and 87 routes** — the single largest file in the codebase by a wide margin. Every new CTS feature was added here because it was the path of least resistance. This was a failure of judgment that should have been caught and flagged at ~800 lines. It was not.

Current file sizes (key files only):

| Lines | File |
|------:|------|
| 8,040 | `apps/api/routers/cts.py` ← the problem |
| 1,683 | `apps/api/routers/demo_cloud_extract.py` |
| 1,386 | `modules/cts/workflows/cheque_workflow.py` |
| 1,348 | `modules/cts/workflows/outward_scan_workflow.py` |
| 1,329 | `apps/api/routers/admin.py` |
| 1,145 | `apps/api/routers/cts_ops.py` |

---

## 2. Architecture Decision — Direct Routing, NOT Orchestration

**Rejected approach:** Keep `cts.py` as an orchestrator that internally calls sub-modules and passes common context down.

**Chosen approach:** Each new file is a **fully independent FastAPI router**, registered directly in `main.py`. FastAPI owns the routing table. No orchestrator.

```
Client → FastAPI → cts_inward.py       (direct)
Client → FastAPI → cts_outward_core.py (direct)
Client → FastAPI → cts_smb.py          (direct)
... etc
```

**Common context (bank_id, user_context, temporal_client, kafka_producer) is solved by FastAPI dependency injection**, not by passing between files. Each route declares its deps via `Depends()` and FastAPI injects them per request.

**This pattern already works in this codebase today.** Look at `main.py`:

```python
app.include_router(cts.router_v1)             # existing
app.include_router(cts_ops.router_v1)         # already split out
app.include_router(vault_upload.router_v1)    # already split out
app.include_router(cts_outward_queue.router_v1) # already split out
```

When a client hits `/v1/cts/smb/ops-summary`, `cts.py` is never touched — FastAPI goes straight to `cts_ops.py`. The refactoring is completing what was already started.

---

## 3. The Core Problem Within the Split — Shared Dependencies

`cts.py` defines these at the top and every route uses them:

```python
def _safe_temporal_param(value: str, field: str) -> str: ...
async def get_current_user_context(...) -> UserContext: ...
async def get_current_bank_id(...) -> str: ...
async def get_current_user_id(...) -> str: ...
def get_temporal_client(request: Request): ...
def get_kafka_producer(request: Request): ...

# SQL row cap constants
_VAULT_GAP_MAX_ROWS    = 2000
_SCAN_LOG_MAX_ROWS     = 500
_ANALYTICS_TOP_N       = 10
_SMB_REPORTS_MAX_ROWS  = 500
_COMPLIANCE_MAX_ROWS   = 500
_NGCH_ROUTING_MAX_ROWS = 500
_MICR_PREFIX_MAX_ROWS  = 1000
```

**Step 0 (mandatory first):** Move ALL of the above to a new file `apps/api/routers/cts_deps.py`. Every split file imports from there. This is ~60 lines with no business logic, so it can be done safely before touching any routes.

---

## 4. Complete Split Plan — 9 New Router Files

All new files use:
```python
router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])
```
**Zero URL changes. All existing clients unaffected.**

### File 1: `cts_inward.py` (~1,400 lines, 10 routes)

Routes to move:
- `POST /inward/{instrument_id}/submit` (line 178)
- `GET /decisions/{instrument_id}` (line 296)
- `POST /review/{instrument_id}/decide` (line 357)
- `GET /queue` (line 425)
- `GET /decisions` (line 536)
- `GET /vault-gaps` (line 656)
- `GET /search` — instrument search (line 767)
- `GET /inward/analytics` (line 5559)
- `GET /inward/live-flow` (line 7198)
- `GET /inward/sessions` (line 7282)

Internal helpers that travel with this file:
- `_instrument_search()` (line 5258)

---

### File 2: `cts_outward_core.py` (~1,400 lines, 9 routes)

Routes to move:
- `POST /outward/scan/upload-url` (line 1678)
- `POST /outward/scan/submit` (line 1795)
- `GET /outward/hub-summary` (line 3409)
- `PATCH /outward/lots/{lot_id}/seal` (line 3451)
- `POST /outward/lots/seal-all` (line 3488)
- `POST /outward/scanner-sessions/open` (line 4633)
- `POST /outward/scanner-sessions/close` (line 4696)
- `POST /outward/clearing-session/submit` (line 4768)
- `GET /outward/clearing-window` (line 4841)

Internal helpers that travel with this file:
- `_ensure_open_lot()` (line 3351)
- `_row_to_branch_summary()` (line 3317)

---

### File 3: `cts_outward_data.py` (~1,100 lines, 13 routes)

Routes to move:
- `GET /outward/human-review-queue` (line 4920)
- `POST /outward/review/{instrument_id}/decide` (line 4979)
- `GET /outward/settlement` (line 5062)
- `GET /outward/analytics/daily` (line 5408)
- `GET /outward/lots/{lot_id}/instruments` (line 5318)
- `GET /outward/lots` (line 6033)
- `GET /outward/reconciliation` (line 5915)
- `GET /outward/sessions` (line 6895)
- `GET /outward/compliance` (line 7374)
- `GET /outward/decisions` (line 7703)
- `POST /outward/endorsement` (line 2703)
- `GET /outward/endorsement-queue` (line 7919)
- `GET /outward/file-download` (line 2776)
- `POST /outward/iqa-rescan` (line 2830)
- `GET /outward/iqa-results` (line 7985)
- `GET /outward/session-report` (line 2894)

---

### File 4: `cts_scanner.py` (~700 lines, 6 routes)

Routes to move:
- `POST /admin/scanner/reg-code` (line 4336)
- `POST /admin/scanner/register` (line 4472)
- `POST /outward/scan-events` (line 4071)
- `GET /outward/scan-events` (line 4134)
- `GET /outward/branch-scan-events` (line 4234)
- `GET /scan-monitor/recent` (line 2968)

---

### File 5: `cts_vault_ops.py` (~700 lines, 7 routes)

Routes to move:
- `GET /vault/sync-status` (line 1006 and 7836 — **check for duplicate, only keep one**)
- `POST /vault/sync` (line 1035)
- `GET /vault/health` (line 6168)
- `GET /vault/misses` (line 6234)
- `GET /vault/pps` (line 6294)
- `GET /vault/stop-cheques` (line 6362)

Internal helpers that travel with this file:
- `_vault_status()` (line 3692)
- `_publish_vault_batch_event()` (line 3700)

> **IMPORTANT:** Before moving vault routes, verify there is no overlap with the existing
> `vault_upload.py` which is already registered in `main.py`. Check its routes at:
> `apps/api/routers/vault_upload.py` lines 93, 224, 251, 342.
> Do NOT create duplicate route registrations.

---

### File 6: `cts_smb.py` (~600 lines, 8 routes)

Routes to move:
- `GET /smb` (SMB list, line 1408)
- `POST /smb` (register SMB, line 1436)
- `GET /smb/{id}/ledger` (line 1511)
- `GET /smb/{id}/forwarding-log` (line 1543)
- `POST /smb/{id}/vault-sync` (line 1574)
- `GET /smb/ledgers` (all SMB ledgers, line 5805)
- `GET /smb/forwarding-log` (SB view all, line 6646)
- `GET /smb/reports` (line 6995)

Internal helpers that travel with this file:
- `_smb_list()` (line 5147)
- `_smb_ledger()` (line 5183)
- `_smb_forwarding_log()` (line 5222)

---

### File 7: `cts_holds.py` (~700 lines, 9 routes)

Routes to move:
- `POST /holds` — place hold (line 2117)
- `GET /holds` — list holds (line 2242)
- `POST /holds/{id}/release` (line 2310)
- `POST /holds/recommendation` (line 2402)
- `GET /mismatches` (line 2514)
- `POST /mismatches/{id}/resolve` (line 2580)
- `POST /allocation/claim` (line 3048)
- `DELETE /allocation/{id}/claim` (line 3119)
- `GET /allocation/status` (line 3163)

---

### File 8: `cts_admin_ops.py` (~900 lines, 12 routes)

Routes to move:
- `GET /ifsc-registry` (line 1947)
- `GET /ifsc-registry/{id}` (line 1968)
- `POST /ifsc-registry` (line 1982)
- `PUT /ifsc-registry/{id}/approve` (line 2003)
- `DELETE /ifsc-registry/{id}` (line 2023)
- `GET /schedules` (line 1134)
- `PATCH /schedules/{id}` (line 1194)
- `POST /schedules/{id}/pause` (line 1241)
- `POST /schedules/{id}/resume` (line 1275)
- `GET /instrument/{id}/digest` (line 828)
- `POST /admin/workflow-cleanup` (line 905)
- `GET /admin/login-log` (line 7107)
- `GET /admin/ngch-routing` (line 7475)
- `GET /admin/micr-prefixes` (line 7539)
- `GET /rpc/zones` (line 7610)

Internal helpers that travel with this file:
- `_get_ifsc_repo()` (line 1937)

---

### File 9: `cts_dashboard.py` (~400 lines, 3 routes)

Routes to move:
- `GET /dashboard/today` (line 6464)
- `GET /dashboard/trend` (line 6565)
- `GET /exceptions` (line 6777)

---

## 5. `main.py` Wiring Change

**Before:**
```python
from apps.api.routers import cts
app.include_router(cts.router_v1)
```

**After:**
```python
from apps.api.routers import (
    cts_inward, cts_outward_core, cts_outward_data, cts_scanner,
    cts_vault_ops, cts_smb, cts_holds, cts_admin_ops, cts_dashboard,
)
app.include_router(cts_inward.router_v1)
app.include_router(cts_outward_core.router_v1)
app.include_router(cts_outward_data.router_v1)
app.include_router(cts_scanner.router_v1)
app.include_router(cts_vault_ops.router_v1)
app.include_router(cts_smb.router_v1)
app.include_router(cts_holds.router_v1)
app.include_router(cts_admin_ops.router_v1)
app.include_router(cts_dashboard.router_v1)
# cts_ops, vault_upload, cts_outward_queue stay as-is — already registered
```

`cts.py` is **deleted** only after all tests are green.

---

## 6. Test Plan

### Existing test files — keep as-is (URLs unchanged, tests still valid)

| File | Status |
|---|---|
| `tests/apps/api/routers/test_cts_phase2.py` | Keep |
| `tests/apps/api/routers/test_cts_phase3.py` | Keep |
| `tests/apps/api/routers/test_cts_phase4.py` | Keep |
| `tests/apps/api/routers/test_cts_phase6_smb.py` | Keep |
| `tests/apps/api/routers/test_cts_outward_queue.py` | Keep |
| `tests/apps/api/routers/test_vault_upload_routes.py` | Keep |
| `tests/apps/api/routers/test_cts_ifsc.py` | Keep (rename optional) |

### `test_cts.py` (1,193 lines) — split into two

| Class in test_cts.py | Moves to |
|---|---|
| `TestCTSSubmitRoute` | `test_cts_inward.py` |
| `TestCTSDecisionRoute` | `test_cts_inward.py` |
| `TestCTSHealthRoute` | `test_cts_inward.py` |
| `TestCTSSubmitWithTemporalClient` | `test_cts_inward.py` |
| `TestCTSDecisionWithTemporalClient` | `test_cts_inward.py` |
| `TestCTSReviewDecision` | `test_cts_inward.py` |
| `TestCTSQueueRoute` | `test_cts_inward.py` |
| `TestChequeSearchRoute` | `test_cts_inward.py` |
| `TestCTSSubmitCtsConfigWiring` | `test_cts_inward.py` |
| `TestCTSAuthEdgeCases` | `test_cts_inward.py` |
| `TestCTSDependencyCoverage` | `test_cts_inward.py` |
| `TestVaultSyncRoutes` | `test_cts_vault_ops.py` |
| `TestScheduleIDOR` | `test_cts_admin_ops.py` |

### New test files to write (TDD — RED first)

| New test file | Covers |
|---|---|
| `test_cts_inward.py` | All inward routes (split from test_cts.py) |
| `test_cts_outward_core.py` | Hub summary, lot seal, scanner sessions, clearing submit |
| `test_cts_outward_data.py` | Reconciliation, outward analytics, lots list, IQA |
| `test_cts_scanner.py` | Scanner reg-code, scanner register, scan events |
| `test_cts_vault_ops.py` | Vault health, misses, PPS, stop-cheques |
| `test_cts_smb.py` | SMB register, SMB ledger, SMB forwarding log |
| `test_cts_holds.py` | Place/release hold, mismatch resolve, claim/unclaim |
| `test_cts_admin_ops.py` | IFSC, schedules, workflow cleanup, NGCH routing |
| `test_cts_dashboard.py` | Dashboard today/trend, exceptions |

---

## 7. Execution Order (strict — do not skip steps)

```
Step 0  Create cts_deps.py              → run pytest → confirm green
Step 1a cts_dashboard.py (3 routes)     → write test_cts_dashboard.py → pytest green
Step 1b cts_smb.py (8 routes)          → write test_cts_smb.py → pytest green
Step 1c cts_holds.py (9 routes)        → write test_cts_holds.py → pytest green
Step 1d cts_scanner.py (6 routes)      → write test_cts_scanner.py → pytest green
Step 1e cts_vault_ops.py (7 routes)    → write test_cts_vault_ops.py → pytest green
Step 1f cts_admin_ops.py (12 routes)   → split test_cts.py → pytest green
Step 1g cts_outward_data.py (15 routes)→ write test_cts_outward_data.py → pytest green
Step 1h cts_outward_core.py (9 routes) → write test_cts_outward_core.py → pytest green
Step 1i cts_inward.py (10 routes)      → split test_cts.py → pytest green
Step 2  Wire main.py fully
Step 3  Delete cts.py → run full pytest suite → fix any import leaks
Step 4  Commit
```

---

## 8. Safety Protocol (non-negotiable)

1. **One step at a time.** Confirm with Nilesh before moving to the next step.
2. **After each step: run `pytest` and paste the actual terminal output** (numbers, not a summary).
3. **After each step: list every file touched** so Nilesh can verify scope.
4. **`cts.py` is never edited during Steps 1a–1i** — code is carved out (new file created, lines verified), then corresponding lines deleted from `cts.py` only after the new file's tests are green.
5. **All work happens on branch `claude/cts-router-split`** — the entire change is reversible with one `git checkout main`.
6. **Check `vault_upload.py` routes before moving vault section** — potential duplicate registration risk.
7. **Never declare "done" without running the server** (`uvicorn apps.api.main:app`) and confirming no startup errors.

---

## 9. Optional Phase 2 — Service Layer Extraction (do AFTER split is stable)

Two route handlers have business logic that should move to `modules/cts/services/`:

**`get_inward_analytics`** (~210 lines in a single handler, line 5559):
→ Extract SQL logic to `modules/cts/services/inward_analytics_service.py`
→ Route handler becomes ~20 lines

**`submit_outward_scan`** (~128 lines in a single handler, line 1795):
→ Extract to `modules/cts/services/outward_scan_service.py`
→ Route handler becomes ~25 lines

Do not do this in the same session as the router split. Stabilise first.

---

## 10. What Already Exists (do not touch these)

These files were already split out from `cts.py` correctly and are registered in `main.py`:

| File | Routes | Already registered |
|---|---|---|
| `apps/api/routers/cts_ops.py` | 15 routes (`/smb/ops-summary`, `/branch/*`, `/agency/*` etc.) | Yes |
| `apps/api/routers/vault_upload.py` | 4 routes (vault CSV upload flow) | Yes |
| `apps/api/routers/cts_outward_queue.py` | 1 route (`POST /decisions`) | Yes |

---

*Document created: 2026-09-09. Ready to execute. No code has been changed yet.*
