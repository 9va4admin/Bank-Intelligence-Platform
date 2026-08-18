"""
ChequeLeafVault — full lifecycle tracking for every issued cheque leaf.

Statuses and who writes them:
  ACTIVE       — ASTRA: auto-expanded from cheque_books when a book is uploaded
  STOPPED      — Bank upload / CBS push / UI: customer stop payment
  LOST         — Bank upload / CBS push / UI: customer reports loss
  STOLEN       — Bank upload / CBS push / UI: customer/police report
  CANCELLED    — Bank upload / CBS push / UI: customer cancels unused leaf
  PRESENTED    — ASTRA automatic: written by ChequeProcessingWorkflow on start
  PAID         — ASTRA automatic: written by ngch_filer on NGCH payment confirmation
  RETURNED     — ASTRA automatic: written by ngch_filer on NGCH return
  EXPIRED      — ASTRA automatic: daily VaultSyncWorkflow sweep (ACTIVE > 3 months)

Two storage tiers:
  Tier 1 (hot):     Redis Cluster — hgetall per leaf; sub-ms lookup in clearing window
                    Key: chq:{bank_id}:{hmac_sha256(pepper, bank_id:account_number)}:{cheque_number}
  Tier 2 (durable): YugabyteDB cts.cheque_leaves — source of truth; survives Redis restart

History: before EVERY status change, the current row is snapshotted atomically to
  cts.cheque_leaves_history with changed_by, changed_at, change_action, upload_batch_id.

Bloom filter: CANCELLED / LOST / STOLEN / STOPPED entries written to
  bloom:canceled:{bank_id} immediately on status change (via CanceledLeafBloom).

Vault miss / Redis error / DB error ALWAYS routes to HUMAN_REVIEW.
Raw account numbers NEVER appear in Redis keys, DB columns, or logs.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger()

# Statuses the bank / CBS feed can upload — ASTRA never lets bank set clearing statuses
_BANK_WRITABLE_STATUSES = frozenset({"STOPPED", "LOST", "STOLEN", "CANCELLED"})
# Terminal statuses — once set, cannot be changed (except STOPPED can be revoked via DEACTIVATE)
_TERMINAL_STATUSES = frozenset({"PAID", "EXPIRED", "LOST", "STOLEN", "CANCELLED"})
# Bloom filter candidates — immediately added on transition
_BLOOM_STATUSES = frozenset({"STOPPED", "LOST", "STOLEN", "CANCELLED", "EXPIRED"})


@dataclass(frozen=True)
class ChequeLeafVaultResult:
    outcome: str                    # "FOUND" | "NOT_FOUND" | "HUMAN_REVIEW"
    status: Optional[str] = None    # leaf status when FOUND
    issued_date: Optional[str] = None
    degraded: bool = False          # True when result is due to infra error


class ChequeLeafVault:
    def __init__(self, bank_id: str, pepper: str, db_pool=None,
                 bloom_filter=None) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._db_pool = db_pool
        self._bloom = bloom_filter  # CanceledLeafBloom instance, optional
        self._redis = None
        self._ready = False

    def connect(self, redis_client=None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis  # type: ignore[import]
            self._redis = redis.Redis()
        self._ready = True

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "ChequeLeafVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _account_hash(self, account_number: str) -> str:
        return hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _make_key(self, account_number: str, cheque_number: str) -> str:
        return f"chq:{self._bank_id}:{self._account_hash(account_number)}:{cheque_number}"

    # ------------------------------------------------------------------
    # Primary read path
    # ------------------------------------------------------------------

    async def lookup(self, account_number: str, cheque_number: str) -> ChequeLeafVaultResult:
        """
        Priority: Redis → YugabyteDB → HUMAN_REVIEW on miss.
        Callers use the returned status to gate whether a cheque may be presented.
        """
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)

        # 1. Redis
        try:
            raw = self._redis.hgetall(key)
        except Exception as exc:
            log.warning(
                "cheque_leaf_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=self._bank_id,
                error=str(exc),
            )
            return ChequeLeafVaultResult(outcome="HUMAN_REVIEW", degraded=True)

        if raw:
            entry = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in raw.items()
            }
            return ChequeLeafVaultResult(
                outcome="FOUND",
                status=entry.get("status", "UNKNOWN"),
                issued_date=entry.get("issued_date"),
            )

        # 2. YugabyteDB
        if self._db_pool is not None:
            try:
                row = await self._load_from_db(
                    self._account_hash(account_number), cheque_number
                )
            except Exception as exc:
                log.warning(
                    "cheque_leaf_vault.db_error",
                    account_last4=account_number[-4:],
                    bank_id=self._bank_id,
                    error=str(exc),
                )
                return ChequeLeafVaultResult(outcome="HUMAN_REVIEW", degraded=True)

            if row:
                self._backfill_redis(key, row)
                return ChequeLeafVaultResult(
                    outcome="FOUND",
                    status=row["status"],
                    issued_date=str(row["issued_date"]) if row.get("issued_date") else None,
                )

        log.info(
            "cheque_leaf_vault.miss",
            account_last4=account_number[-4:],
            cheque_number=cheque_number,
            bank_id=self._bank_id,
        )
        return ChequeLeafVaultResult(outcome="NOT_FOUND")

    # ------------------------------------------------------------------
    # ASTRA-automatic status writes (called by workflow activities)
    # ------------------------------------------------------------------

    async def mark_presented(
        self,
        account_number: str,
        cheque_number: str,
        instrument_id: str,
    ) -> None:
        """
        Written by ChequeProcessingWorkflow when inward processing starts.
        Detects duplicate presentment: raises DuplicatePresentmentError if leaf is
        already PRESENTED or PAID (both terminal from re-presentment perspective).
        """
        await self._astra_transition(
            account_number=account_number,
            cheque_number=cheque_number,
            new_status="PRESENTED",
            change_action="ASTRA_PRESENTED",
            changed_by="astra:workflow",
            instrument_id=instrument_id,
            disallow_from=frozenset({"PRESENTED", "PAID"}),
            raise_on_disallow=True,
        )

    async def mark_paid(
        self,
        account_number: str,
        cheque_number: str,
        instrument_id: str,
    ) -> None:
        """Written by ngch_filer after NGCH confirms payment. Terminal."""
        await self._astra_transition(
            account_number=account_number,
            cheque_number=cheque_number,
            new_status="PAID",
            change_action="ASTRA_PAID",
            changed_by="astra:ngch_filer",
            instrument_id=instrument_id,
            disallow_from=frozenset({"PAID"}),
        )

    async def mark_returned(
        self,
        account_number: str,
        cheque_number: str,
        instrument_id: str,
        return_reason_code: Optional[str] = None,
    ) -> None:
        """
        Written by ngch_filer after NGCH return. Leaf reverts to ACTIVE after 24 h
        (the re-presentment window); that reversion is handled by the daily sweep.
        For the vault we just write RETURNED — re-activation is a separate sweep.
        """
        await self._astra_transition(
            account_number=account_number,
            cheque_number=cheque_number,
            new_status="RETURNED",
            change_action="ASTRA_RETURNED",
            changed_by="astra:ngch_filer",
            instrument_id=instrument_id,
            return_reason_code=return_reason_code,
        )

    async def mark_expired(
        self,
        account_number: str,
        cheque_number: str,
    ) -> None:
        """Written by daily VaultSyncWorkflow sweep for ACTIVE leaves > 3 months old."""
        await self._astra_transition(
            account_number=account_number,
            cheque_number=cheque_number,
            new_status="EXPIRED",
            change_action="ASTRA_EXPIRED",
            changed_by="astra:vault_sweep",
            disallow_from=frozenset({"PAID", "RETURNED", "EXPIRED"}),
        )
        if self._bloom is not None:
            try:
                await self._bloom.add(account_number, cheque_number)
            except Exception as exc:
                log.warning("cheque_leaf_vault.bloom_add_failed",
                            cheque_number=cheque_number, error=str(exc))

    # ------------------------------------------------------------------
    # Bank-upload write paths (called by VaultUploadProcessor)
    # ------------------------------------------------------------------

    async def store_book(
        self,
        account_number: str,
        series_start: str,
        series_end: str,
        issued_date: date,
        branch_code: Optional[str],
        cbs_book_ref: Optional[str],
        action: str,
        changed_by: str,
        upload_batch_id: Optional[str] = None,
    ) -> int:
        """
        Register a cheque book and auto-expand every leaf in the series to ACTIVE.
        Returns the count of leaves created/updated.

        action: INSERT_ONLY | UPSERT | UPDATE_ONLY | DEACTIVATE
        DEACTIVATE: marks the book is_active=False and sets all ACTIVE leaves to CANCELLED.
        """
        self._assert_ready()
        account_hash = self._account_hash(account_number)
        acct_last4 = account_number[-4:]

        if self._db_pool is None:
            log.warning("cheque_leaf_vault.store_book_no_db", bank_id=self._bank_id)
            return 0

        async with self._db_pool.acquire() as conn:
            async with conn.transaction():
                # Snapshot history for existing book record before any change
                existing_book = await conn.fetchrow(
                    """
                    SELECT id, is_active, series_start, series_end, issued_date, branch_code
                    FROM cts.cheque_books
                    WHERE bank_id=$1 AND account_hash=$2 AND series_start=$3
                    """,
                    self._bank_id, account_hash, series_start,
                )
                if existing_book and action in ("UPDATE_ONLY", "UPSERT", "DEACTIVATE"):
                    await conn.execute(
                        """
                        INSERT INTO cts.cheque_books_history
                          (book_id, bank_id, account_hash, series_start, series_end,
                           issued_date, branch_code, cbs_book_ref, is_active,
                           change_action, changed_by, changed_at, upload_batch_id)
                        SELECT id, bank_id, account_hash, series_start, series_end,
                               issued_date, branch_code, cbs_book_ref, is_active,
                               $4, $5, now(), $6
                        FROM cts.cheque_books
                        WHERE bank_id=$1 AND account_hash=$2 AND series_start=$3
                        """,
                        self._bank_id, account_hash, series_start,
                        action, changed_by,
                        upload_batch_id,
                    )

                is_active = action != "DEACTIVATE"
                if action == "INSERT_ONLY" and existing_book:
                    log.info("cheque_leaf_vault.book_insert_skip_existing",
                             series_start=series_start, bank_id=self._bank_id)
                    return 0

                book_id_row = await conn.fetchrow(
                    """
                    INSERT INTO cts.cheque_books
                      (bank_id, account_hash, account_number_last4, series_start,
                       series_end, issued_date, branch_code, cbs_book_ref,
                       is_active, upload_batch_id, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,now(),now())
                    ON CONFLICT (bank_id, account_hash, series_start)
                    DO UPDATE SET
                        series_end       = EXCLUDED.series_end,
                        issued_date      = EXCLUDED.issued_date,
                        branch_code      = EXCLUDED.branch_code,
                        cbs_book_ref     = EXCLUDED.cbs_book_ref,
                        is_active        = EXCLUDED.is_active,
                        upload_batch_id  = EXCLUDED.upload_batch_id,
                        updated_at       = now()
                    RETURNING id
                    """,
                    self._bank_id, account_hash, acct_last4,
                    series_start, series_end, issued_date,
                    branch_code, cbs_book_ref, is_active,
                    upload_batch_id,
                )
                book_id = book_id_row["id"]

                if action == "DEACTIVATE":
                    # Mark all still-ACTIVE leaves in this book as CANCELLED
                    return await self._bulk_cancel_book_leaves(
                        conn, account_hash, series_start, series_end,
                        changed_by, upload_batch_id, book_id
                    )

                # Expand series → individual ACTIVE leaves
                start_n = int(series_start)
                end_n = int(series_end)
                count = 0
                for leaf_num in range(start_n, end_n + 1):
                    cheque_number = str(leaf_num).zfill(len(series_start))
                    await self._upsert_leaf(
                        conn, account_hash, acct_last4, cheque_number,
                        "ACTIVE", issued_date, book_id, series_start,
                        changed_by, upload_batch_id, action,
                    )
                    count += 1

        # Warm Redis for the first and last leaf of the book
        for leaf_num in [start_n, end_n]:
            cheque_number = str(leaf_num).zfill(len(series_start))
            key = self._make_key(account_number, cheque_number)
            self._redis_set(key, "ACTIVE", str(issued_date))

        log.info(
            "cheque_leaf_vault.book_stored",
            bank_id=self._bank_id,
            account_last4=acct_last4,
            series_start=series_start,
            series_end=series_end,
            action=action,
            leaves_count=count,
        )
        return count

    async def set_leaf_status(
        self,
        account_number: str,
        cheque_number: str,
        new_status: str,
        action: str,
        changed_by: str,
        reason: Optional[str] = None,
        reported_by: Optional[str] = None,
        effective_date: Optional[date] = None,
        upload_batch_id: Optional[str] = None,
    ) -> bool:
        """
        Bank-upload method for exception statuses: STOPPED/LOST/STOLEN/CANCELLED.
        action=DEACTIVATE on a STOPPED leaf revokes the stop (reverts to ACTIVE).
        Returns True if the leaf was updated, False if skipped (e.g. INSERT_ONLY on existing).
        """
        self._assert_ready()
        if new_status not in _BANK_WRITABLE_STATUSES and action != "DEACTIVATE":
            raise ValueError(
                f"Bank may not write status {new_status!r}. "
                f"Allowed: {sorted(_BANK_WRITABLE_STATUSES)}"
            )

        account_hash = self._account_hash(account_number)

        if self._db_pool is None:
            log.warning("cheque_leaf_vault.set_leaf_status_no_db", bank_id=self._bank_id)
            return False

        async with self._db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, status FROM cts.cheque_leaves
                    WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                    """,
                    self._bank_id, account_hash, cheque_number,
                )
                if not row:
                    log.warning(
                        "cheque_leaf_vault.set_leaf_status_leaf_not_found",
                        account_last4=account_number[-4:],
                        cheque_number=cheque_number,
                        bank_id=self._bank_id,
                    )
                    return False

                prev_status = row["status"]
                leaf_id = row["id"]

                if action == "INSERT_ONLY" and prev_status != "ACTIVE":
                    return False  # leaf already has a non-default status

                if prev_status in _TERMINAL_STATUSES and action != "DEACTIVATE":
                    log.warning(
                        "cheque_leaf_vault.terminal_status_change_blocked",
                        prev_status=prev_status,
                        cheque_number=cheque_number,
                        bank_id=self._bank_id,
                    )
                    return False

                resolved_status = "ACTIVE" if action == "DEACTIVATE" else new_status

                # Snapshot history before changing
                await conn.execute(
                    """
                    INSERT INTO cts.cheque_leaves_history
                      (leaf_id, bank_id, account_hash, cheque_number,
                       prev_status, new_status, change_action,
                       changed_by, changed_at, upload_batch_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,now(),$9)
                    """,
                    leaf_id, self._bank_id, account_hash, cheque_number,
                    prev_status, resolved_status, action,
                    changed_by, upload_batch_id,
                )

                await conn.execute(
                    """
                    UPDATE cts.cheque_leaves
                    SET status=$3, exception_reason=$4, reported_by=$5,
                        effective_date=$6, upload_batch_id=$7, updated_at=now()
                    WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$8
                    """,
                    self._bank_id, account_hash,
                    resolved_status, reason, reported_by,
                    effective_date, upload_batch_id, cheque_number,
                )

        # Update Redis
        key = self._make_key(account_number, cheque_number)
        try:
            self._redis.hset(key, mapping={"status": resolved_status})
        except Exception as exc:
            log.warning("cheque_leaf_vault.redis_update_failed",
                        cheque_number=cheque_number, error=str(exc))

        # Bloom filter for exception statuses
        if resolved_status in _BLOOM_STATUSES and self._bloom is not None:
            try:
                await self._bloom.add(account_number, cheque_number)
            except Exception as exc:
                log.warning("cheque_leaf_vault.bloom_add_failed",
                            cheque_number=cheque_number, error=str(exc))
        elif action == "DEACTIVATE" and self._bloom is not None:
            # Revoking a stop: remove from bloom if bloom supports deletion
            # RedisBloom BF does not support deletion — log only
            log.info("cheque_leaf_vault.stop_revoked_bloom_note",
                     cheque_number=cheque_number,
                     note="Bloom filter does not support deletion; leaf stays in filter "
                          "but vault status is ACTIVE — vault check wins over bloom for STOPPED")

        log.info(
            "cheque_leaf_vault.leaf_status_set",
            account_last4=account_number[-4:],
            cheque_number=cheque_number,
            prev_status=prev_status,
            new_status=resolved_status,
            action=action,
            bank_id=self._bank_id,
        )
        return True

    # ------------------------------------------------------------------
    # Backward-compatible store() used by VaultSyncWorkflow seed path
    # ------------------------------------------------------------------

    async def store(
        self,
        account_number: str,
        cheque_number: str,
        status: str,
        issued_date: Optional[str] = None,
        series_end: Optional[str] = None,
    ) -> None:
        """Legacy single-leaf write used by VaultSyncWorkflow. Writes Redis only."""
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)
        mapping: dict[str, str] = {"status": status}
        if issued_date:
            mapping["issued_date"] = issued_date
        if series_end:
            mapping["series_end"] = series_end
        self._redis.hset(key, mapping=mapping)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_from_db(self, account_hash: str, cheque_number: str):
        async with self._db_pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT status, issued_date
                FROM cts.cheque_leaves
                WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                """,
                self._bank_id, account_hash, cheque_number,
            )

    def _backfill_redis(self, key: str, row) -> None:
        try:
            mapping = {"status": row["status"]}
            if row.get("issued_date"):
                mapping["issued_date"] = str(row["issued_date"])
            self._redis.hset(key, mapping=mapping)
        except Exception as exc:
            log.warning("cheque_leaf_vault.redis_backfill_failed",
                        key=key[:50], error=str(exc))

    def _redis_set(self, key: str, status: str, issued_date: Optional[str] = None) -> None:
        try:
            mapping: dict[str, str] = {"status": status}
            if issued_date:
                mapping["issued_date"] = issued_date
            self._redis.hset(key, mapping=mapping)
        except Exception as exc:
            log.warning("cheque_leaf_vault.redis_set_failed",
                        key=key[:50], error=str(exc))

    async def _astra_transition(
        self,
        account_number: str,
        cheque_number: str,
        new_status: str,
        change_action: str,
        changed_by: str,
        disallow_from: frozenset = frozenset(),
        raise_on_disallow: bool = False,
        instrument_id: Optional[str] = None,
        return_reason_code: Optional[str] = None,
    ) -> None:
        """Atomic status transition with history snapshot. For ASTRA-automatic writes."""
        self._assert_ready()
        account_hash = self._account_hash(account_number)

        if self._db_pool is None:
            # Degrade gracefully: update Redis only (lost on restart but IET unblocked)
            key = self._make_key(account_number, cheque_number)
            self._redis_set(key, new_status)
            return

        async with self._db_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, status FROM cts.cheque_leaves
                    WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                    FOR UPDATE
                    """,
                    self._bank_id, account_hash, cheque_number,
                )

                if row is None:
                    # Leaf not seeded yet — create it now (CBS miss at book upload time)
                    await conn.execute(
                        """
                        INSERT INTO cts.cheque_leaves
                          (bank_id, account_hash, account_number_last4, cheque_number,
                           status, instrument_id, created_at, updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,now(),now())
                        ON CONFLICT (bank_id, account_hash, cheque_number) DO NOTHING
                        """,
                        self._bank_id, account_hash, account_number[-4:],
                        cheque_number, new_status, instrument_id,
                    )
                    key = self._make_key(account_number, cheque_number)
                    self._redis_set(key, new_status)
                    return

                prev_status = row["status"]
                leaf_id = row["id"]

                if prev_status in disallow_from:
                    if raise_on_disallow:
                        raise DuplicatePresentmentError(
                            f"Cheque {cheque_number} is already {prev_status} — "
                            "duplicate presentment detected."
                        )
                    log.warning(
                        "cheque_leaf_vault.astra_transition_blocked",
                        cheque_number=cheque_number,
                        prev_status=prev_status,
                        new_status=new_status,
                        bank_id=self._bank_id,
                    )
                    return

                await conn.execute(
                    """
                    INSERT INTO cts.cheque_leaves_history
                      (leaf_id, bank_id, account_hash, cheque_number,
                       prev_status, new_status, change_action,
                       changed_by, changed_at, instrument_id, return_reason_code)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,now(),$9,$10)
                    """,
                    leaf_id, self._bank_id, account_hash, cheque_number,
                    prev_status, new_status, change_action,
                    changed_by, instrument_id, return_reason_code,
                )
                await conn.execute(
                    """
                    UPDATE cts.cheque_leaves
                    SET status=$3, instrument_id=COALESCE($4, instrument_id),
                        return_reason_code=COALESCE($5, return_reason_code),
                        updated_at=now()
                    WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$6
                    """,
                    self._bank_id, account_hash,
                    new_status, instrument_id, return_reason_code, cheque_number,
                )

        key = self._make_key(account_number, cheque_number)
        self._redis_set(key, new_status)
        log.info(
            "cheque_leaf_vault.astra_transition",
            cheque_number=cheque_number,
            prev_status=prev_status,
            new_status=new_status,
            change_action=change_action,
            bank_id=self._bank_id,
        )

    async def _upsert_leaf(
        self,
        conn,
        account_hash: str,
        acct_last4: str,
        cheque_number: str,
        status: str,
        issued_date,
        book_id,
        series_start: str,
        changed_by: str,
        upload_batch_id,
        action: str,
    ) -> None:
        existing = await conn.fetchrow(
            """
            SELECT id, status FROM cts.cheque_leaves
            WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
            """,
            self._bank_id, account_hash, cheque_number,
        )
        if existing and action == "INSERT_ONLY":
            return  # skip without error

        if existing and action in ("UPDATE_ONLY", "UPSERT"):
            await conn.execute(
                """
                INSERT INTO cts.cheque_leaves_history
                  (leaf_id, bank_id, account_hash, cheque_number,
                   prev_status, new_status, change_action,
                   changed_by, changed_at, upload_batch_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,now(),$9)
                """,
                existing["id"], self._bank_id, account_hash, cheque_number,
                existing["status"], status, action,
                changed_by, upload_batch_id,
            )

        await conn.execute(
            """
            INSERT INTO cts.cheque_leaves
              (bank_id, account_hash, account_number_last4, cheque_number,
               status, issued_date, book_id, series_start,
               upload_batch_id, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now(),now())
            ON CONFLICT (bank_id, account_hash, cheque_number)
            DO UPDATE SET
                status          = CASE
                                    WHEN cts.cheque_leaves.status IN
                                         ('PRESENTED','PAID','RETURNED')
                                    THEN cts.cheque_leaves.status  -- protect clearing statuses
                                    ELSE EXCLUDED.status
                                  END,
                issued_date     = EXCLUDED.issued_date,
                book_id         = EXCLUDED.book_id,
                upload_batch_id = EXCLUDED.upload_batch_id,
                updated_at      = now()
            """,
            self._bank_id, account_hash, acct_last4, cheque_number,
            status, issued_date, book_id, series_start,
            upload_batch_id,
        )

    async def _bulk_cancel_book_leaves(
        self,
        conn,
        account_hash: str,
        series_start: str,
        series_end: str,
        changed_by: str,
        upload_batch_id,
        book_id,
    ) -> int:
        start_n = int(series_start)
        end_n = int(series_end)
        cheque_numbers = [str(n).zfill(len(series_start)) for n in range(start_n, end_n + 1)]

        # Snapshot history for all ACTIVE leaves in this book
        await conn.execute(
            """
            INSERT INTO cts.cheque_leaves_history
              (leaf_id, bank_id, account_hash, cheque_number,
               prev_status, new_status, change_action,
               changed_by, changed_at, upload_batch_id)
            SELECT id, bank_id, account_hash, cheque_number,
                   status, 'CANCELLED', 'DEACTIVATE',
                   $3, now(), $4
            FROM cts.cheque_leaves
            WHERE bank_id=$1 AND account_hash=$2
              AND cheque_number = ANY($5)
              AND status = 'ACTIVE'
            """,
            self._bank_id, account_hash, changed_by, upload_batch_id, cheque_numbers,
        )
        result = await conn.execute(
            """
            UPDATE cts.cheque_leaves
            SET status='CANCELLED', updated_at=now(), upload_batch_id=$4
            WHERE bank_id=$1 AND account_hash=$2
              AND cheque_number = ANY($3)
              AND status = 'ACTIVE'
            """,
            self._bank_id, account_hash, cheque_numbers, upload_batch_id,
        )
        # result is like "UPDATE 42"
        count = int(result.split()[-1]) if result else 0
        return count

    def _pipeline_store(self, pipe, account_number, cheque_number, status,
                        issued_date=None, series_end=None):
        """Legacy pipeline method kept for VaultSyncWorkflow compat."""
        key = self._make_key(account_number, cheque_number)
        mapping: dict[str, str] = {"status": status}
        if issued_date:
            mapping["issued_date"] = issued_date
        if series_end:
            mapping["series_end"] = series_end
        pipe.hset(key, mapping=mapping)


class DuplicatePresentmentError(Exception):
    """Raised when a cheque leaf is presented that is already PRESENTED or PAID."""
