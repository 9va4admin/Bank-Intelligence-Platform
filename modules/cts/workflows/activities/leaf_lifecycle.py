"""
Leaf lifecycle activities — ASTRA-automatic cheque leaf status writes.

These are Temporal activities called by ChequeProcessingWorkflow and ngch_filer.
They write to ChequeLeafVault (Redis + YugabyteDB) so that every clearing-time
event is reflected in the vault without any CBS call.

Activities:
  mark_leaf_presented    — called at start of ChequeProcessingWorkflow
  mark_leaf_paid         — called by file_to_ngch after CONFIRM is filed
  mark_leaf_returned     — called by file_to_ngch after RETURN is filed
  sweep_expired_leaves   — called by VaultSyncWorkflow daily sweep
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


class MarkLeafPresentedInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    account_number: str
    cheque_number: str
    instrument_id: str


class MarkLeafPaidInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    account_number: str
    cheque_number: str
    instrument_id: str


class MarkLeafReturnedInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    account_number: str
    cheque_number: str
    instrument_id: str
    return_reason_code: Optional[str] = None


class LeafLifecycleResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    success: bool
    skipped: bool = False
    reason: Optional[str] = None


@activity.defn
async def mark_leaf_presented(
    inp: MarkLeafPresentedInput,
    cheque_leaf_vault=None,
) -> LeafLifecycleResult:
    """
    Marks the cheque leaf as PRESENTED in the vault.

    Raises DuplicatePresentmentError (non-retryable) if the leaf is already
    PRESENTED or PAID — caller treats this as a duplicate presentment and
    files a return to NGCH immediately without running AI activities.

    Best-effort: if the vault is degraded (no DB pool), Redis-only write is
    still attempted so the clearing window is not blocked.
    """
    from modules.cts.vaults.cheque_leaf_vault import DuplicatePresentmentError

    try:
        await cheque_leaf_vault.mark_presented(
            account_number=inp.account_number,
            cheque_number=inp.cheque_number,
            instrument_id=inp.instrument_id,
        )
        log.info(
            "leaf_lifecycle.presented",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
        )
        return LeafLifecycleResult(success=True)

    except DuplicatePresentmentError as exc:
        log.warning(
            "leaf_lifecycle.duplicate_presentment",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        raise  # propagates as non-retryable to workflow

    except Exception as exc:
        # Degraded: vault write failed but clearing must not be blocked.
        # Log and continue — IET breach > vault miss in priority.
        log.warning(
            "leaf_lifecycle.presented_vault_error",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return LeafLifecycleResult(success=False, reason=str(exc))


@activity.defn
async def mark_leaf_paid(
    inp: MarkLeafPaidInput,
    cheque_leaf_vault,
) -> LeafLifecycleResult:
    """
    Marks the cheque leaf as PAID after ngch_filer confirms payment to NGCH.
    Terminal state — the leaf cannot be re-presented once PAID.
    """
    try:
        await cheque_leaf_vault.mark_paid(
            account_number=inp.account_number,
            cheque_number=inp.cheque_number,
            instrument_id=inp.instrument_id,
        )
        log.info(
            "leaf_lifecycle.paid",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
        )
        return LeafLifecycleResult(success=True)
    except Exception as exc:
        log.warning(
            "leaf_lifecycle.paid_vault_error",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return LeafLifecycleResult(success=False, reason=str(exc))


@activity.defn
async def mark_leaf_returned(
    inp: MarkLeafReturnedInput,
    cheque_leaf_vault,
) -> LeafLifecycleResult:
    """
    Marks the cheque leaf as RETURNED after ngch_filer files a return.
    The daily sweep resets RETURNED leaves back to ACTIVE after 24 h
    to allow the legal re-presentment window.
    """
    try:
        await cheque_leaf_vault.mark_returned(
            account_number=inp.account_number,
            cheque_number=inp.cheque_number,
            instrument_id=inp.instrument_id,
            return_reason_code=inp.return_reason_code,
        )
        log.info(
            "leaf_lifecycle.returned",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            return_reason_code=inp.return_reason_code,
            bank_id=inp.bank_id,
        )
        return LeafLifecycleResult(success=True)
    except Exception as exc:
        log.warning(
            "leaf_lifecycle.returned_vault_error",
            instrument_id=inp.instrument_id,
            cheque_number=inp.cheque_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return LeafLifecycleResult(success=False, reason=str(exc))


class ExpiredSweepInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    validity_months: int = 3   # RBI cheque validity window


class ExpiredSweepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    expired_count: int
    returned_reset_count: int


@activity.defn
async def sweep_expired_leaves(
    inp: ExpiredSweepInput,
    cheque_leaf_vault,
    db_pool,
) -> ExpiredSweepResult:
    """
    Daily sweep run by VaultSyncWorkflow.

    Two passes:
    1. ACTIVE leaves whose issued_date is older than validity_months → EXPIRED.
       These are also added to the bloom filter.
    2. RETURNED leaves older than 24 h → revert to ACTIVE (re-presentment window).
    """
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=inp.validity_months * 30)
    returned_cutoff = date.today() - timedelta(days=1)

    expired_count = 0
    returned_reset_count = 0

    if db_pool is None:
        log.warning("sweep_expired_leaves.no_db", bank_id=inp.bank_id)
        return ExpiredSweepResult(expired_count=0, returned_reset_count=0)

    async with db_pool.acquire() as conn:
        # Pass 1: expire ACTIVE leaves past validity
        rows_to_expire = await conn.fetch(
            """
            SELECT account_hash, account_number_last4, cheque_number
            FROM cts.cheque_leaves
            WHERE bank_id=$1 AND status='ACTIVE' AND issued_date < $2
            LIMIT 5000
            """,
            inp.bank_id, cutoff,
        )
        for row in rows_to_expire:
            try:
                # Mark in vault (writes DB + Redis)
                # We synthesise a pseudo account_number from last4 — vault uses hash internally
                _acct_proxy = "0000" + row["account_number_last4"]
                await cheque_leaf_vault.mark_expired(
                    account_number=row["account_number_last4"],
                    cheque_number=row["cheque_number"],
                )
                expired_count += 1
            except Exception as exc:
                log.warning(
                    "sweep_expired_leaves.expire_failed",
                    cheque_number=row["cheque_number"],
                    bank_id=inp.bank_id,
                    error=str(exc),
                )

        # Pass 2: reset RETURNED leaves older than 24 h back to ACTIVE
        rows_to_reset = await conn.fetch(
            """
            SELECT id, account_hash, account_number_last4, cheque_number
            FROM cts.cheque_leaves
            WHERE bank_id=$1 AND status='RETURNED' AND updated_at < $2
            LIMIT 5000
            """,
            inp.bank_id, returned_cutoff,
        )
        for row in rows_to_reset:
            try:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO cts.cheque_leaves_history
                          (leaf_id, bank_id, account_hash, cheque_number,
                           prev_status, new_status, change_action,
                           changed_by, changed_at)
                        VALUES ($1,$2,$3,$4,'RETURNED','ACTIVE','ASTRA_RETURN_RESET',
                                'astra:vault_sweep',now())
                        """,
                        row["id"], inp.bank_id, row["account_hash"], row["cheque_number"],
                    )
                    await conn.execute(
                        """
                        UPDATE cts.cheque_leaves
                        SET status='ACTIVE', updated_at=now()
                        WHERE id=$1
                        """,
                        row["id"],
                    )
                returned_reset_count += 1
            except Exception as exc:
                log.warning(
                    "sweep_expired_leaves.reset_failed",
                    cheque_number=row["cheque_number"],
                    bank_id=inp.bank_id,
                    error=str(exc),
                )

    log.info(
        "sweep_expired_leaves.done",
        bank_id=inp.bank_id,
        expired_count=expired_count,
        returned_reset_count=returned_reset_count,
    )
    return ExpiredSweepResult(
        expired_count=expired_count,
        returned_reset_count=returned_reset_count,
    )
