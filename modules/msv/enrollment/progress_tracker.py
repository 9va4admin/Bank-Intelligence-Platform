"""
EnrollmentProgressTracker — reads/writes enrollment_progress and enrollment_jobs tables.

Used by AccountEnroller (per-account) and BulkEnrollmentProcessor (job-level progress).
All writes are to YugabyteDB msv schema.
"""
from typing import Any, Optional

import structlog
from opentelemetry import trace

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.enrollment")


class EnrollmentProgressTracker:
    def __init__(self, db_pool) -> None:
        self._db = db_pool

    async def is_enrolled(self, bank_id: str, account_hash: str) -> bool:
        """Return True iff the account is in ENROLLED status."""
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT status, enrolled_at
                FROM msv.enrollment_progress
                WHERE bank_id = $1 AND account_hash = $2
                """,
                bank_id,
                account_hash,
            )
        if row is None:
            return False
        return row["status"] == "ENROLLED"

    async def mark_enrolled(
        self,
        bank_id: str,
        account_hash: str,
        batch_id: str,
    ) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO msv.enrollment_progress
                    (bank_id, account_hash, operation_type, status, enrolled_at, batch_id)
                VALUES ($1, $2, '', 'ENROLLED', NOW(), $3)
                ON CONFLICT (bank_id, account_hash)
                DO UPDATE SET status = 'ENROLLED', enrolled_at = NOW(), batch_id = $3
                """,
                bank_id,
                account_hash,
                batch_id,
            )
        log.info(
            "enrollment.progress.enrolled",
            bank_id=bank_id,
            batch_id=batch_id,
        )

    async def mark_failed(
        self,
        bank_id: str,
        account_hash: str,
        error: str,
        batch_id: str,
    ) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO msv.enrollment_progress
                    (bank_id, account_hash, operation_type, status, error_reason, batch_id)
                VALUES ($1, $2, '', 'FAILED', $3, $4)
                ON CONFLICT (bank_id, account_hash)
                DO UPDATE SET status = 'FAILED', error_reason = $3, batch_id = $4
                """,
                bank_id,
                account_hash,
                error,
                batch_id,
            )
        log.warning(
            "enrollment.progress.failed",
            bank_id=bank_id,
            error=error,
            batch_id=batch_id,
        )

    async def get_job(self, job_id: str) -> Optional[dict]:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT job_id, bank_id, file_name, file_type, status,
                       total_accounts, processed_accounts, enrolled_accounts,
                       failed_accounts, total_signatures, enrolled_signatures,
                       current_operation_type, started_at, completed_at, error_summary
                FROM msv.enrollment_jobs
                WHERE job_id = $1
                """,
                job_id,
            )
        if row is None:
            return None
        return dict(row)

    async def update_job_counts(
        self,
        job_id: str,
        accounts_delta: int,
        sigs_delta: int,
    ) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                UPDATE msv.enrollment_jobs
                SET processed_accounts = processed_accounts + $2,
                    enrolled_signatures = enrolled_signatures + $3
                WHERE job_id = $1
                """,
                job_id,
                accounts_delta,
                sigs_delta,
            )
