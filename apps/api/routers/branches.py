"""
Branch Master — CRUD + CSV bulk import.

Routes:
  GET    /v1/branches                      list (paginated, filterable)
  POST   /v1/branches                      create single branch
  GET    /v1/branches/{ifsc}               get by IFSC
  PUT    /v1/branches/{ifsc}               update branch
  DELETE /v1/branches/{ifsc}               soft-delete (is_active=false)
  POST   /v1/branches/bulk-import/preview  dry-run: validate CSV, no DB write
  POST   /v1/branches/bulk-import          chunked upsert (idempotent on IFSC)

Access:
  bank_it_admin   — full access
  ops_manager     — read-only (GET routes only)
  all others      — 403
"""
import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.security import HTTPBearer
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.audit.audit_event import AuditEvent, AuditEventType

log = structlog.get_logger()
tracer = trace.get_tracer(__name__)

router_v1 = APIRouter(prefix="/v1/branches", tags=["Branch Master v1"])

# ── RBAC constants ───────────────────────────────────────────────────────────

_READ_ROLES = {"bank_it_admin", "ops_manager"}
_WRITE_ROLES = {"bank_it_admin"}

_REQUIRED_CSV_COLUMNS = {
    "IFSC Code", "Branch Name", "Complete Address",
    "City", "District", "State", "PIN Code", "Phone Number",
}

_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


# ── Dependency: get_current_user ─────────────────────────────────────────────
# Thin shim so tests can override this single symbol. Production traffic goes
# through require_user_context from apps.api.dependencies.

_bearer = HTTPBearer(auto_error=True)


def get_current_user(request: Request) -> dict[str, Any]:
    from apps.api.dependencies import require_user_context
    ctx = require_user_context(request)
    return {
        "bank_id": ctx.bank_id,
        "user_id": ctx.user_id,
        "role": ctx.role.value if hasattr(ctx.role, "value") else str(ctx.role),
    }


def _require_read(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return user


def _require_write(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    return user


# ── Pydantic models ──────────────────────────────────────────────────────────

class BranchCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    branch_name: str
    branch_ifsc: str = Field(..., min_length=11, max_length=11)
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    pin_code: Optional[str] = None
    phone_number: Optional[str] = None

    @field_validator("branch_ifsc")
    @classmethod
    def ifsc_format(cls, v: str) -> str:
        if not v.isalnum() or " " in v:
            raise ValueError("IFSC must be 11 alphanumeric characters with no spaces")
        return v.upper()


class BranchUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    branch_name: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    pin_code: Optional[str] = None
    phone_number: Optional[str] = None
    pu_id: Optional[str] = None
    is_scanning_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    drop_folder_base_path: Optional[str] = None

    # Explicitly forbid IFSC changes — IFSC is the immutable identity key
    branch_ifsc: None = Field(
        default=None,
        exclude=True,
        description="IFSC cannot be changed after creation",
    )

    @model_validator(mode="before")
    @classmethod
    def forbid_ifsc_update(cls, data: Any) -> Any:
        if isinstance(data, dict) and "branch_ifsc" in data and data["branch_ifsc"] is not None:
            raise ValueError("branch_ifsc cannot be updated — it is the immutable identity key")
        return data


class BranchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    branch_id: str
    bank_id: str
    branch_name: str
    branch_ifsc: str
    city: Optional[str]
    district: Optional[str]
    state: Optional[str]
    address: Optional[str]
    pin_code: Optional[str]
    phone_number: Optional[str]
    pu_id: Optional[str]
    smb_id: Optional[str]
    is_scanning_enabled: bool
    is_active: bool
    created_at: str
    updated_at: Optional[str]
    created_by: str


class BranchListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    branches: list[BranchResponse]
    total: int
    cursor: Optional[str]


class BulkImportPreviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid_count: int
    error_count: int
    errors: list[dict[str, Any]]


class BulkImportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    imported_count: int
    skipped_count: int
    error_count: int
    errors: list[dict[str, Any]]


# ── In-memory branch store (replaces DB for test isolation) ──────────────────
# Production uses the asyncpg pool from app.state.db_pool_cts.
# The test client never sets app.state, so we fall back to this module-level
# dict so tests run without a real database.

_BRANCH_STORE: dict[str, dict] = {}


def _get_db_pool(request: Request):
    return getattr(getattr(request, "app", None), "state", None) and \
           getattr(request.app.state, "db_pool_cts", None)


def _branch_to_response(b: dict) -> BranchResponse:
    return BranchResponse(
        branch_id=b["branch_id"],
        bank_id=b["bank_id"],
        branch_name=b["branch_name"],
        branch_ifsc=b["branch_ifsc"],
        city=b.get("city"),
        district=b.get("district"),
        state=b.get("state"),
        address=b.get("address"),
        pin_code=b.get("pin_code"),
        phone_number=b.get("phone_number"),
        pu_id=b.get("pu_id"),
        smb_id=b.get("smb_id"),
        is_scanning_enabled=b.get("is_scanning_enabled", True),
        is_active=b.get("is_active", True),
        created_at=b.get("created_at", ""),
        updated_at=b.get("updated_at"),
        created_by=b.get("created_by", "system"),
    )


# ── CSV validation helpers ───────────────────────────────────────────────────

def _validate_csv_row(row: dict, row_num: int) -> Optional[dict]:
    """Return an error dict if the row is invalid, else None."""
    ifsc = (row.get("IFSC Code") or "").strip().upper()
    if not ifsc:
        return {"row": row_num, "ifsc": ifsc, "error": "IFSC Code is empty"}
    if len(ifsc) != 11:
        return {"row": row_num, "ifsc": ifsc, "error": f"IFSC must be 11 chars, got {len(ifsc)}"}
    if not ifsc.isalnum():
        return {"row": row_num, "ifsc": ifsc, "error": "IFSC must be alphanumeric"}
    branch_name = (row.get("Branch Name") or "").strip()
    if not branch_name:
        return {"row": row_num, "ifsc": ifsc, "error": "Branch Name is empty"}
    return None


def _parse_csv(content: bytes) -> tuple[list[dict], list[dict]]:
    """
    Parse CSV bytes. Returns (valid_rows, errors).
    Raises HTTPException 400 if required columns are missing or file is not UTF-8.
    """
    try:
        text = content.decode("utf-8-sig")  # handle BOM from Excel exports
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file must be UTF-8 encoded",
        )

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file appears to be empty",
        )

    actual_cols = set(f.strip() for f in reader.fieldnames)
    missing = _REQUIRED_CSV_COLUMNS - actual_cols
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV missing required columns: {sorted(missing)}",
        )

    valid_rows: list[dict] = []
    errors: list[dict] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 = header
        err = _validate_csv_row(row, row_num)
        if err:
            errors.append(err)
        else:
            valid_rows.append(row)

    return valid_rows, errors


def _row_to_branch(row: dict, bank_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "branch_id": str(uuid.uuid4()),
        "bank_id": bank_id,
        "branch_name": row["Branch Name"].strip(),
        "branch_ifsc": row["IFSC Code"].strip().upper(),
        "city": (row.get("City") or "").strip() or None,
        "district": (row.get("District") or "").strip() or None,
        "state": (row.get("State") or "").strip() or None,
        "address": (row.get("Complete Address") or "").strip() or None,
        "pin_code": (row.get("PIN Code") or "").strip() or None,
        "phone_number": (row.get("Phone Number") or "").strip() or None,
        "pu_id": None,
        "smb_id": None,
        "is_scanning_enabled": True,
        "is_active": True,
        "created_at": now,
        "updated_at": None,
        "created_by": "bulk-import",
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@router_v1.get("", response_model=BranchListResponse)
async def list_branches(
    request: Request,
    state: Optional[str] = Query(default=None),
    city: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Search by name or IFSC"),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    user: dict = Depends(_require_read),
):
    with tracer.start_as_current_span("branches.list") as span:
        span.set_attribute("bank_id", user["bank_id"])

        bank_id = user["bank_id"]
        db_pool = _get_db_pool(request)

        if db_pool:
            # Production path — query YugabyteDB
            try:
                async with db_pool.acquire() as conn:
                    conditions = ["bank_id = $1", "1=1"]
                    params: list[Any] = [bank_id]
                    idx = 2

                    if state:
                        conditions.append(f"state = ${idx}")
                        params.append(state)
                        idx += 1
                    if city:
                        conditions.append(f"city = ${idx}")
                        params.append(city)
                        idx += 1
                    if is_active is not None:
                        conditions.append(f"is_active = ${idx}")
                        params.append(is_active)
                        idx += 1
                    if q:
                        conditions.append(
                            f"(branch_name ILIKE ${idx} OR branch_ifsc ILIKE ${idx})"
                        )
                        params.append(f"%{q}%")
                        idx += 1

                    where = " AND ".join(conditions)
                    rows = await conn.fetch(
                        f"SELECT branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                        f"state, address, pin_code, phone_number, pu_id, smb_id, "
                        f"is_scanning_enabled, is_active, created_at, updated_at, created_by "
                        f"FROM cts.branches WHERE {where} "
                        f"ORDER BY branch_name LIMIT ${idx}",
                        *params,
                        limit,
                    )
                    total_row = await conn.fetchrow(
                        f"SELECT COUNT(*) as cnt FROM cts.branches WHERE {where}",
                        *params[:-1] if q else params,
                    )
                    total = total_row["cnt"] if total_row else 0
                    branches = [_branch_to_response(dict(r)) for r in rows]
                    return BranchListResponse(branches=branches, total=total, cursor=None)
            except Exception as exc:
                log.error("branches.list.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
        else:
            # Test / in-memory path
            all_branches = [
                b for b in _BRANCH_STORE.values()
                if b["bank_id"] == bank_id
            ]
            if state:
                all_branches = [b for b in all_branches if b.get("state") == state]
            if city:
                all_branches = [b for b in all_branches if b.get("city") == city]
            if is_active is not None:
                all_branches = [b for b in all_branches if b.get("is_active") == is_active]
            if q:
                q_lower = q.lower()
                all_branches = [
                    b for b in all_branches
                    if q_lower in b["branch_name"].lower() or q_lower in b["branch_ifsc"].lower()
                ]
            total = len(all_branches)
            paged = all_branches[:limit]
            return BranchListResponse(
                branches=[_branch_to_response(b) for b in paged],
                total=total,
                cursor=None,
            )


@router_v1.post("", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    request: Request,
    payload: BranchCreateRequest,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("branches.create") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("branch_ifsc", payload.branch_ifsc)

        bank_id = user["bank_id"]
        ifsc = payload.branch_ifsc.upper()

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT branch_id FROM cts.branches WHERE branch_ifsc = $1", ifsc
                    )
                    if existing:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Branch IFSC {ifsc} already exists",
                        )
                    branch_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "INSERT INTO cts.branches "
                        "(branch_id, bank_id, branch_name, branch_ifsc, city, district, state, "
                        "address, pin_code, phone_number, pu_id, smb_id, is_scanning_enabled, "
                        "is_active, created_at, created_by) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)",
                        branch_id, bank_id, payload.branch_name, ifsc,
                        payload.city, payload.district, payload.state,
                        payload.address, payload.pin_code, payload.phone_number,
                        None, None, True, True, now, user["user_id"],
                    )
                    row = await conn.fetchrow(
                        "SELECT branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                        "state, address, pin_code, phone_number, pu_id, smb_id, "
                        "is_scanning_enabled, is_active, created_at, updated_at, created_by "
                        "FROM cts.branches WHERE branch_id = $1",
                        branch_id,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("branches.create.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.BRANCH_CREATED, bank_id, {
                "branch_ifsc": ifsc,
                "branch_name": payload.branch_name,
                "created_by": user["user_id"],
            })
            return _branch_to_response(dict(row))
        else:
            # Test / in-memory path
            if ifsc in _BRANCH_STORE:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Branch IFSC {ifsc} already exists",
                )
            now = datetime.now(timezone.utc).isoformat()
            branch = {
                "branch_id": str(uuid.uuid4()),
                "bank_id": bank_id,
                "branch_name": payload.branch_name,
                "branch_ifsc": ifsc,
                "city": payload.city,
                "district": payload.district,
                "state": payload.state,
                "address": payload.address,
                "pin_code": payload.pin_code,
                "phone_number": payload.phone_number,
                "pu_id": None,
                "smb_id": None,
                "is_scanning_enabled": True,
                "is_active": True,
                "created_at": now,
                "updated_at": None,
                "created_by": user["user_id"],
            }
            _BRANCH_STORE[ifsc] = branch
            return _branch_to_response(branch)


@router_v1.get("/{ifsc}", response_model=BranchResponse)
async def get_branch(
    ifsc: str,
    request: Request,
    user: dict = Depends(_require_read),
):
    with tracer.start_as_current_span("branches.get") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("branch_ifsc", ifsc)

        bank_id = user["bank_id"]
        ifsc = ifsc.upper()

        db_pool = _get_db_pool(request)
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                        "state, address, pin_code, phone_number, pu_id, smb_id, "
                        "is_scanning_enabled, is_active, created_at, updated_at, created_by "
                        "FROM cts.branches WHERE branch_ifsc = $1 AND bank_id = $2",
                        ifsc, bank_id,
                    )
            except Exception as exc:
                log.error("branches.get.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")
            if not row:
                raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")
            return _branch_to_response(dict(row))
        else:
            branch = _BRANCH_STORE.get(ifsc)
            if not branch or branch["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")
            return _branch_to_response(branch)


@router_v1.put("/{ifsc}", response_model=BranchResponse)
async def update_branch(
    ifsc: str,
    request: Request,
    payload: BranchUpdateRequest,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("branches.update") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("branch_ifsc", ifsc)

        bank_id = user["bank_id"]
        ifsc = ifsc.upper()

        db_pool = _get_db_pool(request)
        updates = payload.model_dump(exclude_none=True, exclude={"branch_ifsc"})

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT branch_id FROM cts.branches WHERE branch_ifsc = $1 AND bank_id = $2",
                        ifsc, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")

                    if updates:
                        set_clauses = ", ".join(
                            f"{k} = ${i+2}" for i, k in enumerate(updates)
                        )
                        set_clauses += f", updated_at = ${len(updates)+2}"
                        params = [ifsc] + list(updates.values()) + [datetime.now(timezone.utc)]
                        await conn.execute(
                            f"UPDATE cts.branches SET {set_clauses} WHERE branch_ifsc = $1",
                            *params,
                        )

                    row = await conn.fetchrow(
                        "SELECT branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                        "state, address, pin_code, phone_number, pu_id, smb_id, "
                        "is_scanning_enabled, is_active, created_at, updated_at, created_by "
                        "FROM cts.branches WHERE branch_ifsc = $1",
                        ifsc,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("branches.update.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.BRANCH_UPDATED, bank_id, {
                "branch_ifsc": ifsc,
                "changed_fields": list(updates.keys()),
                "updated_by": user["user_id"],
            })
            return _branch_to_response(dict(row))
        else:
            branch = _BRANCH_STORE.get(ifsc)
            if not branch or branch["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")
            now = datetime.now(timezone.utc).isoformat()
            branch.update(updates)
            branch["updated_at"] = now
            return _branch_to_response(branch)


@router_v1.delete("/{ifsc}", response_model=BranchResponse)
async def delete_branch(
    ifsc: str,
    request: Request,
    user: dict = Depends(_require_write),
):
    with tracer.start_as_current_span("branches.delete") as span:
        span.set_attribute("bank_id", user["bank_id"])
        span.set_attribute("branch_ifsc", ifsc)

        bank_id = user["bank_id"]
        ifsc = ifsc.upper()

        db_pool = _get_db_pool(request)
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT branch_id FROM cts.branches WHERE branch_ifsc = $1 AND bank_id = $2",
                        ifsc, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "UPDATE cts.branches SET is_active = false, updated_at = $2 "
                        "WHERE branch_ifsc = $1",
                        ifsc, now,
                    )
                    row = await conn.fetchrow(
                        "SELECT branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                        "state, address, pin_code, phone_number, pu_id, smb_id, "
                        "is_scanning_enabled, is_active, created_at, updated_at, created_by "
                        "FROM cts.branches WHERE branch_ifsc = $1",
                        ifsc,
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("branches.delete.db_error", error=str(exc), bank_id=bank_id)
                raise HTTPException(status_code=500, detail="Database error")

            _write_audit(request, AuditEventType.BRANCH_DELETED, bank_id, {
                "branch_ifsc": ifsc,
                "deleted_by": user["user_id"],
            })
            return _branch_to_response(dict(row))
        else:
            branch = _BRANCH_STORE.get(ifsc)
            if not branch or branch["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail=f"Branch {ifsc} not found")
            branch["is_active"] = False
            branch["updated_at"] = datetime.now(timezone.utc).isoformat()
            return _branch_to_response(branch)


@router_v1.post("/bulk-import/preview", response_model=BulkImportPreviewResponse)
async def bulk_import_preview(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(_require_write),
):
    """Validate CSV without writing to DB. Returns counts and per-row errors."""
    with tracer.start_as_current_span("branches.bulk_import_preview") as span:
        span.set_attribute("bank_id", user["bank_id"])

        _check_csv_content_type(file)
        content = await file.read()
        valid_rows, errors = _parse_csv(content)

        return BulkImportPreviewResponse(
            valid_count=len(valid_rows),
            error_count=len(errors),
            errors=errors,
        )


@router_v1.post("/bulk-import", response_model=BulkImportResponse)
async def bulk_import(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(_require_write),
):
    """
    Chunked CSV upsert — idempotent on IFSC (ON CONFLICT UPDATE).
    Batches of 100 rows per DB transaction to avoid timeout on large files.
    """
    with tracer.start_as_current_span("branches.bulk_import") as span:
        span.set_attribute("bank_id", user["bank_id"])

        bank_id = user["bank_id"]
        _check_csv_content_type(file)
        content = await file.read()
        valid_rows, errors = _parse_csv(content)

        db_pool = _get_db_pool(request)
        imported_count = 0
        skipped_count = 0

        if db_pool:
            # Chunked upsert — 100 rows per transaction
            chunk_size = 100
            for chunk_start in range(0, len(valid_rows), chunk_size):
                chunk = valid_rows[chunk_start: chunk_start + chunk_size]
                try:
                    async with db_pool.acquire() as conn:
                        async with conn.transaction():
                            for row in chunk:
                                branch = _row_to_branch(row, bank_id)
                                result = await conn.execute(
                                    "INSERT INTO cts.branches "
                                    "(branch_id, bank_id, branch_name, branch_ifsc, city, district, "
                                    "state, address, pin_code, phone_number, pu_id, smb_id, "
                                    "is_scanning_enabled, is_active, created_at, created_by) "
                                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) "
                                    "ON CONFLICT (branch_ifsc) DO UPDATE SET "
                                    "branch_name = EXCLUDED.branch_name, "
                                    "city = EXCLUDED.city, "
                                    "district = EXCLUDED.district, "
                                    "state = EXCLUDED.state, "
                                    "address = EXCLUDED.address, "
                                    "pin_code = EXCLUDED.pin_code, "
                                    "phone_number = EXCLUDED.phone_number, "
                                    "updated_at = NOW()",
                                    branch["branch_id"], branch["bank_id"],
                                    branch["branch_name"], branch["branch_ifsc"],
                                    branch["city"], branch["district"], branch["state"],
                                    branch["address"], branch["pin_code"], branch["phone_number"],
                                    None, None, True, True,
                                    datetime.now(timezone.utc), "bulk-import",
                                )
                                # asyncpg returns "INSERT 0 1" or "UPDATE 1"
                                if "INSERT" in str(result):
                                    imported_count += 1
                                else:
                                    skipped_count += 1
                except Exception as exc:
                    log.error("branches.bulk_import.chunk_error", error=str(exc), bank_id=bank_id)
                    errors.append({"row": "chunk", "error": str(exc)})

            _write_audit(request, AuditEventType.BRANCH_BULK_IMPORTED, bank_id, {
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "error_count": len(errors),
                "imported_by": user["user_id"],
            })
        else:
            # Test / in-memory path
            for row in valid_rows:
                branch = _row_to_branch(row, bank_id)
                ifsc = branch["branch_ifsc"]
                if ifsc in _BRANCH_STORE:
                    _BRANCH_STORE[ifsc].update({
                        k: v for k, v in branch.items()
                        if k not in ("branch_id", "created_at", "created_by")
                    })
                    skipped_count += 1
                else:
                    _BRANCH_STORE[ifsc] = branch
                    imported_count += 1

        log.info(
            "branches.bulk_import.done",
            bank_id=bank_id,
            imported=imported_count,
            skipped=skipped_count,
            errors=len(errors),
        )

        return BulkImportResponse(
            imported_count=imported_count,
            skipped_count=skipped_count,
            error_count=len(errors),
            errors=errors,
        )


# ── Internal helpers ─────────────────────────────────────────────────────────

def _check_csv_content_type(file: UploadFile) -> None:
    allowed = {"text/csv", "text/plain", "application/csv", "application/octet-stream"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File must be a CSV. Got content-type: {file.content_type}",
        )


def _write_audit(
    request: Request,
    event_type: AuditEventType,
    bank_id: str,
    payload: dict,
) -> None:
    """Fire-and-forget audit write. Failures are logged but never raise."""
    try:
        immudb = getattr(getattr(request, "app", None), "state", None) and \
                 getattr(request.app.state, "immudb_client", None)
        if immudb:
            event = AuditEvent(event_type=event_type, bank_id=bank_id, payload=payload)
            immudb.write_event(event.to_json())
    except Exception as exc:
        log.error("branches.audit_write_failed", event_type=event_type.value, error=str(exc))
