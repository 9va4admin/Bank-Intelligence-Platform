"""
cbs_sync activity for MSV — fetches signatory data from CBS and enrolls into registry.

This activity is used by MSVValidationWorkflow when signatory vault data is stale
or missing. It calls AccountEnroller for each account in the input list.

CBS unavailability → CBSSyncResult(status="DEGRADED", enrolled_count=0)
  Never raises CBSUnavailableError out — the workflow handles degraded state.

PII rules:
  - account_numbers are passed to CBS connector and hashed internally
  - Raw account numbers are never logged here — enroller handles masking
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.msv.enrollment.account_enroller import AccountEnroller
from shared.cbs_connector.exceptions import CBSUnavailableError

log = structlog.get_logger()


class CBSSyncInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    account_numbers: list[str]
    batch_id: str


class CBSSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str               # "COMPLETE" | "DEGRADED"
    bank_id: str
    batch_id: str
    enrolled_count: int
    skipped_count: int
    failed_count: int


@activity.defn
async def sync_signatories_from_cbs(
    inp: CBSSyncInput,
    cbs_connector=None,
    enroller: Optional[AccountEnroller] = None,
) -> CBSSyncResult:
    """
    Fetch signatory data from CBS and enroll each account.

    On CBSUnavailableError: returns DEGRADED status (workflow routes to human review).
    Never raises — errors are captured in the result.
    """
    enrolled_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        for account_number in inp.account_numbers:
            try:
                # Verify CBS is reachable for this account (enroller will do full flow)
                signatory_list = await cbs_connector.get_signatory_data(
                    account_number, inp.bank_id
                )
            except CBSUnavailableError as exc:
                log.warning(
                    "msv.cbs_sync.cbs_unavailable",
                    bank_id=inp.bank_id,
                    batch_id=inp.batch_id,
                    error=str(exc),
                )
                return CBSSyncResult(
                    status="DEGRADED",
                    bank_id=inp.bank_id,
                    batch_id=inp.batch_id,
                    enrolled_count=0,
                    skipped_count=0,
                    failed_count=len(inp.account_numbers),
                )

            if not signatory_list:
                log.warning(
                    "msv.cbs_sync.no_signatory_data",
                    bank_id=inp.bank_id,
                    batch_id=inp.batch_id,
                )
                failed_count += 1
                continue

            # Delegate to AccountEnroller for embed + store
            result = await enroller.enroll(
                bank_id=inp.bank_id,
                account_number=account_number,
                operation_type=signatory_list[0].operation_type,
                batch_id=inp.batch_id,
            )

            if result.status == "ENROLLED":
                enrolled_count += 1
            elif result.status == "SKIPPED":
                skipped_count += 1
            else:
                failed_count += 1

    except CBSUnavailableError as exc:
        log.warning(
            "msv.cbs_sync.cbs_unavailable_outer",
            bank_id=inp.bank_id,
            batch_id=inp.batch_id,
            error=str(exc),
        )
        return CBSSyncResult(
            status="DEGRADED",
            bank_id=inp.bank_id,
            batch_id=inp.batch_id,
            enrolled_count=0,
            skipped_count=0,
            failed_count=len(inp.account_numbers),
        )

    log.info(
        "msv.cbs_sync.complete",
        bank_id=inp.bank_id,
        batch_id=inp.batch_id,
        enrolled=enrolled_count,
        skipped=skipped_count,
        failed=failed_count,
    )

    return CBSSyncResult(
        status="COMPLETE",
        bank_id=inp.bank_id,
        batch_id=inp.batch_id,
        enrolled_count=enrolled_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )
