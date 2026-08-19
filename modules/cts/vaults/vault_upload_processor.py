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
  CHEQUE_BOOK    — cheque_book_upload.csv          → ChequeLeafVault.store_book()
  LEAF_STATUS    — cheque_leaf_status_upload.csv   → ChequeLeafVault.set_leaf_status()
  ACCOUNT_DETAIL — account_vault_detail_upload.csv → AccountVaultDetailWriter
  SIGNATURE      — signatory_upload.csv            → SignatureVault account_signatories
  PPS            — pps_upload.csv                  → PPSVault.store_pps()

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

from shared.utils.pii_crypto import encrypt_pii, hash_account_number

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
    "PPS": {
        "required": ["account_number", "cheque_number", "cheque_date", "amount", "payee_name"],
        "optional": ["action", "registration_channel", "cbs_pps_ref", "npci_flag"],
    },
}


class VaultUploadResult:
    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        self.rows_total = 0
        self.rows_processed = 0
        self.rows_failed = 0
        self.errors: list[dict] = []
        self.error_file_path: Optional[str] = None   # MinIO key; set when rows_failed > 0


class VaultUploadProcessor:
    def __init__(
        self,
        bank_id: str,
        db_pool,
        cheque_leaf_vault=None,
        account_vault=None,
        signature_vault=None,
        pps_vault=None,
        pepper: Optional[str] = None,
        minio_client=None,
        error_file_bucket: Optional[str] = None,
    ) -> None:
        self._bank_id = bank_id
        self._db_pool = db_pool
        self._cheque_leaf_vault = cheque_leaf_vault
        self._account_vault = account_vault
        self._signature_vault = signature_vault
        self._pps_vault = pps_vault
        # When pepper is provided, _bulk_account_check validates every non-ACCOUNT_DETAIL row
        # against cts.account_vault before writing to any child vault table.
        # Without pepper the check is skipped — tests and dev deployments that don't need it.
        self._pepper = pepper
        # MinIO client + bucket for writing the full error CSV.
        # Both must be non-None to write; either missing → fall back to errors_json JSONB.
        self._minio_client = minio_client
        self._error_file_bucket = error_file_bucket

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

        # Referential integrity: bulk-check all accounts exist in cts.account_vault.
        # One DB round-trip for the whole batch — cheap for any realistic CSV size.
        # Skipped when: pepper not set (dev/test), db_pool is None, or ACCOUNT_DETAIL
        # (which IS the source of truth — it creates the account_vault entries).
        valid_hashes: Optional[frozenset[str]] = None
        if self._pepper is not None and self._db_pool is not None and vault_type != "ACCOUNT_DETAIL":
            valid_hashes = await self._bulk_account_check(rows)

        # Cache account_number → hash to avoid recomputing HMAC per row
        _acct_hash_cache: dict[str, str] = {}

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

            # Referential integrity gate: reject rows for accounts not in cts.account_vault
            if valid_hashes is not None:
                raw_acct = (clean.get("account_number") or "").strip()
                if raw_acct:
                    if raw_acct not in _acct_hash_cache:
                        _acct_hash_cache[raw_acct] = hash_account_number(
                            raw_acct, self._bank_id, self._pepper
                        )
                    if _acct_hash_cache[raw_acct] not in valid_hashes:
                        result.rows_failed += 1
                        result.errors.append({
                            "row": idx,
                            "error": (
                                f"Account ****{raw_acct[-4:]} not found in cts.account_vault"
                                f" — upload ACCOUNT_DETAIL first"
                            ),
                            "error_code": "ACCOUNT_NOT_FOUND_IN_VAULT",
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
    # Referential integrity
    # ------------------------------------------------------------------

    async def _bulk_account_check(self, rows: list[dict]) -> frozenset[str]:
        """
        Bulk-validate that every account_number in the CSV exists in cts.account_vault.
        One SELECT per batch regardless of row count — O(unique_accounts) not O(rows).
        Returns frozenset of valid account_hashes. An empty frozenset means zero accounts
        in this batch have an account_vault entry — all rows will be rejected.
        """
        unique_accounts = {
            r.get("account_number", "").strip()
            for r in rows
            if r.get("account_number", "").strip()
        }
        if not unique_accounts:
            return frozenset()

        hashes = [
            hash_account_number(acct, self._bank_id, self._pepper)
            for acct in unique_accounts
        ]

        async with self._db_pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT account_hash FROM cts.account_vault
                WHERE bank_id = $1 AND account_hash = ANY($2::text[])
                """,
                self._bank_id,
                hashes,
            )
        return frozenset(r["account_hash"] for r in records)

    # ------------------------------------------------------------------
    # Row handlers per vault type
    # ------------------------------------------------------------------

    def _get_handler(self, vault_type: str):
        return {
            "CHEQUE_BOOK": self._handle_cheque_book_row,
            "LEAF_STATUS": self._handle_leaf_status_row,
            "ACCOUNT_DETAIL": self._handle_account_detail_row,
            "SIGNATURE": self._handle_signature_row,
            "PPS": self._handle_pps_row,
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

        account_hash = hash_account_number(acct, self._bank_id, self._account_vault._pepper)

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

                # Encrypt full holder name with pgcrypto via pii_crypto utility
                from shared.config.config_service import config_service as _cs
                pii_key = _cs.get_secret(f"banks.{self._bank_id}.pii_enc_key")
                holder_name_enc = await encrypt_pii(holder_name, pii_key, conn)

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
                      (bank_id, account_hash, holder_seq, holder_name_encrypted,
                       holder_name_display, role, pan_last4, is_active, upload_batch_id,
                       created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now(),now())
                    ON CONFLICT (bank_id, account_hash, holder_seq)
                    DO UPDATE SET
                        holder_name_encrypted = EXCLUDED.holder_name_encrypted,
                        holder_name_display   = EXCLUDED.holder_name_display,
                        role                  = EXCLUDED.role,
                        pan_last4             = EXCLUDED.pan_last4,
                        is_active             = EXCLUDED.is_active,
                        upload_batch_id       = EXCLUDED.upload_batch_id,
                        updated_at            = now()
                    """,
                    self._bank_id, account_hash, holder_seq, holder_name_enc,
                    holder_display, role, pan_last4, is_active, batch_id,
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

    async def _handle_pps_row(
        self, row: dict, action: str, changed_by: str, batch_id: str
    ) -> None:
        """
        Registers or cancels a PPS entry (Positive Pay System).

        5 RBI-mandated fields: account_number, cheque_number, cheque_date, amount, payee_name.
        amount: rupees (float/int) — converted to paise internally.
        action DEACTIVATE maps to store_pps action=CANCEL (deletes Redis key, sets CANCELLED in DB).
        """
        from datetime import date as _date
        acct = _require(row, "account_number")
        cheque_number = _require(row, "cheque_number").zfill(6)
        cheque_date_raw = _require(row, "cheque_date")
        cheque_date = _date.fromisoformat(cheque_date_raw)
        amount_raw = _require(row, "amount")
        try:
            amount_paise = int(float(amount_raw) * 100)
        except ValueError as exc:
            raise ValueError(f"amount must be numeric, got {amount_raw!r}") from exc
        payee = _require(row, "payee_name")

        store_action = "CANCEL" if action == "DEACTIVATE" else action

        if self._pps_vault is None:
            raise RuntimeError("PPSVault not configured in processor")

        await self._pps_vault.store_pps(
            account_number=acct,
            cheque_number=cheque_number,
            cheque_date=cheque_date,
            amount_paise=amount_paise,
            payee=payee,
            registered_by=changed_by,
            action=store_action,
            registration_channel=row.get("registration_channel") or "BRANCH_UPLOAD",
            cbs_pps_ref=row.get("cbs_pps_ref"),
            npci_flag=row.get("npci_flag") or None,
            upload_batch_id=batch_id,
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

        account_hash = hash_account_number(acct, self._bank_id, self._signature_vault._pepper)

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

    # ------------------------------------------------------------------
    # Error file writer (MinIO)
    # ------------------------------------------------------------------

    def _write_error_file(
        self, batch_id: str, errors: list[dict]
    ) -> Optional[str]:
        """
        Write the full error list to MinIO as a UTF-8 CSV.
        Returns the object key on success, None if MinIO is unavailable or raises.
        Key pattern: {bank_id}/vault-errors/{batch_id}.csv
        Columns: row, error_message, error_code
        This is intentionally synchronous — MinIO client is blocking; called from async
        context but does not touch the event loop. Non-fatal: exceptions are swallowed.
        """
        if self._minio_client is None or self._error_file_bucket is None:
            return None

        object_key = f"{self._bank_id}/vault-errors/{batch_id}.csv"
        try:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["row", "error_message", "error_code"])
            writer.writeheader()
            for err in errors:
                writer.writerow({
                    "row": err.get("row", ""),
                    "error_message": err.get("error", ""),
                    "error_code": err.get("error_code", ""),
                })
            raw = buf.getvalue().encode("utf-8")
            data = io.BytesIO(raw)
            self._minio_client.put_object(
                bucket_name=self._error_file_bucket,
                object_name=object_key,
                data=data,
                length=len(raw),
                content_type="text/csv",
            )
            log.info(
                "vault_upload_processor.error_file_written",
                bank_id=self._bank_id,
                batch_id=batch_id,
                object_key=object_key,
                error_count=len(errors),
            )
            return object_key
        except Exception as exc:
            log.warning(
                "vault_upload_processor.error_file_write_failed",
                bank_id=self._bank_id,
                batch_id=batch_id,
                error=str(exc),
            )
            return None

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

        # Write full error list to MinIO (non-fatal if unavailable).
        # Only when rows_failed > 0 — clean batches need no error file.
        if result.rows_failed > 0:
            result.error_file_path = self._write_error_file(batch_id, result.errors)

        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.vault_upload_batches
                SET status=$2, rows_processed=$3, rows_failed=$4,
                    errors_json=$5, error_file_path=$6, completed_at=now()
                WHERE id=$1
                """,
                batch_id, status,
                result.rows_processed, result.rows_failed,
                json.dumps(result.errors[:1000]),  # JSONB preview; full list in MinIO file
                result.error_file_path,
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
    "PPS": (
        "action,account_number,cheque_number,cheque_date,amount,payee_name,"
        "registration_channel,cbs_pps_ref,npci_flag\n"
        "INSERT_ONLY,00112233445566,000101,2026-08-20,50000.00,"
        "Mahindra Finance Ltd,NET_BANKING,,\n"
    ),
}


def _require(row: dict, col: str) -> str:
    val = row.get(col)
    if not val:
        raise ValueError(f"Required column {col!r} is empty or missing")
    return val.strip()
