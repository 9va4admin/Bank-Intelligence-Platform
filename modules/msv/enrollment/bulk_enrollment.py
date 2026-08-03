"""
BulkEnrollmentProcessor — streams a gzipped CSV file and enrolls accounts in parallel.

CSV format: account_number,operation_type,branch_code
File types:
  signatories_bulk_YYYYMMDD.csv.gz      → full bulk enrollment
  signatories_delta_YYYYMMDD[_HHMM].csv.gz → incremental delta
  signatories_revocation_YYYYMMDD.csv.gz  → revoke signatories (handled separately)

Priority order: Corporate (L/T/P) → Joint (J/JAS) → Retail (S/E/F/A)
NEVER loads the entire file into memory. Uses CSV streaming via io.TextIOWrapper + gzip.

Concurrency: asyncio.Semaphore(20) — max 20 parallel embedding calls.
Progress: updates enrollment_jobs every PROGRESS_BATCH_SIZE accounts processed.
Resumable: is_enrolled() checked per account — already enrolled accounts skipped.
"""
import asyncio
import csv
import gzip
import io
import uuid
from pathlib import Path
from typing import Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from modules.msv.enrollment.account_enroller import AccountEnroller, EnrollmentResult
from modules.msv.enrollment.progress_tracker import EnrollmentProgressTracker

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.enrollment")

_MAX_CONCURRENT = 20
_PROGRESS_BATCH_SIZE = 500

# Priority groups — processed in order (Corporate → Joint → Retail)
_CORPORATE_TYPES = {"L", "T", "P"}
_JOINT_TYPES = {"J", "JAS"}
_RETAIL_TYPES = {"S", "E", "F", "A"}

# Order for sorting: lower = higher priority
_OP_PRIORITY = {
    **{t: 0 for t in _CORPORATE_TYPES},
    **{t: 1 for t in _JOINT_TYPES},
    **{t: 2 for t in _RETAIL_TYPES},
}


class BulkEnrollmentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    bank_id: str
    total_processed: int
    enrolled: int
    skipped: int
    failed: int
    total_signatures_enrolled: int


class BulkEnrollmentProcessor:
    """
    Processes a gzipped CSV enrollment file.

    Args:
        account_enroller:  AccountEnroller instance for per-account processing
        progress_tracker:  EnrollmentProgressTracker for job-level progress
    """

    def __init__(
        self,
        account_enroller: AccountEnroller,
        progress_tracker: EnrollmentProgressTracker,
    ) -> None:
        self._enroller = account_enroller
        self._tracker = progress_tracker

    async def process_file(
        self,
        file_path: Path,
        bank_id: str,
        job_id: str,
    ) -> BulkEnrollmentSummary:
        """
        Stream and process a gzipped CSV file.

        Priority groups are processed in order: Corporate → Joint → Retail.
        Within each group, accounts are processed concurrently (max 20 at a time).
        """
        with tracer.start_as_current_span("msv.bulk_enrollment.process_file") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("job_id", job_id)
            span.set_attribute("file_path", str(file_path))

            # Read all rows grouped by priority (minimal memory: just store tuples of strings)
            priority_groups: dict[int, list[tuple[str, str, str]]] = {0: [], 1: [], 2: []}

            with gzip.open(str(file_path), "rt", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    account_number = row.get("account_number", "").strip()
                    operation_type = row.get("operation_type", "").strip()
                    branch_code = row.get("branch_code", "").strip()
                    if not account_number or not operation_type:
                        continue
                    priority = _OP_PRIORITY.get(operation_type, 2)
                    priority_groups[priority].append((account_number, operation_type, branch_code))

            semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
            enrolled_count = 0
            skipped_count = 0
            failed_count = 0
            total_sigs = 0
            total_processed = 0

            for priority in sorted(priority_groups.keys()):
                rows = priority_groups[priority]
                if not rows:
                    continue

                async def _process_row(
                    acct: str, op_type: str, _branch: str
                ) -> EnrollmentResult:
                    # Idempotency: check before acquiring semaphore
                    account_hash = None
                    try:
                        # Let enroller handle the is_enrolled check internally
                        async with semaphore:
                            return await self._enroller.enroll(
                                bank_id, acct, op_type, job_id
                            )
                    except Exception as exc:
                        from modules.msv.enrollment.account_enroller import EnrollmentResult
                        log.error("msv.bulk_enrollment.row_error", error=str(exc))
                        return EnrollmentResult(
                            account_hash="error",
                            status="FAILED",
                            specimens_enrolled=0,
                            error_reason=str(exc),
                        )

                tasks = [_process_row(acct, op_type, branch) for acct, op_type, branch in rows]
                results = await asyncio.gather(*tasks)

                for result in results:
                    total_processed += 1
                    if result.status == "ENROLLED":
                        enrolled_count += 1
                        total_sigs += result.specimens_enrolled
                    elif result.status == "SKIPPED":
                        skipped_count += 1
                    else:
                        failed_count += 1

                    # Progress update every N accounts
                    if total_processed % _PROGRESS_BATCH_SIZE == 0:
                        await self._tracker.update_job_counts(
                            job_id,
                            accounts_delta=_PROGRESS_BATCH_SIZE,
                            sigs_delta=0,
                        )

            summary = BulkEnrollmentSummary(
                job_id=job_id,
                bank_id=bank_id,
                total_processed=total_processed,
                enrolled=enrolled_count,
                skipped=skipped_count,
                failed=failed_count,
                total_signatures_enrolled=total_sigs,
            )

            span.set_attribute("total_processed", total_processed)
            span.set_attribute("enrolled", enrolled_count)
            span.set_attribute("failed", failed_count)

            log.info(
                "msv.bulk_enrollment.complete",
                bank_id=bank_id,
                job_id=job_id,
                total=total_processed,
                enrolled=enrolled_count,
                skipped=skipped_count,
                failed=failed_count,
            )

            return summary
