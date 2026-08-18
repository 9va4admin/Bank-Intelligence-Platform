"""
Vault Upload API — upload CSV files to seed / update CTS vault data.

Routes:
  POST /v1/cts/vault/upload/{vault_type}           — manual UI upload
  GET  /v1/cts/vault/upload/template/{vault_type}  — download blank template CSV
  GET  /v1/cts/vault/upload/batches                — list recent upload batches
  POST /v1/cts/vault/upload/file-drop              — MinIO event webhook →
                                                     starts VaultFileDropWorkflow

vault_type values: CHEQUE_BOOK | LEAF_STATUS | ACCOUNT_DETAIL | SIGNATURE | PPS

Role requirement: bank_it_admin (LEAF_STATUS + PPS also allow ops_manager).
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict  # noqa: F401 (ConfigDict used in response models)

from apps.api.dependencies import require_user_context
from shared.auth.rbac import Role, UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/cts/vault/upload", tags=["Vault Upload v1"])

_VALID_VAULT_TYPES = {"CHEQUE_BOOK", "LEAF_STATUS", "ACCOUNT_DETAIL", "SIGNATURE", "PPS"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


async def get_current_user_context(
    ctx: UserContext = Depends(require_user_context),
) -> UserContext:
    return ctx


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UploadBatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    vault_type: str
    status: str
    rows_total: int
    rows_processed: int
    rows_failed: int
    errors: list[dict]
    message: str


class BatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    vault_type: str
    filename: Optional[str]
    upload_channel: str
    uploaded_by: str
    status: str
    rows_total: Optional[int]
    rows_processed: Optional[int]
    rows_failed: Optional[int]
    created_at: str
    completed_at: Optional[str]


class BatchListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[BatchSummary]
    total: int


# ---------------------------------------------------------------------------
# Helper: resolve vault objects from app state
# ---------------------------------------------------------------------------

def _get_vault_upload_deps(request: Request):
    """Return (db_pool, cheque_leaf_vault, account_vault, signature_vault) from app state."""
    db_pool = getattr(request.app.state, "db_pool", None)
    cheque_leaf_vault_factory = getattr(request.app.state, "cheque_leaf_vault_factory", None)
    account_vault_factory = getattr(request.app.state, "account_vault_factory", None)
    signature_vault_factory = getattr(request.app.state, "signature_vault_factory", None)
    return db_pool, cheque_leaf_vault_factory, account_vault_factory, signature_vault_factory


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.post(
    "/{vault_type}",
    response_model=UploadBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_vault_csv(
    vault_type: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: UserContext = Depends(get_current_user_context),
) -> UploadBatchResponse:
    """
    Upload a CSV file to seed or update a vault.

    - bank_it_admin: all vault types
    - ops_manager: LEAF_STATUS only (e.g. marking a leaf lost/stolen at branch)

    The upload is processed synchronously. For large files (>2,000 rows) the
    response may take a few seconds — clients should set a 60s timeout.
    """
    vault_type = vault_type.upper()
    if vault_type not in _VALID_VAULT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_UNKNOWN_TYPE",
                "message": f"Unknown vault_type {vault_type!r}. "
                           f"Valid: {sorted(_VALID_VAULT_TYPES)}",
                "request_id": "",
            },
        )

    # Role check
    if vault_type in ("LEAF_STATUS", "PPS"):
        allowed = {Role.bank_it_admin, Role.ops_manager}
    else:
        allowed = {Role.bank_it_admin}

    if ctx.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "VAULT_UPLOAD_FORBIDDEN",
                "message": f"Role {ctx.role} cannot upload {vault_type}.",
                "request_id": "",
            },
        )

    # Size guard
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error_code": "VAULT_UPLOAD_TOO_LARGE",
                "message": f"File exceeds {_MAX_UPLOAD_BYTES // 1024 // 1024} MB limit.",
                "request_id": "",
            },
        )

    db_pool, clf_factory, av_factory, sv_factory = _get_vault_upload_deps(request)

    # Resolve per-bank vault instances
    cheque_leaf_vault = clf_factory(ctx.bank_id) if clf_factory else None
    account_vault = av_factory(ctx.bank_id) if av_factory else None
    signature_vault = sv_factory(ctx.bank_id) if sv_factory else None

    pps_vault_factory = getattr(request.app.state, "pps_vault_factory", None)
    pps_vault = pps_vault_factory(ctx.bank_id) if pps_vault_factory else None

    from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor
    processor = VaultUploadProcessor(
        bank_id=ctx.bank_id,
        db_pool=db_pool,
        cheque_leaf_vault=cheque_leaf_vault,
        account_vault=account_vault,
        signature_vault=signature_vault,
        pps_vault=pps_vault,
    )

    changed_by = f"user:{ctx.user_id}"
    try:
        result = await processor.process(
            vault_type=vault_type,
            csv_content=content,
            changed_by=changed_by,
            filename=file.filename,
            upload_channel="UI",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "VAULT_UPLOAD_INVALID",
                "message": str(exc),
                "request_id": "",
            },
        )

    final_status = (
        "FAILED" if result.rows_processed == 0
        else "PARTIAL" if result.rows_failed > 0
        else "COMPLETE"
    )
    message = (
        f"Processed {result.rows_processed}/{result.rows_total} rows."
        + (f" {result.rows_failed} failed." if result.rows_failed else "")
    )

    log.info(
        "vault_upload.complete",
        bank_id=ctx.bank_id,
        vault_type=vault_type,
        batch_id=result.batch_id,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
    )

    return UploadBatchResponse(
        batch_id=result.batch_id,
        vault_type=vault_type,
        status=final_status,
        rows_total=result.rows_total,
        rows_processed=result.rows_processed,
        rows_failed=result.rows_failed,
        errors=result.errors[:20],
        message=message,
    )


@router_v1.get(
    "/template/{vault_type}",
    response_class=Response,
)
async def download_template(
    vault_type: str,
    ctx: UserContext = Depends(get_current_user_context),
) -> Response:
    """Return a blank CSV template with headers + one example row."""
    vault_type = vault_type.upper()
    if vault_type not in _VALID_VAULT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "VAULT_UNKNOWN_TYPE", "message": f"Unknown: {vault_type}"},
        )

    from modules.cts.vaults.vault_upload_processor import TEMPLATES
    csv_content = TEMPLATES[vault_type]
    filename = f"astra_{vault_type.lower()}_template.csv"

    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router_v1.get(
    "/batches",
    response_model=BatchListResponse,
)
async def list_upload_batches(
    request: Request,
    vault_type: Optional[str] = None,
    limit: int = 25,
    ctx: UserContext = Depends(get_current_user_context),
) -> BatchListResponse:
    """
    List recent vault upload batches for this bank.
    Filtered by vault_type if provided. Max 100 per page.
    """
    if ctx.role not in {Role.bank_it_admin, Role.ops_manager}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error_code": "VAULT_BATCHES_FORBIDDEN",
                                    "message": "Insufficient role."})
    limit = min(max(1, limit), 100)

    db_pool, *_ = _get_vault_upload_deps(request)
    if db_pool is None:
        return BatchListResponse(items=[], total=0)

    async with db_pool.acquire() as conn:
        where_extras = "AND vault_type=$3" if vault_type else ""
        params = [ctx.bank_id, limit]
        if vault_type:
            params.append(vault_type.upper())

        rows = await conn.fetch(
            f"""
            SELECT id, vault_type, filename, upload_channel, uploaded_by,
                   status, rows_total, rows_processed, rows_failed,
                   created_at, completed_at
            FROM cts.vault_upload_batches
            WHERE bank_id=$1 {where_extras}
            ORDER BY created_at DESC
            LIMIT $2
            """,
            *params,
        )
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM cts.vault_upload_batches
            WHERE bank_id=$1 {where_extras}
            """,
            *([ctx.bank_id] + ([vault_type.upper()] if vault_type else [])),
        )

    items = [
        BatchSummary(
            batch_id=str(r["id"]),
            vault_type=r["vault_type"],
            filename=r["filename"],
            upload_channel=r["upload_channel"],
            uploaded_by=r["uploaded_by"],
            status=r["status"],
            rows_total=r["rows_total"],
            rows_processed=r["rows_processed"],
            rows_failed=r["rows_failed"],
            created_at=r["created_at"].isoformat(),
            completed_at=r["completed_at"].isoformat() if r["completed_at"] else None,
        )
        for r in rows
    ]
    return BatchListResponse(items=items, total=total or 0)


# ---------------------------------------------------------------------------
# File-drop webhook — triggered by MinIO bucket event notification
# ---------------------------------------------------------------------------

class FileDropWebhookBody(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    vault_type: str       # CHEQUE_BOOK | LEAF_STATUS | ACCOUNT_DETAIL | SIGNATURE | PPS
    minio_bucket: str
    minio_key: str        # e.g. "{bank_id}/pps/20260818_batch.csv"
    file_hash: str        # SHA-256 of file bytes — workflow idempotency key
    feed_name: str = "sftp"


class FileDropWebhookResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    workflow_id: str
    bank_id: str
    vault_type: str
    status: str           # ACCEPTED | DUPLICATE_SKIPPED | INVALID


@router_v1.post(
    "/file-drop",
    response_model=FileDropWebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def file_drop_webhook(
    request: Request,
    body: FileDropWebhookBody,
) -> FileDropWebhookResponse:
    """
    MinIO event notification endpoint — called when a CSV file is dropped in
    astra-vault-drops/{bank_id}/{vault_type}/.

    Starts VaultFileDropWorkflow via Temporal.
    Workflow ID is deterministic (bank_id + vault_type + file_hash) so duplicate
    MinIO events for the same file are silently deduplicated.

    No user auth required — this is an internal system-to-system call from MinIO
    event notification, protected by mTLS (Istio) at the service mesh layer.
    """
    vault_type = body.vault_type.upper()
    if vault_type not in _VALID_VAULT_TYPES:
        return FileDropWebhookResponse(
            workflow_id="",
            bank_id=body.bank_id,
            vault_type=vault_type,
            status="INVALID",
        )

    workflow_id = (
        f"cts-vault-drop-{body.bank_id}-{vault_type.lower()}-{body.file_hash[:16]}"
    )

    temporal_client = getattr(request.app.state, "temporal_client", None)
    if temporal_client is None:
        log.warning("vault_file_drop.temporal_unavailable",
                    bank_id=body.bank_id, vault_type=vault_type)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "TEMPORAL_UNAVAILABLE", "message": "Temporal not connected."},
        )

    from modules.cts.workflows.vault_file_drop_workflow import (
        VaultFileDropWorkflow,
        VaultFileDropInput,
    )
    from temporalio.client import WorkflowAlreadyStartedError

    try:
        await temporal_client.start_workflow(
            VaultFileDropWorkflow.run,
            VaultFileDropInput(
                bank_id=body.bank_id,
                vault_type=vault_type,
                minio_bucket=body.minio_bucket,
                minio_key=body.minio_key,
                file_hash=body.file_hash,
                feed_name=body.feed_name,
            ),
            id=workflow_id,
            task_queue=f"cts-processing-{body.bank_id}",
        )
        log.info("vault_file_drop.workflow_started",
                 bank_id=body.bank_id, vault_type=vault_type,
                 workflow_id=workflow_id, minio_key=body.minio_key)
        return FileDropWebhookResponse(
            workflow_id=workflow_id,
            bank_id=body.bank_id,
            vault_type=vault_type,
            status="ACCEPTED",
        )
    except WorkflowAlreadyStartedError:
        log.info("vault_file_drop.duplicate_skipped",
                 bank_id=body.bank_id, vault_type=vault_type, workflow_id=workflow_id)
        return FileDropWebhookResponse(
            workflow_id=workflow_id,
            bank_id=body.bank_id,
            vault_type=vault_type,
            status="DUPLICATE_SKIPPED",
        )
