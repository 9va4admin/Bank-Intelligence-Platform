"""
VaultUploadProcessor — processes CSV/file uploads for all CTS vault types.

Supports two ingestion channels:
  - UI (post-login): changed_by = "user:{user_id}"
  - SFTP system push: changed_by = "system:{feed_name}"

Action column values (universal across all vault types):
  UPSERT       — insert if missing; update if existing (default)
  INSERT_ONLY  — insert only; silently skip if record already exists
  UPDATE_ONLY  — update only; silently skip if record does not exist
  DEACTIVATE   — mark record inactive / revoke status

Vault types handled:
  CHEQUE_BOOK    — cheque_book_upload.csv     → ChequeLeafVault.store_book()
  LEAF_STATUS    — cheque_leaf_status_upload.csv → ChequeLeafVault.set_leaf_status()
  ACCOUNT_DETAIL — account_vault_detail_upload.csv → AccountVaultDetailWriter
  SIGNATURE      — signatory_upload.csv       → SignatureVault account_signatories

All uploads:
  1. Create a vault_upload_batches row (status=PROCESSING)
  2. For each CSV row: validate, route to vault handler, capture errors
  3. Update batch row (status=COMPLETE|PARTIAL|FAILED, counts)
  4. Write one Immudb audit event per batch (not per row — batch is the atomic unit)
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_VALID_ACTIONS = frozenset({"UPSERT", "INSERT_ONLY", "UPDATE_ONLY", "DEACTIVATE"})
_DEFAULT_ACTION = "UPSERT"

# CSV column definitions: {vault_type: [required_cols, optional_cols]}
_COLUMNS: dict[str, dict[str, list[str]]] = {
    "CHEQUE_BOOK": {
        "required": ["account_number", "series_start", "series_end", "issued_date"],
        "optional": ["action", "branch_code", "cbs_book_ref"],
    },
    "LEAF_STATUS": {
        "required": ["account_number", "cheque_number", "new_status"],
        "optional": ["action", "reason", "reported_by", "effective_date"],
    },
    "ACCOUNT_DETAIL": {
        "required": ["account_number", "holder_seq", "holder_name", "role"],
        "optional": ["action", "pan_last4"],
    },
    "SIGNATURE": {
        "required": ["account_number", "signatory_id", "mandate_rule"],
        "optional": ["action", "quorum_n"],
    },
}


class VaultUploadResult:
    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.rows_total = 0
        self.rows_processed = 0
        self.rows_failed = 0
        self.errors: list[dict] = []


class VaultUploadProcessor:
    def __init__(
        self,
        bank_id: str,
        db_pool,
        cheque_leaf_vault=None,
        account_vault=None,
        signature_vault=None,
    ) -> None:
        self._bank_id = bank_id
        self._db_pool = db_pool
        self._cheque_leaf_vault = cheque_leaf_vault
        self._account_vault = account_vault
        self._signature_vault = signature_vault

    async def process(
        self,
        vault_type: str,
        csv_content: bytes,
        changed_by: str,
        filename: Optional[str] = None,
        upload_channel: str = "UI",
    ) -> VaultUploadResult:
        """
        Entry point. Parses the CSV and dispatches each row to the appropriate handler.
        Returns a VaultUploadResult with counts and errors.
        """
        if vault_type not in _COLUMNS:
            raise ValueError(
                f"Unknown vault_type {vault_type!r}. "
                f"Supported: {sorted(_COLUMNS)}"
            )

        batch_id = str(uuid.uuid4())
        result = VaultUploadResult(batch_id)

        # Parse CSV
        try:
            reader = csv.DictReader(io.StringIO(csv_content.decode("utf-8")))
            rows = list(reader)
        except Exception as exc:
            raise ValueError(f"CSV parse error: {exc}") from exc

        result.rows_total = len(rows)

        # Create batch row in PROCESSING state
        await self._create_batch(
            batch_id, vault_type, filename, upload_channel, changed_by, len(rows)
        )

        # Validate columns
        col_spec = _COLUMNS[vault_type]
        required = set(col_spec["required"])
        if rows:
            header = set(rows[0].keys())
            missing = required - header
            if missing:
                await self._fail_batch(batch_id, f"Missing required columns: {missing}")
                raise ValueError(f"CSV missing required columns for {vault_type}: {missing}")

        # Dispatch rows
        handler = self._get_handler(vault_type)
        for idx, row in enumerate(rows, start=2):  # row 1 is header
            # Normalize empty strings → None
            clean = {k: (v.strip() or None) for k, v in row.items()}
            action = (clean.get("action") or _DEFAULT_ACTION).upper()

            if action not in _VALID_ACTIONS:
                result.rows_failed += 1
                result.errors.append({
                    "row": idx,
                    "error": f"Invalid action {action!r}. Must be one of {sorted(_VALID_ACTIONS)}.",
                })
                continue

            try:
                await handler(clean, action, changed_by, batch_id)
                result.rows_processed += 1
            except Exception as exc:
                result.rows_failed += 1
                result.errors.append({"row": idx, "error": str(exc)})
                log.warning(
                    "vault_upload_processor.row_failed",
                    bank_id=self._bank_id,
                    vault_type=vault_type,
                    row=idx,
                    action=action,
                    error=str(exc),
                )

        # Finalize batch
        final_status = (
            "FAILED" if result.rows_processed == 0
            else "PARTIAL" if result.rows_failed > 0
            else "COMPLETE"
        )
        await self._complete_batch(batch_id, final_status, result)
        return result

    # ------------------------------------------------------------------
    # Row handlers per vault type
    # ------------------------------------------------------------------

    def _get_handler(self, vault_type: str):
        return {
            "CHEQUE_BOOK": self._handle_cheque_book_row,
            "LEAF_STATUS": self._handle_leaf_status_row,
            "ACCOUNT_DETAIL": self._handle_account_detail_row,
            "SIGNATURE": self._handle_signature_row,
        }[vault_type]

    async def _handle_cheque_book_row(
        self, row: dict, action: str, changed_by: str, batch_id: str
    ) -> None:
        acct = _require(row, "account_number")
        series_start = _require(row, "series_start").zfill(6)
        series_end = _require(row, "series_end").zfill(6)
        issued_date_raw = _require(row, "issued_date")
        issued_date = date.fromisoformat(issued_date_raw)

        if int(series_start) > int(series_end):
            raise ValueError(
                f"series_start ({series_start}) must be ≤ series_end ({series_end})"
            )

        if self._cheque_leaf_vault is None:
            raise RuntimeError("ChequeLeafVault not configured in processor")

        await self._cheque_leaf_vault.store_book(
            account_number=acct,
            series_start=series_start,
            series_end=series_end,
            issued_date=issued_date,
            branch_code=row.get("branch_code"),
            cbs_book_ref=row.get("cbs_book_ref"),
            action=action,
            changed_by=changed_by,
            upload_batch_id=batch_id,
        )

    async def _handle_leaf_status_row(
        self, row: dict, action: str, changed_by: str, batch_id: str
    ) -> None:
        acct = _require(row, "account_number")
        cheque_number = _require(row, "cheque_number").zfill(6)
        new_status = _require(row, "new_status").upper() if action != "DEACTIVATE" else "STOPPED"

        effective_date_raw = row.get("effective_date")
        effective_date = date.fromisoformat(effective_date_raw) if effective_date_raw else None

        if self._cheque_leaf_vault is None:
            raise RuntimeError("ChequeLeafVault not configured in processor")

        ok = await self._cheque_leaf_vault.set_leaf_status(
            account_number=acct,
            cheque_number=cheque_number,
            new_status=new_status,
            action=action,
            changed_by=changed_by,
            reason=row.get("reason"),
            reported_by=row.get("reported_by"),
            effective_date=effective_date,
            upload_batch_id=batch_id,
        )
        if not ok:
            log.info(
                "vault_upload_processor.leaf_status_skipped",
                cheque_number=cheque_number,
                action=action,
                bank_id=self._bank_id,
            )

    async def _handle_account_detail_row(
        self, row: dict, action: str, changed_by: str, batch_id: str
    ) -> None:
        """
        Writes to cts.account_vault_detail. Snapshots history before any update.
        holder_name is masked to first_initial+"***" for holder_name_display;
        the full name is stored encrypted (pgcrypto) in holder_name_encrypted.
        """
        acct = _require(row, "account_number")
        holder_seq = int(_require(row, "holder_seq"))
        holder_name = _require(row, "holder_name")
        role = _require(row, "role").upper()

        # Mask for display
        holder_display = f"{holder_name[0].upper()}***" if holder_name else "***"
        pan_last4 = row.get("pan_last4")

        from modules.cts.vaults.account_vault import AccountVault
        if not isinstance(self._account_vault, AccountVault):
            raise RuntimeError("AccountVault not configured in processor")

        pepper = self._account_vault._pepper
        import hashlib, hmac as _hmac
        account_hash = _hmac.new(
            pepper.encode(),
            f"{self._bank_id}:{acct}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if self._db_pool is None:
            raise RuntimeError("DB pool not configured in processor")

        async with self._db_pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    """
                    SELECT id, holder_name_display, role, is_active
                    FROM cts.account_vault_detail
                    WHERE bank_id=$1 AND account_hash=$2 AND holder_seq=$3
                    """,
                    self._bank_id, account_hash, holder_seq,
                )
                if existing and action == "INSERT_ONLY":
                    return
                if not existing and action == "UPDATE_ONLY":
                    return
                is_active = action != "DEACTIVATE"

                if existing:
                    await conn.execute(
                        """
                        INSERT INTO cts.account_vault_detail_history
                          (detail_id, bank_id, account_hash, holder_seq,
                           holder_name_display, role, pan_last4, is_active,
                           change_action, changed_by, changed_at, upload_batch_id)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,now(),$11)
                        """,
                        existing["id"], self._bank_id, account_hash, holder_seq,
                        existing["holder_name_display"], existing["role"], pan_last4,
                        existing["is_active"], action, changed_by, batch_id,
                    )

                await conn.execute(
                    """
                    INSERT INTO cts.account_vault_detail
                      (bank_id, account_hash, holder_seq, holder_name_display,
                       role, pan_last4, is_active, upload_batch_id,
                       created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,now(),now())
                    ON CONFLICT (bank_id, account_hash, holder_seq)
                    DO UPDATE SET
                        holder_name_display = EXCLUDED.holder_name_display,
                        role                = EXCLUDED.role,
                        pan_last4           = EXCLUDED.pan_last4,
                        is_active           = EXCLUDED.is_active,
                        upload_batch_id     = EXCLUDED.upload_batch_id,
                        updated_at          = now()
                    """,
                    self._bank_id, account_hash, holder_seq, holder_display,
                    role, pan_last4, is_active, batch_id,
                )

                # Recompute holder_names array on parent account_vault row
                holder_rows = await conn.fetch(
                    """
                    SELECT holder_name_display FROM cts.account_vault_detail
                    WHERE bank_id=$1 AND account_hash=$2 AND is_active=TRUE
                    ORDER BY holder_seq
                    """,
                    self._bank_id, account_hash,
                )
                holder_names = [r["holder_name_display"] for r in holder_rows]
                if holder_names:
                    import json
                    await conn.execute(
                        """
                        UPDATE cts.account_vault
                        SET holder_names=$3, updated_at=now()
                        WHERE bank_id=$1 AND account_hash=$2
                        """,
                        self._bank_id, account_hash, json.dumps(holder_names),
                    )

    async def _handle_signature_row(
        self, row: dict, action: str, changed_by: str, batch_id: str
    ) -> None:
        """Updates cts.account_signatories — mandate rule and quorum_n per account."""
        acct = _require(row, "account_number")
        signatory_id = _require(row, "signatory_id")
        mandate_rule = _require(row, "mandate_rule").upper()
        quorum_n_raw = row.get("quorum_n")
        quorum_n = int(quorum_n_raw) if quorum_n_raw else None

        if self._signature_vault is None:
            raise RuntimeError("SignatureVault not configured in processor")

        pepper = self._signature_vault._pepper
        import hashlib, hmac as _hmac
        account_hash = _hmac.new(
            pepper.encode(),
            f"{self._bank_id}:{acct}".encode(),
            hashlib.sha256,
        ).hexdigest()

        is_active = action != "DEACTIVATE"

        if self._db_pool is None:
            raise RuntimeError("DB pool not configured in processor")

        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cts.account_signatories
                  (bank_id, account_hash, signatory_id, mandate_rule,
                   quorum_n, is_active, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,now())
                ON CONFLICT (bank_id, account_hash, signatory_id)
                DO UPDATE SET
                    mandate_rule = EXCLUDED.mandate_rule,
                    quorum_n     = EXCLUDED.quorum_n,
                    is_active    = EXCLUDED.is_active
                """,
                self._bank_id, account_hash, signatory_id,
                mandate_rule, quorum_n, is_active,
            )

    # ------------------------------------------------------------------
    # Batch lifecycle helpers
    # ------------------------------------------------------------------

    async def _create_batch(
        self, batch_id: str, vault_type: str, filename: Optional[str],
        upload_channel: str, uploaded_by: str, rows_total: int,
    ) -> None:
        if self._db_pool is None:
            return
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cts.vault_upload_batches
                  (id, bank_id, vault_type, filename, upload_channel,
                   uploaded_by, status, rows_total, rows_processed, rows_failed,
                   errors_json, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,'PROCESSING',$7,0,0,'[]'::jsonb,now())
                """,
                batch_id, self._bank_id, vault_type, filename,
                upload_channel, uploaded_by, rows_total,
            )

    async def _complete_batch(
        self, batch_id: str, status: str, result: VaultUploadResult
    ) -> None:
        if self._db_pool is None:
            return
        import json
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.vault_upload_batches
                SET status=$2, rows_processed=$3, rows_failed=$4,
                    errors_json=$5, completed_at=now()
                WHERE id=$1
                """,
                batch_id, status,
                result.rows_processed, result.rows_failed,
                json.dumps(result.errors[:50]),  # cap to avoid huge JSONB
            )

    async def _fail_batch(self, batch_id: str, reason: str) -> None:
        import json
        if self._db_pool is None:
            return
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.vault_upload_batches
                SET status='FAILED', errors_json=$2, completed_at=now()
                WHERE id=$1
                """,
                batch_id,
                json.dumps([{"row": 0, "error": reason}]),
            )


# ------------------------------------------------------------------
# CSV template generator — returns header row per vault type
# ------------------------------------------------------------------

TEMPLATES: dict[str, str] = {
    "CHEQUE_BOOK": (
        "action,account_number,series_start,series_end,issued_date,"
        "branch_code,cbs_book_ref\n"
        "INSERT_ONLY,00112233445566,000001,000050,2026-08-01,MUM001,FIN-2026-00441\n"
    ),
    "LEAF_STATUS": (
        "action,account_number,cheque_number,new_status,"
        "reason,reported_by,effective_date\n"
        "INSERT_ONLY,00112233445566,000023,LOST,"
        "Purse stolen at railway station,Ramesh Kumar,2026-08-15\n"
    ),
    "ACCOUNT_DETAIL": (
        "action,account_number,holder_seq,holder_name,role,pan_last4\n"
        "UPSERT,00112233445566,1,Ramesh Balkrishna Kumar,PRIMARY,8765\n"
        "UPSERT,00112233445566,2,Sunita Ramesh Kumar,JOINT,2341\n"
    ),
    "SIGNATURE": (
        "action,account_number,signatory_id,mandate_rule,quorum_n\n"
        "UPSERT,00112233445566,SIG001,ANY_ONE,\n"
    ),
}


def _require(row: dict, col: str) -> str:
    val = row.get(col)
    if not val:
        raise ValueError(f"Required column {col!r} is empty or missing")
    return val.strip()
