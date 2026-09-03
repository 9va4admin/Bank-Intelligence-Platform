"""
Scanner OEM Config — CRUD for cts.scanner_configs.

Each branch configured for FOLDER_DROP mode has one scanner_config row that tells
the drop-folder watcher how to parse the OEM metadata file and locate images.

Routes:
  GET    /v1/cts/scanner-configs                — list all for bank
  POST   /v1/cts/scanner-configs                — create
  GET    /v1/cts/scanner-configs/{config_id}    — get by ID
  PUT    /v1/cts/scanner-configs/{config_id}    — update (partial, any field)
  DELETE /v1/cts/scanner-configs/{config_id}    — soft-delete (is_active=false)

RBAC:
  bank_it_admin, ops_manager, platform_admin — full read + write
  ops_reviewer, fraud_analyst               — 403

Audit + Ops Dashboard:
  Every write emits an AuditEvent to Immudb (mandatory).
  Every write also publishes to platform.config.changed Kafka topic (fire-and-forget)
  so the Ops Dashboard can flash a notification without polling.
  drop_folder_path changes are audited with old + new values.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from shared.audit.audit_event import AuditEvent, AuditEventType

log = structlog.get_logger()
tracer = trace.get_tracer(__name__)

router_v1 = APIRouter(prefix="/v1/cts/scanner-configs", tags=["Scanner Config v1"])

_WRITE_ROLES = {"bank_it_admin", "ops_manager", "platform_admin"}
_READ_ROLES  = {"bank_it_admin", "ops_manager", "platform_admin"}

_CONFIG_STORE: dict[str, dict] = {}


# ── Auth dependency ───────────────────────────────────────────────────────────

def get_current_user(request: Request) -> dict[str, Any]:
    try:
        from apps.api.dependencies import require_user_context
        ctx = require_user_context(request)
        return {
            "bank_id": ctx.bank_id,
            "user_id": ctx.user_id,
            "role": ctx.role.value if hasattr(ctx.role, "value") else str(ctx.role),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


# ── DB / infra helpers ────────────────────────────────────────────────────────

def _get_db_pool(request: Request):
    state = getattr(getattr(request, "app", None), "state", None)
    return getattr(state, "db_pool_cts", None) if state else None


def _write_audit(request: Request, event_type: AuditEventType, bank_id: str, payload: dict) -> None:
    try:
        state = getattr(getattr(request, "app", None), "state", None)
        immudb = getattr(state, "immudb_client", None) if state else None
        if immudb:
            record = json.dumps({"event_type": event_type.value, "bank_id": bank_id, **payload})
            immudb.write_event(record)
    except Exception as exc:
        log.error("scanner_configs.audit_failed", event_type=event_type.value, error=str(exc))


def _emit_config_changed(request: Request, bank_id: str, branch_ifsc: str, action: str) -> None:
    try:
        state = getattr(getattr(request, "app", None), "state", None)
        kafka = getattr(state, "kafka_producer", None) if state else None
        if kafka:
            kafka.publish(
                "platform.config.changed",
                {
                    "entity": "scanner_config",
                    "action": action,
                    "bank_id": bank_id,
                    "branch_ifsc": branch_ifsc,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception as exc:
        log.warning("scanner_configs.kafka_emit_failed", error=str(exc))


# ── Pydantic models ───────────────────────────────────────────────────────────

class ScannerConfigCreate(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: Optional[str] = None
    branch_ifsc: Optional[str] = Field(default=None, min_length=11, max_length=11)
    scanner_oem: str
    scanner_model: str
    output_format: str
    date_format: str
    amount_format: str
    field_mapping: dict[str, str]
    image_naming_pattern: str
    image_side_mapping: dict[str, str]
    drop_folder_path: str


class ScannerConfigUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanner_oem: Optional[str] = None
    scanner_model: Optional[str] = None
    output_format: Optional[str] = None
    date_format: Optional[str] = None
    amount_format: Optional[str] = None
    field_mapping: Optional[dict[str, str]] = None
    image_naming_pattern: Optional[str] = None
    image_side_mapping: Optional[dict[str, str]] = None
    drop_folder_path: Optional[str] = None
    is_active: Optional[bool] = None


class ScannerConfigResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scanner_config_id: str
    bank_id: str
    branch_id: Optional[str]
    branch_ifsc: Optional[str]
    scanner_oem: str
    scanner_model: str
    output_format: str
    date_format: str
    amount_format: str
    field_mapping: dict[str, Any]
    image_naming_pattern: str
    image_side_mapping: dict[str, Any]
    drop_folder_path: str
    is_active: bool
    created_at: str
    updated_at: Optional[str]
    created_by: str


class ScannerConfigListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    configs: list[ScannerConfigResponse]
    total: int


def _to_response(c: dict) -> ScannerConfigResponse:
    def _ts(v) -> Optional[str]:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return ScannerConfigResponse(
        scanner_config_id=c["scanner_config_id"],
        bank_id=c["bank_id"],
        branch_id=c.get("branch_id"),
        branch_ifsc=c.get("branch_ifsc"),
        scanner_oem=c["scanner_oem"],
        scanner_model=c["scanner_model"],
        output_format=c["output_format"],
        date_format=c["date_format"],
        amount_format=c["amount_format"],
        field_mapping=c["field_mapping"],
        image_naming_pattern=c["image_naming_pattern"],
        image_side_mapping=c["image_side_mapping"],
        drop_folder_path=c["drop_folder_path"],
        is_active=c.get("is_active", True),
        created_at=_ts(c.get("created_at")) or "",
        updated_at=_ts(c.get("updated_at")),
        created_by=c.get("created_by", "system"),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router_v1.get("", response_model=ScannerConfigListResponse)
async def list_configs(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ScannerConfigListResponse:
    if current_user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    with tracer.start_as_current_span("scanner_configs.list") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)

        db_pool = _get_db_pool(request)
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT scanner_config_id, bank_id, branch_id, branch_ifsc, "
                        "scanner_oem, scanner_model, output_format, date_format, amount_format, "
                        "field_mapping, image_naming_pattern, image_side_mapping, drop_folder_path, "
                        "is_active, created_at, updated_at, created_by "
                        "FROM cts.scanner_configs WHERE bank_id = $1 ORDER BY branch_ifsc NULLS LAST",
                        bank_id,
                    )
            except Exception as exc:
                log.error("scanner_configs.list.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
            configs = [_to_response(dict(r)) for r in rows]
        else:
            configs = [
                _to_response(c) for c in _CONFIG_STORE.values()
                if c["bank_id"] == bank_id
            ]
        return ScannerConfigListResponse(configs=configs, total=len(configs))


@router_v1.post("", response_model=ScannerConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(
    body: ScannerConfigCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ScannerConfigResponse:
    if current_user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    with tracer.start_as_current_span("scanner_configs.create") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT scanner_config_id FROM cts.scanner_configs "
                        "WHERE bank_id = $1 AND COALESCE(branch_id, '') = $2 AND is_active = true",
                        bank_id, body.branch_id or "",
                    )
                    if existing:
                        raise HTTPException(status_code=409, detail="An active config already exists for this branch.")
                    config_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc)
                    await conn.execute(
                        "INSERT INTO cts.scanner_configs "
                        "(scanner_config_id, bank_id, branch_id, branch_ifsc, scanner_oem, scanner_model, "
                        "output_format, date_format, amount_format, field_mapping, image_naming_pattern, "
                        "image_side_mapping, drop_folder_path, is_active, created_at, created_by) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,true,$14,$15)",
                        config_id, bank_id, body.branch_id, body.branch_ifsc,
                        body.scanner_oem, body.scanner_model, body.output_format,
                        body.date_format, body.amount_format,
                        json.dumps(body.field_mapping), body.image_naming_pattern,
                        json.dumps(body.image_side_mapping), body.drop_folder_path,
                        now, current_user["user_id"],
                    )
                    row = await conn.fetchrow(
                        "SELECT scanner_config_id, bank_id, branch_id, branch_ifsc, scanner_oem, scanner_model, "
                        "output_format, date_format, amount_format, field_mapping, image_naming_pattern, "
                        "image_side_mapping, drop_folder_path, is_active, created_at, updated_at, created_by "
                        "FROM cts.scanner_configs WHERE scanner_config_id = $1", config_id
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("scanner_configs.create.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
            result = _to_response(dict(row))
        else:
            active_exists = any(
                c["bank_id"] == bank_id and c.get("branch_id") == body.branch_id and c.get("is_active", True)
                for c in _CONFIG_STORE.values()
            )
            if active_exists:
                raise HTTPException(status_code=409, detail="An active config already exists for this branch.")
            config_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            record = {
                "scanner_config_id": config_id,
                "bank_id": bank_id,
                "branch_id": body.branch_id,
                "branch_ifsc": body.branch_ifsc,
                "scanner_oem": body.scanner_oem,
                "scanner_model": body.scanner_model,
                "output_format": body.output_format,
                "date_format": body.date_format,
                "amount_format": body.amount_format,
                "field_mapping": body.field_mapping,
                "image_naming_pattern": body.image_naming_pattern,
                "image_side_mapping": body.image_side_mapping,
                "drop_folder_path": body.drop_folder_path,
                "is_active": True,
                "created_at": now,
                "updated_at": None,
                "created_by": current_user["user_id"],
            }
            _CONFIG_STORE[config_id] = record
            result = _to_response(record)

        _write_audit(request, AuditEventType.SCANNER_CONFIG_CREATED, bank_id, {
            "scanner_config_id": config_id,
            "branch_ifsc": body.branch_ifsc,
            "drop_folder_path": body.drop_folder_path,
            "created_by": current_user["user_id"],
        })
        _emit_config_changed(request, bank_id, body.branch_ifsc or "", "created")
        log.info("scanner_config.created", bank_id=bank_id, config_id=config_id)
        return result


@router_v1.get("/{config_id}", response_model=ScannerConfigResponse)
async def get_config(
    config_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ScannerConfigResponse:
    if current_user["role"] not in _READ_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    bank_id = current_user["bank_id"]
    db_pool = _get_db_pool(request)

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT scanner_config_id, bank_id, branch_id, branch_ifsc, "
                    "scanner_oem, scanner_model, output_format, date_format, amount_format, "
                    "field_mapping, image_naming_pattern, image_side_mapping, drop_folder_path, "
                    "is_active, created_at, updated_at, created_by "
                    "FROM cts.scanner_configs WHERE scanner_config_id = $1 AND bank_id = $2",
                    config_id, bank_id,
                )
        except Exception as exc:
            log.error("scanner_configs.get.db_error", error=str(exc))
            raise HTTPException(status_code=500, detail="Database error")
        if not row:
            raise HTTPException(status_code=404, detail="Scanner config not found")
        return _to_response(dict(row))
    else:
        c = _CONFIG_STORE.get(config_id)
        if not c or c["bank_id"] != bank_id:
            raise HTTPException(status_code=404, detail="Scanner config not found")
        return _to_response(c)


@router_v1.put("/{config_id}", response_model=ScannerConfigResponse)
async def update_config(
    config_id: str,
    body: ScannerConfigUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ScannerConfigResponse:
    if current_user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    with tracer.start_as_current_span("scanner_configs.update") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("config_id", config_id)

        updates = body.model_dump(exclude_none=True)
        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT drop_folder_path, branch_ifsc FROM cts.scanner_configs "
                        "WHERE scanner_config_id = $1 AND bank_id = $2",
                        config_id, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404, detail="Scanner config not found")
                    old_path = existing["drop_folder_path"]
                    branch_ifsc = existing["branch_ifsc"]

                    if updates:
                        set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
                        set_clauses += f", updated_at = ${len(updates)+2}"
                        params = [config_id] + [
                            json.dumps(v) if isinstance(v, dict) else v
                            for v in updates.values()
                        ] + [datetime.now(timezone.utc)]
                        await conn.execute(
                            f"UPDATE cts.scanner_configs SET {set_clauses} WHERE scanner_config_id = $1",
                            *params,
                        )
                    row = await conn.fetchrow(
                        "SELECT scanner_config_id, bank_id, branch_id, branch_ifsc, scanner_oem, scanner_model, "
                        "output_format, date_format, amount_format, field_mapping, image_naming_pattern, "
                        "image_side_mapping, drop_folder_path, is_active, created_at, updated_at, created_by "
                        "FROM cts.scanner_configs WHERE scanner_config_id = $1", config_id
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("scanner_configs.update.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
            result = _to_response(dict(row))
        else:
            c = _CONFIG_STORE.get(config_id)
            if not c or c["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail="Scanner config not found")
            old_path = c["drop_folder_path"]
            branch_ifsc = c.get("branch_ifsc", "")
            c.update(updates)
            c["updated_at"] = datetime.now(timezone.utc).isoformat()
            result = _to_response(c)

        audit_payload: dict[str, Any] = {
            "scanner_config_id": config_id,
            "branch_ifsc": branch_ifsc,
            "changed_fields": list(updates.keys()),
            "updated_by": current_user["user_id"],
        }
        if "drop_folder_path" in updates:
            audit_payload["old_drop_folder_path"] = old_path
            audit_payload["new_drop_folder_path"] = updates["drop_folder_path"]

        _write_audit(request, AuditEventType.SCANNER_CONFIG_UPDATED, bank_id, audit_payload)
        _emit_config_changed(request, bank_id, branch_ifsc or "", "updated")
        log.info("scanner_config.updated", bank_id=bank_id, config_id=config_id, changed=list(updates.keys()))
        return result


@router_v1.delete("/{config_id}", response_model=ScannerConfigResponse)
async def delete_config(
    config_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> ScannerConfigResponse:
    if current_user["role"] not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role")

    with tracer.start_as_current_span("scanner_configs.delete") as span:
        bank_id = current_user["bank_id"]
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("config_id", config_id)

        db_pool = _get_db_pool(request)

        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    existing = await conn.fetchrow(
                        "SELECT scanner_config_id, branch_ifsc FROM cts.scanner_configs "
                        "WHERE scanner_config_id = $1 AND bank_id = $2",
                        config_id, bank_id,
                    )
                    if not existing:
                        raise HTTPException(status_code=404, detail="Scanner config not found")
                    branch_ifsc = existing["branch_ifsc"]
                    await conn.execute(
                        "UPDATE cts.scanner_configs SET is_active = false, updated_at = $2 "
                        "WHERE scanner_config_id = $1",
                        config_id, datetime.now(timezone.utc),
                    )
                    row = await conn.fetchrow(
                        "SELECT scanner_config_id, bank_id, branch_id, branch_ifsc, scanner_oem, scanner_model, "
                        "output_format, date_format, amount_format, field_mapping, image_naming_pattern, "
                        "image_side_mapping, drop_folder_path, is_active, created_at, updated_at, created_by "
                        "FROM cts.scanner_configs WHERE scanner_config_id = $1", config_id
                    )
            except HTTPException:
                raise
            except Exception as exc:
                log.error("scanner_configs.delete.db_error", error=str(exc))
                raise HTTPException(status_code=500, detail="Database error")
            result = _to_response(dict(row))
        else:
            c = _CONFIG_STORE.get(config_id)
            if not c or c["bank_id"] != bank_id:
                raise HTTPException(status_code=404, detail="Scanner config not found")
            branch_ifsc = c.get("branch_ifsc", "")
            c["is_active"] = False
            c["updated_at"] = datetime.now(timezone.utc).isoformat()
            result = _to_response(c)

        _write_audit(request, AuditEventType.SCANNER_CONFIG_DELETED, bank_id, {
            "scanner_config_id": config_id,
            "branch_ifsc": branch_ifsc,
            "deleted_by": current_user["user_id"],
        })
        _emit_config_changed(request, bank_id, branch_ifsc or "", "deleted")
        log.info("scanner_config.deleted", bank_id=bank_id, config_id=config_id)
        return result
