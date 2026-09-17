"""
IFSCRepository — asyncpg-based data access for cts.ifsc_registry.

All queries are bank_id-scoped (multi-tenant isolation).
No raw PII — IFSC codes and branch metadata are not PII.

Methods:
  lookup_ifsc(bank_id, ifsc_code, smb_id=None, active_only=True) → IFSCEntry | None
  get_ifsc_by_id(entry_id)  → IFSCEntry | None
  list_ifsc(bank_id, ...)   → list[IFSCEntry]
  create_ifsc(bank_id, req, created_by) → IFSCEntry
  approve_ifsc(entry_id, approved_by)   → IFSCEntry | None
  deactivate_ifsc(entry_id, updated_by) → IFSCEntry | None
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog

from modules.cts.ifsc.models import IFSCCreateRequest, IFSCEntry

log = structlog.get_logger()


class IFSCDuplicateError(Exception):
    """Raised when (bank_id, ifsc_code) unique constraint is violated."""
    def __init__(self, ifsc_code: str) -> None:
        super().__init__(f"IFSC {ifsc_code!r} already registered for this bank")
        self.ifsc_code = ifsc_code


def _row_to_entry(row: dict) -> IFSCEntry:
    return IFSCEntry(
        id=str(row["id"]),
        bank_id=row["bank_id"],
        bank_type=row["bank_type"],
        smb_id=row.get("smb_id"),
        ifsc_code=row["ifsc_code"],
        branch_name=row.get("branch_name"),
        branch_city=row.get("branch_city"),
        micr_code=row.get("micr_code"),
        is_active=bool(row["is_active"]),
        effective_from=row["effective_from"],
        effective_till=row.get("effective_till"),
        status=row["status"],
        created_by=row["created_by"],
        approved_by=row.get("approved_by"),
    )


class IFSCRepository:
    def __init__(self, db) -> None:
        self._db = db

    async def lookup_ifsc(
        self,
        bank_id: str,
        ifsc_code: str,
        smb_id: Optional[str] = None,
        active_only: bool = True,
    ) -> Optional[IFSCEntry]:
        """
        Look up a single IFSC entry scoped to bank_id.
        When smb_id is provided, the lookup is further scoped to that sub-member.
        When active_only=True (default), only ACTIVE entries are returned.
        """
        if smb_id is not None:
            if active_only:
                query = """
                    SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry
                    WHERE bank_id = $1
                      AND ifsc_code = $2
                      AND smb_id = $3
                      AND status = 'ACTIVE'
                      AND is_active = TRUE
                    LIMIT 1
                """
                row = await self._db.fetchrow(query, bank_id, ifsc_code.upper(), smb_id)
            else:
                query = """
                    SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry
                    WHERE bank_id = $1
                      AND ifsc_code = $2
                      AND smb_id = $3
                    LIMIT 1
                """
                row = await self._db.fetchrow(query, bank_id, ifsc_code.upper(), smb_id)
        else:
            if active_only:
                query = """
                    SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry
                    WHERE bank_id = $1
                      AND ifsc_code = $2
                      AND status = 'ACTIVE'
                      AND is_active = TRUE
                    LIMIT 1
                """
                row = await self._db.fetchrow(query, bank_id, ifsc_code.upper())
            else:
                query = """
                    SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry
                    WHERE bank_id = $1
                      AND ifsc_code = $2
                    LIMIT 1
                """
                row = await self._db.fetchrow(query, bank_id, ifsc_code.upper())

        return _row_to_entry(row) if row else None

    async def get_ifsc_by_id(self, entry_id: str) -> Optional[IFSCEntry]:
        query = """SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry WHERE id = $1 LIMIT 1"""
        row = await self._db.fetchrow(query, entry_id)
        return _row_to_entry(row) if row else None

    async def list_ifsc(
        self,
        bank_id: str,
        bank_type: Optional[str] = None,
        smb_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[IFSCEntry]:
        conditions = ["bank_id = $1"]
        params: list = [bank_id]
        idx = 2

        if active_only:
            conditions.append(f"status = ${idx} AND is_active = TRUE")
            params.append("ACTIVE")
            idx += 1

        if bank_type is not None:
            conditions.append(f"bank_type = ${idx}")
            params.append(bank_type)
            idx += 1

        if smb_id is not None:
            conditions.append(f"smb_id = ${idx}")
            params.append(smb_id)
            idx += 1

        where = " AND ".join(conditions)
        query = f"""
            SELECT id, bank_id, bank_type, smb_id, ifsc_code, branch_name, branch_city,
                       micr_code, is_active, effective_from, effective_till, status,
                       created_by, approved_by FROM cts.ifsc_registry
            WHERE {where}
            ORDER BY ifsc_code ASC
            LIMIT {limit}
        """
        rows = await self._db.fetch(query, *params)
        return [_row_to_entry(r) for r in rows]

    async def create_ifsc(
        self,
        bank_id: str,
        req: IFSCCreateRequest,
        created_by: str,
    ) -> IFSCEntry:
        """
        Insert a new IFSC entry with status=PENDING.
        Raises IFSCDuplicateError if (bank_id, ifsc_code) already exists.
        """
        query = """
            INSERT INTO cts.ifsc_registry (
                bank_id, bank_type, smb_id, ifsc_code,
                branch_name, branch_city, micr_code,
                is_active, effective_from, status, created_by, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, $8, 'PENDING', $9, NOW())
            RETURNING *
        """
        try:
            row = await self._db.fetchrow(
                query,
                bank_id, req.bank_type, req.smb_id, req.ifsc_code,
                req.branch_name, req.branch_city, req.micr_code,
                req.effective_from, created_by,
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise IFSCDuplicateError(req.ifsc_code) from exc
            raise
        return _row_to_entry(row)

    async def approve_ifsc(
        self,
        entry_id: str,
        approved_by: str,
    ) -> Optional[IFSCEntry]:
        """Approve a PENDING entry → ACTIVE. Returns None if not found."""
        query = """
            UPDATE cts.ifsc_registry
            SET status = 'ACTIVE',
                is_active = TRUE,
                approved_by = $2,
                approved_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        row = await self._db.fetchrow(query, entry_id, approved_by)
        return _row_to_entry(row) if row else None

    async def deactivate_ifsc(
        self,
        entry_id: str,
        updated_by: str,
    ) -> Optional[IFSCEntry]:
        """Deactivate an ACTIVE entry → INACTIVE. Returns None if not found."""
        query = """
            UPDATE cts.ifsc_registry
            SET status = 'INACTIVE',
                is_active = FALSE,
                updated_by = $2,
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        row = await self._db.fetchrow(query, entry_id, updated_by)
        return _row_to_entry(row) if row else None
