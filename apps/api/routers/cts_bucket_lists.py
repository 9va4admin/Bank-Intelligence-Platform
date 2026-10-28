"""
Admin configuration: bank-maintained account lists for the CA (corporate) and IP (institution) review buckets.

An account on a list is put in that bucket whatever its CBS account type says. Accounts are stored as keyed hashes plus the
last four digits (never the number); listings, responses and audit events show only the last four. Roles: ops_manager and
bank_it_admin.

  GET    /v1/cts/admin/bucket-accounts/{CA|IP}?limit=&cursor=   list (hash, last4, who added, when) with a total
  POST   /v1/cts/admin/bucket-accounts/{CA|IP}                  add up to 5,000 account numbers
  DELETE /v1/cts/admin/bucket-accounts/{CA|IP}/{account_hash}   remove one
"""
from __future__ import annotations

import re
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routers.cts_deps import get_current_user_context
from apps.api.schemas.types import IsoTimestamp
from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.auth.rbac import UserContext
from shared.config.config_service import config_service
from shared.utils.pii_crypto import hash_account_number

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS bucket account lists v1"])

LIST_BUCKETS = ("CA", "IP")
_MAX_PER_CALL = 5000
_ACCOUNT = re.compile(r"^[A-Za-z0-9]{6,25}$")
_ADMIN_ROLES = ("ops_manager", "bank_it_admin")

SQL_INSERT = ("INSERT INTO cts.bucket_account_lists (bank_id, bucket, account_hash, account_last4, added_by) "
              "VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING")
SQL_DELETE = "DELETE FROM cts.bucket_account_lists WHERE bank_id = $1 AND bucket = $2 AND account_hash = $3"
SQL_COUNT = "SELECT count(*) FROM cts.bucket_account_lists WHERE bank_id = $1 AND bucket = $2"
SQL_LIST = ("SELECT account_hash, account_last4, added_by, added_at::text AS added_at FROM cts.bucket_account_lists "
            "WHERE bank_id = $1 AND bucket = $2 AND account_hash > $3 ORDER BY account_hash LIMIT $4")


class AddAccountsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_numbers: list[str] = Field(min_length=1, max_length=_MAX_PER_CALL)


class AddAccountsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bucket: str
    added: int
    already_present: int
    invalid: list[str]            # last four characters of each rejected entry (never the entry)


class ListedAccount(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_hash: str
    account_last4: str
    added_by: str
    added_at: IsoTimestamp


class ListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bucket: str
    total: int
    items: list[ListedAccount]
    next_cursor: Optional[str] = None


class RemoveResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bucket: str
    removed: bool


def _check(ctx: UserContext, bucket: str) -> None:
    if ctx.role.value not in _ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if bucket not in LIST_BUCKETS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Only {list(LIST_BUCKETS)} have account lists")


def _db(request: Request):
    db = getattr(request.app.state, "db_pool_cts", None)
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    return db


async def _audit(request: Request, ctx: UserContext, payload: dict) -> None:
    writer = getattr(request.app.state, "audit_stream_writer", None)
    if writer is not None:
        await writer(AuditEvent(event_type=AuditEventType.CTS_ALLOC_CLAIMED, bank_id=ctx.bank_id, user_id=ctx.user_id,
                                payload={**payload, "changed_by": ctx.user_id}))


@router_v1.get("/admin/bucket-accounts/{bucket}", response_model=ListResponse, status_code=status.HTTP_200_OK)
async def list_bucket_accounts(
    bucket: str, request: Request, limit: int = Query(50, ge=1, le=100), cursor: str = "",
    ctx: UserContext = Depends(get_current_user_context),
) -> ListResponse:
    _check(ctx, bucket)
    async with _db(request).acquire() as conn:
        total = int(await conn.fetchval(SQL_COUNT, ctx.bank_id, bucket))
        rows = await conn.fetch(SQL_LIST, ctx.bank_id, bucket, cursor, limit + 1)
    page = rows[:limit]
    return ListResponse(
        bucket=bucket, total=total,
        items=[ListedAccount(account_hash=r["account_hash"], account_last4=r["account_last4"],
                             added_by=r["added_by"], added_at=str(r["added_at"])) for r in page],
        next_cursor=page[-1]["account_hash"] if len(rows) > limit else None,
    )


@router_v1.post("/admin/bucket-accounts/{bucket}", response_model=AddAccountsResponse, status_code=status.HTTP_200_OK)
async def add_bucket_accounts(
    bucket: str, body: AddAccountsRequest, request: Request, ctx: UserContext = Depends(get_current_user_context),
) -> AddAccountsResponse:
    _check(ctx, bucket)
    try:
        pepper = await config_service.get_secret("pii_hash_pepper")
    except Exception as exc:  # noqa: BLE001 - without the secret nothing may be stored
        log.error("bucket_lists.pepper_unavailable", error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Hashing secret unavailable") from exc

    added = already = 0
    invalid: list[str] = []
    async with _db(request).acquire() as conn:
        async with conn.transaction():
            for raw in body.account_numbers:
                number = raw.strip()
                if not _ACCOUNT.match(number):
                    invalid.append(number[-4:] if number else "")
                    continue
                status_text = await conn.execute(
                    SQL_INSERT, ctx.bank_id, bucket, hash_account_number(number, ctx.bank_id, pepper), number[-4:], ctx.user_id)
                if status_text.endswith(" 1"):
                    added += 1
                else:
                    already += 1
    await _audit(request, ctx, {"action": "BUCKET_ACCOUNTS_ADDED", "bucket": bucket, "added": added,
                                "already_present": already, "invalid": len(invalid)})
    log.info("cts.bucket_accounts.added", bank_id=ctx.bank_id, bucket=bucket, added=added, already=already,
             invalid=len(invalid), admin_id=ctx.user_id)
    return AddAccountsResponse(bucket=bucket, added=added, already_present=already, invalid=invalid)


@router_v1.delete("/admin/bucket-accounts/{bucket}/{account_hash}", response_model=RemoveResponse,
                  status_code=status.HTTP_200_OK)
async def remove_bucket_account(
    bucket: str, account_hash: str, request: Request, ctx: UserContext = Depends(get_current_user_context),
) -> RemoveResponse:
    _check(ctx, bucket)
    async with _db(request).acquire() as conn:
        result = await conn.execute(SQL_DELETE, ctx.bank_id, bucket, account_hash)
    if not result.endswith(" 1"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account is not on this list")
    await _audit(request, ctx, {"action": "BUCKET_ACCOUNTS_REMOVED", "bucket": bucket, "removed": 1})
    return RemoveResponse(bucket=bucket, removed=True)
