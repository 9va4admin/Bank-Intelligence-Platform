"""
CTS Outward Core router — scanner upload, lot management, vault upload, clearing session.

Routes:
  POST  /v1/cts/outward/scan/upload-url
  GET   /v1/cts/outward/scan/image
  POST  /v1/cts/outward/scan/submit
  GET   /v1/cts/outward/hub-summary
  PATCH /v1/cts/outward/lots/{lot_id}/seal
  POST  /v1/cts/outward/lots/seal-all
  GET   /v1/cts/outward/sessions/{session_id}/report
  POST  /v1/cts/vault/upload/{vault_type}
  GET   /v1/cts/vault/batches/{batch_id}
  GET   /v1/cts/vault/batches/{batch_id}/errors.csv
  POST  /v1/cts/outward/scanner/session/open
  POST  /v1/cts/outward/scanner/session/close
  POST  /v1/cts/outward/clearing-session/submit
  GET   /v1/cts/outward/clearing-window
"""
import csv as _csv
import io as _io
import time
from datetime import date, datetime, timezone
from typing import List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from apps.api.routers.cts_deps import (
    get_bank_id_scanner_or_user,
    get_current_user_context,
    get_current_bank_id,
    get_temporal_client,
    get_kafka_producer,
)
from shared.auth.rbac import Role, UserContext
from shared.config.config_service import config_service

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS Outward Core v1"])

_CTS_IMAGES_BUCKET = "cts-images"
_UPLOAD_URL_EXPIRY_SECONDS = 300

_HUB_READ_ROLES  = {"bank_it_admin", "platform_admin", "ops_manager"}
_HUB_WRITE_ROLES = {"bank_it_admin", "platform_admin", "ops_manager"}
_HUB_SUBMIT_ROLES = {"ops_manager", "bank_it_admin"}
_SESSION_OPEN_ROLES = {"ops_manager", "ops_reviewer", "bank_it_admin", "branch_manager"}

_VAULT_TABLE_MAP: dict[str, str] = {
    "PPS":            "cts.pps_vault_entries",
    "CHEQUE_BOOK":    "cts.cheque_books",
    "LEAF_STATUS":    "cts.cheque_leaves",
    "ACCOUNT_DETAIL": "cts.account_vault_detail",
    "SIGNATURE":      "cts.account_signatories",
}
_VALID_VAULT_TYPES = frozenset(_VAULT_TABLE_MAP)

_HUB_SUMMARY_SQL = """
    SELECT
        b.branch_id,
        b.branch_name,
        b.branch_ifsc,
        COALESCE(s.hub_type, 'EEH')         AS hub_type,
        COALESCE(r.health, 'UNKNOWN')        AS scanner_health,
        s.session_id,
        s.status                             AS session_status,
        s.opened_at,
        s.total_uploaded,
        s.total_accepted,
        s.total_rejected,
        COALESCE(s.total_held, 0)            AS total_held,
        cl.lot_id                            AS current_lot_id,
        cl.instrument_count                  AS current_lot_filled,
        cl.max_instruments                   AS current_lot_max,
        cl.status                            AS current_lot_status,
        COALESCE(sl.sealed_count, 0)         AS lots_sealed_today
    FROM cts.branches b
    LEFT JOIN cts.eeh_sessions s
        ON  s.branch_id     = b.branch_id
        AND s.clearing_date = $2
        AND s.status        = 'ACTIVE'
    LEFT JOIN cts.scanner_registrations r
        ON  r.branch_id = b.branch_id
        AND r.bank_id   = $1
        AND r.is_active = true
    LEFT JOIN cts.lots cl
        ON  cl.branch_id     = b.branch_id
        AND cl.clearing_date = $2
        AND cl.status        = 'OPEN'
    LEFT JOIN (
        SELECT branch_id, COUNT(*) AS sealed_count
        FROM cts.lots
        WHERE bank_id = $1 AND clearing_date = $2 AND status = 'SEALED'
        GROUP BY branch_id
    ) sl ON sl.branch_id = b.branch_id
    WHERE b.bank_id = $1
    ORDER BY b.branch_id
"""


# ─── Models ──────────────────────────────────────────────────────────────────

class ScanUploadURLRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    include_uv: bool = False


class ScanUploadURLResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    front_presigned_url: str
    rear_presigned_url: str
    front_object_url: str
    rear_object_url: str
    uv_presigned_url: Optional[str] = None
    uv_object_url: Optional[str] = None
    expires_at: int


class OutwardScanSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    instrument_id: str
    bank_ifsc: str
    session_id: str
    image_front_url: str
    image_rear_url: str
    cheque_number: str = ""
    front_dpi: Optional[int] = None
    rear_dpi: Optional[int] = None
    front_colour_depth: Optional[int] = None
    rear_colour_depth: Optional[int] = None
    front_file_size_kb: Optional[float] = None
    rear_file_size_kb: Optional[float] = None
    micr_hardware_raw: Optional[str] = None
    image_uv_url: Optional[str] = None
    pu_id: Optional[str] = None
    branch_id: Optional[str] = None


class OutwardScanSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    instrument_id: str
    workflow_id: str
    status: Literal["ACCEPTED"]
    path: str


class LotInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_id: str
    filled: int
    max:    int
    status: str


class BranchSessionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id:      str
    status:          str
    opened_at:       str
    total_uploaded:  int
    total_accepted:  int
    total_rejected:  int
    total_held:      int = 0


class BranchSessionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id:         str
    branch_name:       str
    branch_ifsc:       str
    hub_type:          str
    scanner_health:    str
    session:           Optional[BranchSessionInfo]
    current_lot:       Optional[LotInfo] = None
    lots_sealed_today: int = 0


class HubSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id:         str
    clearing_date:   str
    branches:        list[BranchSessionSummary]
    total_branches:  int
    active_sessions: int
    generated_at:    str


class SessionReportMeta(BaseModel):
    model_config = ConfigDict(frozen=True)
    report_id:        str
    session_id:       str
    bank_id:          str
    branch_ifsc:      str
    clearing_date:    str
    session_type:     str
    generated_at:     str
    instrument_count: int
    accepted_count:   int
    rejected_count:   int
    held_count:       int
    compliance_pass_count: int
    compliance_fail_count: int
    status:           str
    html_url:         Optional[str] = None
    pdf_url:          Optional[str] = None


class VaultUploadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    vault_type: str
    db_table: str
    status: str
    rows_total: int
    rows_processed: int
    rows_failed: int
    errors_preview: list[dict]


class VaultBatchStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    vault_type: str
    db_table: str
    filename: Optional[str]
    upload_channel: str
    uploaded_by: str
    status: str
    rows_total: int
    rows_processed: int
    rows_failed: int
    errors_preview: list[dict]
    error_file_path: Optional[str]
    has_error_file: bool
    created_at: float
    completed_at: Optional[float]


class ScannerSessionOpenRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    branch_id: str
    hub_type: str = "EEH"
    cert_fingerprint: str


class ScannerSessionOpenResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    branch_id: str
    bank_id: str
    hub_type: str
    status: Literal["ACTIVE"]
    clearing_date: str
    opened_at: str


class ScannerSessionCloseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str


class ScannerSessionCloseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    status: Literal["CLOSED"]
    closed_at: str


class ClearingSessionSubmitRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    clearing_date: str
    session_type: str = "MORNING"
    deployment_mode: str = "SB_NGCH"
    pu_ids: list[str] = []


class ClearingSessionSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    bank_id: str
    clearing_date: str
    session_type: str
    status: Literal["STARTED"]
    message: str


class ClearingWindowResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    open_time_utc: str
    close_time_utc: str
    clearing_date: str
    is_open: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _row_to_branch_summary(row: dict) -> BranchSessionSummary:
    session = None
    if row.get("session_id") is not None:
        opened = row["opened_at"]
        opened_str = opened.isoformat() if hasattr(opened, "isoformat") else str(opened)
        session = BranchSessionInfo(
            session_id=row["session_id"],
            status=row["session_status"] or "ACTIVE",
            opened_at=opened_str,
            total_uploaded=row["total_uploaded"] or 0,
            total_accepted=row["total_accepted"] or 0,
            total_rejected=row["total_rejected"] or 0,
            total_held=row.get("total_held") or 0,
        )
    current_lot = None
    if row.get("current_lot_id") is not None:
        current_lot = LotInfo(
            lot_id=row["current_lot_id"],
            filled=row["current_lot_filled"] or 0,
            max=row["current_lot_max"] or 25,
            status=row["current_lot_status"] or "OPEN",
        )
    return BranchSessionSummary(
        branch_id=row["branch_id"],
        branch_name=row["branch_name"],
        branch_ifsc=row["branch_ifsc"],
        hub_type=row.get("hub_type") or "EEH",
        scanner_health=row.get("scanner_health") or "UNKNOWN",
        session=session,
        current_lot=current_lot,
        lots_sealed_today=row.get("lots_sealed_today") or 0,
    )


async def _ensure_open_lot(
    conn,
    bank_id: str,
    branch_id: str,
    session_id: str,
    clearing_date,
    max_instruments: int = 25,
) -> tuple[str, int]:
    """Find or create the OPEN scanning batch lot. Auto-seals and opens next when full."""
    row = await conn.fetchrow(
        "SELECT lot_id, instrument_count, max_instruments "
        "FROM cts.lots "
        "WHERE branch_id = $1 AND clearing_date = $2 AND status = 'OPEN'",
        branch_id, clearing_date,
    )

    if row is None:
        seq_row = await conn.fetchrow(
            "SELECT COALESCE(MAX(sequence_number), 0) AS max_seq "
            "FROM cts.lots WHERE branch_id = $1 AND clearing_date = $2",
            branch_id, clearing_date,
        )
        seq = (seq_row["max_seq"] or 0) + 1
        date_str = clearing_date.strftime("%Y%m%d") if hasattr(clearing_date, "strftime") else str(clearing_date).replace("-", "")
        lot_id = f"LOT-{branch_id}-{date_str}-{seq:04d}"
        await conn.execute(
            "INSERT INTO cts.lots "
            "(lot_id, bank_id, branch_id, session_id, clearing_date, sequence_number, "
            " status, instrument_count, max_instruments) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'OPEN', 1, $7)",
            lot_id, bank_id, branch_id, session_id, clearing_date, seq, max_instruments,
        )
        return lot_id, 1

    lot_id = row["lot_id"]
    new_count = row["instrument_count"] + 1

    if new_count >= row["max_instruments"]:
        await conn.execute(
            "UPDATE cts.lots SET status='SEALED', instrument_count=$1, sealed_at=NOW() "
            "WHERE lot_id=$2",
            new_count, lot_id,
        )
        return await _ensure_open_lot(conn, bank_id, branch_id, session_id, clearing_date, max_instruments)

    await conn.execute(
        "UPDATE cts.lots SET instrument_count=$1 WHERE lot_id=$2",
        new_count, lot_id,
    )
    return lot_id, new_count


def _vault_status(rows_processed: int, rows_failed: int) -> str:
    if rows_processed == 0 and rows_failed > 0:
        return "FAILED"
    if rows_failed > 0:
        return "PARTIAL"
    return "COMPLETE"


def _publish_vault_batch_event(
    kafka_producer,
    *,
    batch_id: str,
    bank_id: str,
    vault_type: str,
    status: str,
    rows_total: int,
    rows_processed: int,
    rows_failed: int,
) -> None:
    """Emit Kafka event on PARTIAL or FAILED batch → alert dispatcher."""
    if kafka_producer is None or rows_failed == 0:
        return
    event_type = "VAULT_BATCH_FAILED" if rows_processed == 0 else "VAULT_BATCH_PARTIAL"
    try:
        kafka_producer.publish(
            topic="platform.audit.events",
            event_type=event_type,
            payload={
                "batch_id": batch_id,
                "vault_type": vault_type,
                "db_table": _VAULT_TABLE_MAP.get(vault_type, "unknown"),
                "bank_id": bank_id,
                "rows_total": rows_total,
                "rows_processed": rows_processed,
                "rows_failed": rows_failed,
            },
            bank_id=bank_id,
        )
        log.warning(
            "vault.batch_alert_emitted",
            batch_id=batch_id,
            bank_id=bank_id,
            vault_type=vault_type,
            event_type=event_type,
            rows_failed=rows_failed,
        )
    except Exception as exc:
        log.error("vault.batch_alert_publish_failed", batch_id=batch_id, error=str(exc))


# ─── Routes ──────────────────────────────────────────────────────────────────

@router_v1.post(
    "/outward/scan/upload-url",
    response_model=ScanUploadURLResponse,
    status_code=status.HTTP_200_OK,
)
async def request_scan_upload_urls(
    body: ScanUploadURLRequest,
    request: Request,
    bank_id: str = Depends(get_bank_id_scanner_or_user),
) -> ScanUploadURLResponse:
    from datetime import timedelta as _td

    front_key = f"{bank_id}/outward/{body.scan_id}/front.tiff"
    rear_key  = f"{bank_id}/outward/{body.scan_id}/rear.tiff"
    uv_key    = f"{bank_id}/outward/{body.scan_id}/uv.tiff"

    front_obj = f"s3://{_CTS_IMAGES_BUCKET}/{front_key}"
    rear_obj  = f"s3://{_CTS_IMAGES_BUCKET}/{rear_key}"
    uv_obj    = f"s3://{_CTS_IMAGES_BUCKET}/{uv_key}"

    expires_at = int(time.time()) + _UPLOAD_URL_EXPIRY_SECONDS

    minio_store = getattr(request.app.state, "minio_store", None)
    if minio_store is not None:
        try:
            front_url = await minio_store.presigned_put_url(
                _CTS_IMAGES_BUCKET, front_key, expiry_seconds=_UPLOAD_URL_EXPIRY_SECONDS)
            rear_url  = await minio_store.presigned_put_url(
                _CTS_IMAGES_BUCKET, rear_key,  expiry_seconds=_UPLOAD_URL_EXPIRY_SECONDS)
            uv_url    = await minio_store.presigned_put_url(
                _CTS_IMAGES_BUCKET, uv_key, expiry_seconds=_UPLOAD_URL_EXPIRY_SECONDS) if body.include_uv else None
        except Exception as exc:
            log.error("cts.upload_url.minio_error", scan_id=body.scan_id, bank_id=bank_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not provision upload URLs — MinIO unavailable",
            ) from exc
    else:
        front_url = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{front_key}?presigned=1"
        rear_url  = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{rear_key}?presigned=1"
        uv_url    = f"http://minio-dev.local/{_CTS_IMAGES_BUCKET}/{uv_key}?presigned=1" if body.include_uv else None

    log.info("cts.upload_url.issued", scan_id=body.scan_id, bank_id=bank_id, include_uv=body.include_uv)

    return ScanUploadURLResponse(
        front_presigned_url=front_url,
        rear_presigned_url=rear_url,
        front_object_url=front_obj,
        rear_object_url=rear_obj,
        uv_presigned_url=uv_url,
        uv_object_url=uv_obj if body.include_uv else None,
        expires_at=expires_at,
    )


@router_v1.get(
    "/outward/scan/image",
    response_model=None,
    tags=["CTS Outward"],
)
async def get_scan_image_url(
    scan_id: str,
    view: str = "front_bw",
    request: Request = None,
    bank_id: str = Depends(get_bank_id_scanner_or_user),
):
    _VIEW_TO_KEY = {
        "front_bw":   "front.tiff",
        "rear_bw":    "rear.tiff",
        "front_gray": "front.tiff",
        "uv":         "uv.tiff",
    }
    filename = _VIEW_TO_KEY.get(view, "front.tiff")
    object_key = f"{bank_id}/outward/{scan_id}/{filename}"

    minio_store = getattr(request.app.state, "minio_store", None) if request else None
    if minio_store is None:
        raise HTTPException(status_code=503, detail="Image store unavailable")

    try:
        raw_bytes = await minio_store.download_bytes(_CTS_IMAGES_BUCKET, object_key)
    except Exception as exc:
        log.warning("cts.scan_image_download_error", scan_id=scan_id, view=view, error=str(exc))
        raise HTTPException(status_code=404, detail="Image not found") from exc

    try:
        import io
        from PIL import Image as _PILImage
        buf_in  = io.BytesIO(raw_bytes)
        buf_out = io.BytesIO()
        img = _PILImage.open(buf_in)
        img = img.convert("L")
        img.save(buf_out, format="JPEG", quality=85)
        buf_out.seek(0)
        return StreamingResponse(buf_out, media_type="image/jpeg",
                                 headers={"Cache-Control": "private, max-age=300"})
    except Exception as exc:
        log.warning("cts.scan_image_convert_error", scan_id=scan_id, error=str(exc))
        return StreamingResponse(io.BytesIO(raw_bytes), media_type="image/tiff")


@router_v1.post(
    "/outward/scan/submit",
    response_model=OutwardScanSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_outward_scan(
    body: OutwardScanSubmitRequest,
    request: Request,
    response: Response,
    bank_id: str = Depends(get_bank_id_scanner_or_user),
) -> OutwardScanSubmitResponse:
    workflow_id = f"cts-outscan-{bank_id}-{body.scan_id}"
    if body.pu_id:
        workflow_id = f"cts-outscan-{bank_id}-{body.pu_id}-{body.scan_id}"

    from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow, OutwardScanInput

    workflow_input = OutwardScanInput(
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        bank_id=bank_id,
        bank_ifsc=body.bank_ifsc,
        session_id=body.session_id,
        image_front_url=body.image_front_url,
        image_rear_url=body.image_rear_url,
        cheque_number=body.cheque_number,
        front_dpi=body.front_dpi,
        rear_dpi=body.rear_dpi,
        front_colour_depth=body.front_colour_depth,
        rear_colour_depth=body.rear_colour_depth,
        front_file_size_kb=body.front_file_size_kb,
        rear_file_size_kb=body.rear_file_size_kb,
        micr_hardware_raw=body.micr_hardware_raw,
        image_uv_url=body.image_uv_url,
        pu_id=body.pu_id,
        branch_id=body.branch_id,
    )

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is not None:
        try:
            from datetime import timedelta as _td
            from temporalio.exceptions import WorkflowAlreadyStartedError
            await temporal_client.start_workflow(
                OutwardScanWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=f"cts-processing-{bank_id}",
                execution_timeout=_td(hours=24),
            )
        except WorkflowAlreadyStartedError:
            pass
        except Exception as exc:
            log.error(
                "cts.outward_scan_workflow_error",
                scan_id=body.scan_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to start OutwardScanWorkflow",
            ) from exc

    path = "CR120" if body.micr_hardware_raw else "LEGACY"

    if body.session_id and body.branch_id:
        state = getattr(getattr(request, "app", None), "state", None)
        _db_pool = getattr(state, "db_pool_cts", None) if state else None
        if _db_pool is not None:
            try:
                async with _db_pool.acquire() as _conn:
                    await _conn.execute(
                        "UPDATE cts.eeh_sessions SET total_uploaded = total_uploaded + 1 "
                        "WHERE session_id = $1",
                        body.session_id,
                    )
                    await _ensure_open_lot(
                        _conn,
                        bank_id=bank_id,
                        branch_id=body.branch_id,
                        session_id=body.session_id,
                        clearing_date=date.today(),
                    )
            except Exception as _lot_exc:
                log.warning(
                    "cts.outward_scan.lot_tracking_error",
                    scan_id=body.scan_id, bank_id=bank_id, error=str(_lot_exc),
                )

    log.info(
        "cts.outward_scan_submitted",
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
        path=path,
    )

    response.headers["X-Workflow-Id"] = workflow_id
    return OutwardScanSubmitResponse(
        scan_id=body.scan_id,
        instrument_id=body.instrument_id,
        workflow_id=workflow_id,
        status="ACCEPTED",
        path=path,
    )


@router_v1.get("/outward/hub-summary", response_model=HubSummaryResponse)
async def get_hub_summary(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> HubSummaryResponse:
    if ctx.role.value not in _HUB_READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = ctx.bank_id
    today = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).isoformat()
    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None

    if db_pool is None:
        return HubSummaryResponse(
            bank_id=bank_id, clearing_date=today,
            branches=[], total_branches=0, active_sessions=0, generated_at=generated_at,
        )

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(_HUB_SUMMARY_SQL, bank_id, today)
    except Exception as exc:
        log.error("cts.hub_summary.db_error", bank_id=bank_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Database error")

    branches = [_row_to_branch_summary(dict(r)) for r in rows]
    active = sum(1 for b in branches if b.session is not None)
    return HubSummaryResponse(
        bank_id=bank_id, clearing_date=today,
        branches=branches, total_branches=len(branches),
        active_sessions=active, generated_at=generated_at,
    )


@router_v1.patch("/outward/lots/{lot_id}/seal")
async def seal_lot(
    lot_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> dict:
    if ctx.role.value not in _HUB_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None
    if db_pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    bank_id = ctx.bank_id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lot_id, bank_id, status, instrument_count FROM cts.lots WHERE lot_id=$1",
            lot_id,
        )
        if row is None or row["bank_id"] != bank_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lot not found")
        if row["status"] != "OPEN":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Lot is already {row['status']}")
        await conn.execute(
            "UPDATE cts.lots SET status='SEALED', sealed_at=NOW() WHERE lot_id=$1",
            lot_id,
        )

    log.info("cts.lot.sealed", lot_id=lot_id, bank_id=bank_id, operator=ctx.user_id)
    return {"lot_id": lot_id, "status": "SEALED", "sealed_by": ctx.user_id}


@router_v1.post("/outward/lots/seal-all")
async def seal_all_lots(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> dict:
    if ctx.role.value not in _HUB_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    state = getattr(getattr(request, "app", None), "state", None)
    db_pool = getattr(state, "db_pool_cts", None) if state else None
    if db_pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    bank_id = ctx.bank_id
    today = date.today()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT lot_id FROM cts.lots WHERE bank_id=$1 AND clearing_date=$2 AND status='OPEN'",
            bank_id, today,
        )
        for row in rows:
            await conn.execute(
                "UPDATE cts.lots SET status='SEALED', sealed_at=NOW() WHERE lot_id=$1",
                row["lot_id"],
            )

    sealed = len(rows)
    log.info("cts.lots.seal_all", bank_id=bank_id, sealed=sealed, operator=ctx.user_id)
    return {"bank_id": bank_id, "sealed": sealed, "sealed_by": ctx.user_id}


@router_v1.get(
    "/outward/sessions/{session_id}/report",
    response_model=SessionReportMeta,
    status_code=status.HTTP_200_OK,
)
async def get_session_report(
    session_id: str,
    request: Request,
    format: Optional[str] = None,
    ctx: UserContext = Depends(get_current_user_context),
) -> SessionReportMeta:
    bank_id = ctx.bank_id
    allowed = {"ops_manager", "bank_it_admin", "ops_reviewer", "fraud_analyst"}
    if ctx.role.value not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable")

    row = await db.fetchrow(
        """
        SELECT report_id, session_id, bank_id, branch_id, branch_ifsc,
               clearing_date, session_type, generated_at,
               instrument_count, lot_count,
               accepted_count, rejected_count, held_count,
               compliance_pass_count, compliance_fail_count,
               html_minio_path, pdf_minio_path, status
        FROM cts.session_reports
        WHERE session_id = $1 AND bank_id = $2
        """,
        session_id, bank_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    html_url = pdf_url = None

    if format in ("html", "pdf") and row["status"] == "READY":
        from shared.config.config_service import config_service
        from minio import Minio  # type: ignore
        from datetime import timedelta

        minio_ep = await config_service.get("minio.endpoint")
        minio_ak = await config_service.get_secret("minio.access_key")
        minio_sk = await config_service.get_secret("minio.secret_key")
        client = Minio(minio_ep, access_key=minio_ak, secret_key=minio_sk, secure=False)
        bucket = "astra-cts-reports"
        path_key = "html_minio_path" if format == "html" else "pdf_minio_path"
        object_path = row[path_key]
        if object_path:
            url = client.presigned_get_object(bucket, object_path, expires=timedelta(minutes=15))
            if format == "html":
                html_url = url
            else:
                pdf_url = url

    log.info(
        "cts.session_report.fetched",
        session_id=session_id,
        bank_id=bank_id,
        status=row["status"],
        format=format,
    )

    return SessionReportMeta(
        report_id=str(row["report_id"]),
        session_id=row["session_id"],
        bank_id=row["bank_id"],
        branch_ifsc=row["branch_ifsc"],
        clearing_date=str(row["clearing_date"]),
        session_type=row["session_type"],
        generated_at=row["generated_at"].isoformat(),
        instrument_count=row["instrument_count"],
        accepted_count=row["accepted_count"],
        rejected_count=row["rejected_count"],
        held_count=row["held_count"],
        compliance_pass_count=row["compliance_pass_count"],
        compliance_fail_count=row["compliance_fail_count"],
        status=row["status"],
        html_url=html_url,
        pdf_url=pdf_url,
    )


@router_v1.post(
    "/vault/upload/{vault_type}",
    response_model=VaultUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_vault_csv(
    vault_type: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: UserContext = Depends(get_current_user_context),
) -> VaultUploadResponse:
    bank_id = ctx.bank_id
    vault_type = vault_type.upper()

    if vault_type not in _VALID_VAULT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_UNKNOWN_TYPE",
                "message": f"vault_type must be one of {sorted(_VALID_VAULT_TYPES)}",
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_EMPTY_FILE",
                "message": "Uploaded file is empty",
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        )

    db_pool = getattr(request.app.state, "db_pool", None)
    vaults: dict = getattr(request.app.state, "vault_instances", {}) or {}
    minio_client = getattr(request.app.state, "minio_client", None)

    from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor

    error_file_bucket: Optional[str] = None
    if minio_client is not None:
        try:
            error_file_bucket = await config_service.get("vault.error_files.bucket")
        except Exception:
            error_file_bucket = "astra-vault-errors"

    processor = VaultUploadProcessor(
        bank_id=bank_id,
        db_pool=db_pool,
        cheque_leaf_vault=vaults.get("cheque_leaf"),
        account_vault=vaults.get("account"),
        signature_vault=vaults.get("signature"),
        pps_vault=vaults.get("pps"),
        minio_client=minio_client,
        error_file_bucket=error_file_bucket,
    )

    try:
        result = await processor.process(
            vault_type=vault_type,
            csv_content=csv_bytes,
            changed_by=f"user:{ctx.user_id}",
            filename=file.filename,
            upload_channel="UI",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_PARSE_ERROR",
                "message": str(exc),
                "request_id": request.headers.get("X-Request-Id", ""),
            },
        ) from exc

    batch_status = _vault_status(result.rows_processed, result.rows_failed)

    _publish_vault_batch_event(
        get_kafka_producer(request),
        batch_id=result.batch_id,
        bank_id=bank_id,
        vault_type=vault_type,
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
    )

    log.info(
        "vault.upload_complete",
        batch_id=result.batch_id,
        bank_id=bank_id,
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP[vault_type],
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
    )

    return VaultUploadResponse(
        batch_id=result.batch_id,
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP[vault_type],
        status=batch_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
        errors_preview=result.errors[:20],
    )


@router_v1.get(
    "/vault/batches/{batch_id}",
    response_model=VaultBatchStatusResponse,
)
async def get_vault_batch_status(
    batch_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> VaultBatchStatusResponse:
    bank_id = ctx.bank_id
    db_pool = getattr(request.app.state, "db_pool", None)

    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Database pool not ready"},
        )

    import json as _json
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, bank_id, vault_type, filename, upload_channel,
                   uploaded_by, status, rows_total, rows_processed, rows_failed,
                   errors_json, error_file_path, created_at, completed_at
            FROM cts.vault_upload_batches
            WHERE id=$1 AND bank_id=$2
            """,
            batch_id, bank_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "VAULT_BATCH_NOT_FOUND",
                "message": f"Batch {batch_id!r} not found for bank {bank_id!r}",
            },
        )

    vault_type = row["vault_type"]
    errors_raw = row["errors_json"] or []
    errors_list: list[dict] = _json.loads(errors_raw) if isinstance(errors_raw, str) else (errors_raw or [])
    efp: Optional[str] = row["error_file_path"]

    return VaultBatchStatusResponse(
        batch_id=str(row["id"]),
        bank_id=row["bank_id"],
        vault_type=vault_type,
        db_table=_VAULT_TABLE_MAP.get(vault_type, "unknown"),
        filename=row["filename"],
        upload_channel=row["upload_channel"],
        uploaded_by=row["uploaded_by"],
        status=row["status"],
        rows_total=row["rows_total"],
        rows_processed=row["rows_processed"],
        rows_failed=row["rows_failed"],
        errors_preview=errors_list[:20],
        error_file_path=efp,
        has_error_file=efp is not None,
        created_at=row["created_at"].timestamp() if row["created_at"] else 0.0,
        completed_at=row["completed_at"].timestamp() if row["completed_at"] else None,
    )


@router_v1.get("/vault/batches/{batch_id}/errors.csv")
async def download_vault_batch_errors(
    batch_id: str,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> StreamingResponse:
    bank_id = ctx.bank_id
    db_pool = getattr(request.app.state, "db_pool", None)

    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "DB_UNAVAILABLE", "message": "Database pool not ready"},
        )

    import json as _json

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT vault_type, status, rows_failed, errors_json, error_file_path
            FROM cts.vault_upload_batches
            WHERE id=$1 AND bank_id=$2
            """,
            batch_id, bank_id,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "VAULT_BATCH_NOT_FOUND",
                "message": f"Batch {batch_id!r} not found for bank {bank_id!r}",
            },
        )

    filename = f"vault_errors_{batch_id[:8]}.csv"
    efp: Optional[str] = row["error_file_path"]
    minio_client = getattr(request.app.state, "minio_client", None)

    if efp and minio_client is not None:
        try:
            try:
                bucket = await config_service.get("vault.error_files.bucket")
            except Exception:
                bucket = "astra-vault-errors"
            stream = minio_client.get_object(bucket, efp)
            return StreamingResponse(
                stream,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as exc:
            log.warning(
                "vault.download_minio_fallback",
                batch_id=batch_id,
                bank_id=bank_id,
                error_file_path=efp,
                error=str(exc),
            )

    errors_raw = row["errors_json"] or []
    errors_list: list[dict] = _json.loads(errors_raw) if isinstance(errors_raw, str) else (errors_raw or [])

    def _generate_csv():
        buf = _io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=["row_number", "error_message"])
        writer.writeheader()
        yield buf.getvalue()
        for err in errors_list:
            buf = _io.StringIO()
            writer = _csv.DictWriter(buf, fieldnames=["row_number", "error_message"])
            writer.writerow({"row_number": err.get("row", ""), "error_message": err.get("error", "")})
            yield buf.getvalue()

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router_v1.post(
    "/outward/scanner/session/open",
    response_model=ScannerSessionOpenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_scanner_session(
    body: ScannerSessionOpenRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ScannerSessionOpenResponse:
    if ctx.role.value not in _SESSION_OPEN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable")

    import uuid as _uuid
    from datetime import date as _date, datetime as _dt, timezone as _tz

    today = _date.today()
    session_id = f"SES-{_uuid.uuid4().hex[:12].upper()}"

    async with db.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT session_id FROM cts.eeh_sessions "
            "WHERE branch_id = $1 AND clearing_date = $2 AND status = 'ACTIVE'",
            body.branch_id, today,
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Active session {existing['session_id']} already open for this branch today",
            )
        expires_at = _dt.now(_tz.utc).replace(hour=18, minute=0, second=0, microsecond=0)
        await conn.execute(
            """
            INSERT INTO cts.eeh_sessions
                (session_id, bank_id, branch_id, operator_id, cert_fingerprint,
                 hub_type, status, clearing_date, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', $7, $8)
            """,
            session_id, bank_id, body.branch_id, ctx.user_id,
            body.cert_fingerprint, body.hub_type, today, expires_at,
        )
    now_str = _dt.now(_tz.utc).isoformat()
    log.info("cts.scanner_session.opened", session_id=session_id, branch_id=body.branch_id, bank_id=bank_id)
    return ScannerSessionOpenResponse(
        session_id=session_id,
        branch_id=body.branch_id,
        bank_id=bank_id,
        hub_type=body.hub_type,
        status="ACTIVE",
        clearing_date=today.isoformat(),
        opened_at=now_str,
    )


@router_v1.post(
    "/outward/scanner/session/close",
    response_model=ScannerSessionCloseResponse,
    status_code=status.HTTP_200_OK,
)
async def close_scanner_session(
    body: ScannerSessionCloseRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ScannerSessionCloseResponse:
    if ctx.role.value not in _SESSION_OPEN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
    bank_id = ctx.bank_id
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DB unavailable")

    from datetime import datetime as _dt, timezone as _tz

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT session_id, status, bank_id FROM cts.eeh_sessions WHERE session_id = $1",
            body.session_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if row["bank_id"] != bank_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-bank session close forbidden")
        if row["status"] != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session is already {row['status']}",
            )
        closed_at = _dt.now(_tz.utc)
        await conn.execute(
            "UPDATE cts.eeh_sessions SET status='CLOSED', closed_at=$1 WHERE session_id=$2",
            closed_at, body.session_id,
        )
    log.info("cts.scanner_session.closed", session_id=body.session_id, bank_id=bank_id)
    return ScannerSessionCloseResponse(
        session_id=body.session_id,
        status="CLOSED",
        closed_at=closed_at.isoformat(),
    )


@router_v1.post(
    "/outward/clearing-session/submit",
    response_model=ClearingSessionSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_clearing_session(
    body: ClearingSessionSubmitRequest,
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClearingSessionSubmitResponse:
    if ctx.role.value not in _HUB_SUBMIT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hub submit requires ops_manager or bank_it_admin")
    bank_id = ctx.bank_id
    temporal = get_temporal_client(request)
    if temporal is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Temporal unavailable")

    from modules.cts.workflows.clearing_session_workflow import (
        ClearingSessionWorkflow,
        ClearingSessionInput,
        DeploymentMode,
        SessionType,
    )
    import uuid as _uuid

    clearing_date = body.clearing_date
    session_type = body.session_type
    workflow_id = f"cts-clearsess-{bank_id}-{clearing_date}-{session_type}"

    inp = ClearingSessionInput(
        session_id=f"clearsess-{_uuid.uuid4().hex[:8]}",
        bank_id=bank_id,
        clearing_date=clearing_date,
        session_type=SessionType(session_type),
        deployment_mode=DeploymentMode(body.deployment_mode),
        pu_ids=body.pu_ids,
    )
    await temporal.start_workflow(
        ClearingSessionWorkflow.run,
        inp,
        id=workflow_id,
        task_queue=f"cts-processing-{bank_id}",
        id_reuse_policy="ALLOW_DUPLICATE_FAILED_ONLY",
    )
    log.info("cts.clearing_session.submitted", workflow_id=workflow_id, bank_id=bank_id)
    return ClearingSessionSubmitResponse(
        workflow_id=workflow_id,
        bank_id=bank_id,
        clearing_date=clearing_date,
        session_type=session_type,
        status="STARTED",
        message=f"ClearingSessionWorkflow {workflow_id} started — NGCH filing in progress.",
    )


@router_v1.get("/outward/clearing-window", response_model=ClearingWindowResponse)
async def get_clearing_window(
    request: Request,
    ctx: UserContext = Depends(get_current_user_context),
) -> ClearingWindowResponse:
    bank_id = ctx.bank_id
    from datetime import date as _date, datetime as _dt, timezone as _tz

    config_svc = getattr(request.app.state, "config_service", None)
    open_hour, close_hour = 3, 14
    if config_svc is not None:
        try:
            cfg = await config_svc.get_cts_config(bank_id)
            open_hour  = int(cfg.get("clearing_open_hour_utc",  3))
            close_hour = int(cfg.get("clearing_close_hour_utc", 14))
        except Exception:
            pass

    now = _dt.now(_tz.utc)
    today = _date.today()
    is_open = open_hour <= now.hour < close_hour
    return ClearingWindowResponse(
        bank_id=bank_id,
        open_time_utc=f"{open_hour:02d}:00",
        close_time_utc=f"{close_hour:02d}:00",
        clearing_date=today.isoformat(),
        is_open=is_open,
    )
