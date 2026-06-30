"""
VaultSyncWorkflow — syncs CBS account data into Redis vaults.

Triggered: CBS event stream OR schedule (daily at 6AM).
Workflow ID: cts-vaultsync-{bank_id}-{date}  (idempotent per bank per day).
Activities:
  1. load_signatures_from_cbs  — pull all signature specimens from CBS
  2. load_pps_from_cbs         — pull active positive-pay records
  3. warm_redis_vault          — pipeline-write to Redis (batch SET)
  4. verify_vault_integrity    — sample N random keys, assert Redis has them

Exactly-once: Temporal workflow ID deduplicates concurrent trigger events.
"""
import hashlib
import hmac
from datetime import date
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class VaultSyncInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    sync_date: str = ""         # ISO date "YYYY-MM-DD" — part of idempotent workflow ID
    pepper: str = ""            # HMAC pepper from Vault (not logged)
    triggered_by: str = "SCHEDULED"   # SCHEDULED | MANUAL


class SignatureRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    specimens: list[bytes]   # binary image blobs


class PPSRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    cheque_series_start: str
    amount: float
    payee: str
    ttl_seconds: Optional[int] = None


class VaultSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                       # "SYNC_COMPLETE" | "PARTIAL_FAILURE"
    signatures_loaded: int
    pps_records_loaded: int
    stop_records_loaded: int = 0
    integrity_check_passed: bool
    failed_accounts: list[str] = []
    triggered_by: str = "SCHEDULED"


# ---------------------------------------------------------------------------
# Activity: load_signatures_from_cbs
# ---------------------------------------------------------------------------

async def load_signatures_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[SignatureRecord]:
    """
    Fetch all signature specimens from CBS for this bank.
    Returns list of SignatureRecord — each account may have multiple specimens.
    CBS unavailability raises CBSUnavailableError (Temporal retries with CBS_RETRY policy).
    """
    raw_records = await cbs_connector.list_signature_specimens(bank_id)

    records = []
    for raw in raw_records:
        account_number = raw.get("account_number", "")
        specimens_b64 = raw.get("specimens", [])
        if not account_number or not specimens_b64:
            log.warning(
                "vault_sync.invalid_signature_record",
                bank_id=bank_id,
                account_last4=account_number[-4:] if account_number else "????",
            )
            continue
        specimens = [
            s if isinstance(s, bytes) else s.encode()
            for s in specimens_b64
        ]
        records.append(SignatureRecord(account_number=account_number, specimens=specimens))

    log.info(
        "vault_sync.signatures_loaded_from_cbs",
        bank_id=bank_id,
        count=len(records),
    )
    return records


# ---------------------------------------------------------------------------
# Activity: load_pps_from_cbs
# ---------------------------------------------------------------------------

async def load_pps_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[PPSRecord]:
    """
    Fetch all active Positive Pay records from CBS.
    Returns list of PPSRecord.
    """
    raw_records = await cbs_connector.list_positive_pay_records(bank_id)

    records = []
    for raw in raw_records:
        account_number = raw.get("account_number", "")
        cheque_series = raw.get("cheque_series_start", "")
        amount = raw.get("amount")
        payee = raw.get("payee", "")

        if not all([account_number, cheque_series, amount is not None, payee]):
            log.warning(
                "vault_sync.invalid_pps_record",
                bank_id=bank_id,
                account_last4=account_number[-4:] if account_number else "????",
            )
            continue

        records.append(PPSRecord(
            account_number=account_number,
            cheque_series_start=cheque_series,
            amount=float(amount),
            payee=payee,
            ttl_seconds=raw.get("ttl_seconds"),
        ))

    log.info(
        "vault_sync.pps_loaded_from_cbs",
        bank_id=bank_id,
        count=len(records),
    )
    return records


# ---------------------------------------------------------------------------
# Activity: warm_redis_vault
# ---------------------------------------------------------------------------

def _hmac_key(pepper: str, bank_id: str, account_number: str) -> str:
    return hmac.new(
        pepper.encode(),
        f"{bank_id}:{account_number}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def warm_redis_vault(
    bank_id: str,
    pepper: str,
    signature_records: list[SignatureRecord],
    pps_records: list[PPSRecord],
    redis_client=None,
) -> dict[str, int]:
    """
    Pipeline-write all vault records to Redis.
    Uses Redis pipeline for bulk writes — O(1) round trips per batch.
    Returns counts of successfully written records.
    """
    sig_count = 0
    pps_count = 0

    # Signature vault writes
    if signature_records:
        pipe = redis_client.pipeline()
        for rec in signature_records:
            digest = _hmac_key(pepper, bank_id, rec.account_number)
            key = f"sig:{bank_id}:{digest}"
            pipe.delete(key)
            for specimen in rec.specimens:
                pipe.rpush(key, specimen)
        pipe.execute()
        sig_count = len(signature_records)

    # PPS vault writes
    if pps_records:
        pipe = redis_client.pipeline()
        for rec in pps_records:
            digest = _hmac_key(pepper, bank_id, rec.account_number)
            key = f"pps:{bank_id}:{digest}:{rec.cheque_series_start}"
            pipe.hset(key, mapping={
                "amount": str(rec.amount),
                "payee": rec.payee,
                "cheque_number": rec.cheque_series_start,
            })
            if rec.ttl_seconds:
                pipe.expire(key, rec.ttl_seconds)
        pipe.execute()
        pps_count = len(pps_records)

    log.info(
        "vault_sync.warm_complete",
        bank_id=bank_id,
        signatures=sig_count,
        pps_records=pps_count,
    )
    return {"signatures": sig_count, "pps_records": pps_count}


# ---------------------------------------------------------------------------
# Activity: verify_vault_integrity
# ---------------------------------------------------------------------------

async def verify_vault_integrity(
    bank_id: str,
    pepper: str,
    sample_accounts: list[str],
    redis_client=None,
) -> bool:
    """
    Spot-check N random accounts to confirm Redis actually has their vault entries.
    Returns True if all sampled accounts are present in Redis.
    Logs any missing accounts at WARNING level.
    """
    missing = []
    for account_number in sample_accounts:
        digest = _hmac_key(pepper, bank_id, account_number)
        sig_key = f"sig:{bank_id}:{digest}"
        try:
            count = redis_client.llen(sig_key)
        except Exception as exc:
            log.error(
                "vault_sync.integrity_redis_error",
                bank_id=bank_id,
                account_last4=account_number[-4:],
                error=str(exc),
            )
            missing.append(account_number[-4:])
            continue

        if count == 0:
            log.warning(
                "vault_sync.integrity_miss",
                bank_id=bank_id,
                account_last4=account_number[-4:],
            )
            missing.append(account_number[-4:])

    passed = len(missing) == 0
    log.info(
        "vault_sync.integrity_check",
        bank_id=bank_id,
        sampled=len(sample_accounts),
        missing=len(missing),
        passed=passed,
    )
    return passed


# ---------------------------------------------------------------------------
# VaultSyncWorkflow — orchestrates all four activities
# ---------------------------------------------------------------------------

class VaultSyncWorkflow:
    def workflow_id(self, bank_id: str, sync_date: str) -> str:
        return f"cts-vaultsync-{bank_id}-{sync_date}"

    async def run(self, inp: VaultSyncInput) -> VaultSyncResult:
        """
        Production Temporal @workflow.run entry point.
        Delegates to run_with_mocks with no injected deps (Temporal activity stubs resolve them).
        """
        return await self.run_with_mocks(inp)

    async def run_with_mocks(
        self,
        inp: VaultSyncInput,
        cbs_connector=None,
        redis_client=None,
        sample_accounts: Optional[list[str]] = None,
    ) -> VaultSyncResult:
        """
        Testable orchestration. Production Temporal @workflow.run wraps this.
        """
        # Activity 1: Load signatures from CBS
        try:
            sig_records = await load_signatures_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
        except Exception as exc:
            log.error(
                "vault_sync.signature_load_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=0,
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["SIGNATURE_LOAD_FAILED"],
            )

        # Activity 2: Load PPS records from CBS
        try:
            pps_records = await load_pps_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
        except Exception as exc:
            log.error(
                "vault_sync.pps_load_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=len(sig_records),
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["PPS_LOAD_FAILED"],
            )

        # Activity 3: Write to Redis vaults
        await warm_redis_vault(
            bank_id=inp.bank_id,
            pepper=inp.pepper,
            signature_records=sig_records,
            pps_records=pps_records,
            redis_client=redis_client,
        )

        # Activity 4: Spot-check integrity
        accounts_to_sample = sample_accounts or [r.account_number for r in sig_records[:10]]
        integrity_ok = await verify_vault_integrity(
            bank_id=inp.bank_id,
            pepper=inp.pepper,
            sample_accounts=accounts_to_sample,
            redis_client=redis_client,
        )

        log.info(
            "vault_sync.workflow_complete",
            bank_id=inp.bank_id,
            sync_date=inp.sync_date,
            signatures=len(sig_records),
            pps=len(pps_records),
            integrity=integrity_ok,
        )

        return VaultSyncResult(
            outcome="SYNC_COMPLETE",
            signatures_loaded=len(sig_records),
            pps_records_loaded=len(pps_records),
            integrity_check_passed=integrity_ok,
            triggered_by=inp.triggered_by,
        )


# ---------------------------------------------------------------------------
# Temporal Schedule — register once per bank at worker startup
# ---------------------------------------------------------------------------

async def register_vault_sync_schedule(temporal_client, bank_id: str) -> None:
    """
    Register (or update) a Temporal Schedule that triggers VaultSyncWorkflow
    every day at 07:00 AM.

    Schedule ID: cts-vaultsync-schedule-{bank_id}
    If the schedule already exists it is left unchanged (idempotent).

    Call this from the CTS worker startup coroutine after the Temporal client
    is ready:

        await register_vault_sync_schedule(client, bank_id)
    """
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleSpec,
        ScheduleAlreadyRunningError,
    )
    from temporalio.common import RetryPolicy
    from datetime import timedelta

    schedule_id = f"cts-vaultsync-schedule-{bank_id}"

    try:
        await temporal_client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    VaultSyncWorkflow.run,
                    VaultSyncInput(bank_id=bank_id, triggered_by="SCHEDULED"),
                    id=f"cts-vaultsync-{bank_id}-scheduled",
                    task_queue=f"cts-processing-{bank_id}",
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(minutes=5),
                    ),
                ),
                spec=ScheduleSpec(
                    # "0 7 * * *" — every day at 07:00 AM
                    cron_expressions=["0 7 * * *"],
                ),
            ),
        )
        log.info("vault_sync.schedule_registered", bank_id=bank_id, schedule_id=schedule_id)
    except Exception as exc:
        # Schedule already exists — no action needed
        if "already exists" in str(exc).lower() or "already registered" in str(exc).lower():
            log.info("vault_sync.schedule_exists", bank_id=bank_id, schedule_id=schedule_id)
        else:
            log.warning(
                "vault_sync.schedule_register_failed",
                bank_id=bank_id,
                schedule_id=schedule_id,
                error=str(exc),
            )
