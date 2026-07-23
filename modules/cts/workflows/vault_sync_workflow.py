"""
VaultSyncWorkflow — syncs CBS account data into Redis + YugabyteDB vaults.

Triggered: CBS event stream OR schedule (daily at 6AM).
Workflow ID: cts-vaultsync-{bank_id}-{date}  (idempotent per bank per day).

Activities:
  1. load_signatures_from_cbs  — pull all signature specimens from CBS (raw image bytes)
  2. embed_and_store_signatures — embed each raw specimen → store in vault (YugabyteDB + Redis)
  3. load_pps_from_cbs         — pull active positive-pay records
  4. warm_redis_vault          — pipeline-write PPS records to Redis
  5. verify_vault_integrity    — sample N random keys, assert Redis has them

Cold-restart recovery (Redis only — embeddings already in YugabyteDB):
  warm_redis_from_db — reads cts.signature_embeddings → pipeline-writes packed float32 to Redis.
  No embedding model required. Wired by DeltaVaultSyncWorkflow or a dedicated recovery job.

Exactly-once: Temporal workflow ID deduplicates concurrent trigger events.
"""
import base64
import hashlib
import hmac
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_INFRA_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class VaultSyncInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    pepper: str
    sync_date: str = ""
    triggered_by: str = "SCHEDULED"


class SignatureRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    specimens: list[bytes]

    @field_serializer("specimens")
    def _serialize_specimens(self, specimens: list[bytes]) -> list[str]:
        return [base64.b64encode(s).decode("ascii") for s in specimens]

    @field_validator("specimens", mode="before")
    @classmethod
    def _deserialize_specimens(cls, value: Any) -> Any:
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return [base64.b64decode(item) for item in value]
        return value


class PPSRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    cheque_series_start: str
    amount: float
    payee: str
    ttl_seconds: Optional[int] = None


class VaultSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                            # "SYNC_COMPLETE" | "PARTIAL_FAILURE"
    signatures_loaded: int
    signatures_embedded: int = 0            # subset of signatures_loaded successfully embedded
    pps_records_loaded: int
    stop_records_loaded: int = 0
    integrity_check_passed: bool
    failed_accounts: list[str] = []
    triggered_by: str = "SCHEDULED"


# ---------------------------------------------------------------------------
# Activity 1: load_signatures_from_cbs
# ---------------------------------------------------------------------------

@activity.defn
async def load_signatures_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[SignatureRecord]:
    """Fetch all signature specimens from CBS. Returns raw image bytes per account."""
    raw_records = await cbs_connector.list_signature_specimens(bank_id)

    records = []
    for raw in raw_records:
        account_number = raw.get("account_number", "")
        specimens_raw = raw.get("specimens", [])
        if not account_number or not specimens_raw:
            log.warning(
                "vault_sync.invalid_signature_record",
                bank_id=bank_id,
                account_last4=account_number[-4:] if account_number else "????",
            )
            continue
        specimens = [s if isinstance(s, bytes) else s.encode() for s in specimens_raw]
        records.append(SignatureRecord(account_number=account_number, specimens=specimens))

    log.info("vault_sync.signatures_loaded_from_cbs", bank_id=bank_id, count=len(records))
    return records


# ---------------------------------------------------------------------------
# Activity 2: embed_and_store_signatures (NEW)
# ---------------------------------------------------------------------------

@activity.defn
async def embed_and_store_signatures(
    bank_id: str,
    signature_records: list[SignatureRecord],
    vault=None,
    embedding_model=None,
) -> dict[str, int]:
    """
    Embed CBS signature specimens and store in vault (YugabyteDB + Redis).

    For each SignatureRecord: embed each raw specimen via embedding_model →
    call vault.store_embeddings() which durably writes YugabyteDB and then
    warms Redis. No re-embedding is needed on Redis cold restart — warm from
    YugabyteDB directly via warm_redis_from_db.

    Returns:
        {"embedded": <accounts successfully embedded>, "failed": <accounts skipped>}
    """
    if not signature_records:
        return {"embedded": 0, "failed": 0}

    if embedding_model is None or vault is None:
        log.warning(
            "vault_sync.embed_skipped_no_model_or_vault",
            bank_id=bank_id,
            record_count=len(signature_records),
        )
        return {"embedded": 0, "failed": len(signature_records)}

    from shared.ai.signature_embedding import EmbeddingModelUnavailableError

    embedded = 0
    failed = 0

    for rec in signature_records:
        specimen_embeddings: list[list[float]] = []
        for raw in rec.specimens:
            try:
                emb = await embedding_model.embed(raw, bank_id=bank_id)
                specimen_embeddings.append(emb)
            except (EmbeddingModelUnavailableError, Exception) as exc:
                log.warning(
                    "vault_sync.specimen_embed_failed",
                    bank_id=bank_id,
                    account_last4=rec.account_number[-4:],
                    error=str(exc),
                )

        if not specimen_embeddings:
            failed += 1
            continue

        try:
            await vault.store_embeddings(rec.account_number, specimen_embeddings, source="CBS")
            embedded += 1
        except Exception as exc:
            log.error(
                "vault_sync.store_embeddings_failed",
                bank_id=bank_id,
                account_last4=rec.account_number[-4:],
                error=str(exc),
            )
            failed += 1

    log.info(
        "vault_sync.embed_complete",
        bank_id=bank_id,
        embedded=embedded,
        failed=failed,
    )
    return {"embedded": embedded, "failed": failed}


# ---------------------------------------------------------------------------
# Activity 3: load_pps_from_cbs
# ---------------------------------------------------------------------------

@activity.defn
async def load_pps_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[PPSRecord]:
    """Fetch all active Positive Pay records from CBS."""
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

    log.info("vault_sync.pps_loaded_from_cbs", bank_id=bank_id, count=len(records))
    return records


# ---------------------------------------------------------------------------
# Activity 4: warm_redis_vault (PPS only)
# ---------------------------------------------------------------------------

def _hmac_key(pepper: str, bank_id: str, account_number: str) -> str:
    return hmac.new(
        pepper.encode(),
        f"{bank_id}:{account_number}".encode(),
        hashlib.sha256,
    ).hexdigest()


@activity.defn
async def warm_redis_vault(
    bank_id: str,
    pepper: str,
    pps_records: list[PPSRecord],
    redis_client=None,
) -> dict[str, int]:
    """
    Pipeline-write PPS records to Redis.

    Signature warm is no longer done here — embed_and_store_signatures handles
    that by writing through vault.store_embeddings() which writes packed float32
    embeddings to Redis directly.  This activity only handles PPS.
    """
    pps_count = 0

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

    log.info("vault_sync.pps_warm_complete", bank_id=bank_id, pps_records=pps_count)
    return {"pps_records": pps_count}


# ---------------------------------------------------------------------------
# Activity 5: verify_vault_integrity
# ---------------------------------------------------------------------------

@activity.defn
async def verify_vault_integrity(
    bank_id: str,
    pepper: str,
    sample_accounts: list[str],
    redis_client=None,
) -> bool:
    """Spot-check N random accounts to confirm Redis has their signature vault entries."""
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
            log.warning("vault_sync.integrity_miss", bank_id=bank_id, account_last4=account_number[-4:])
            missing.append(account_number[-4:])

    passed = len(missing) == 0
    log.info("vault_sync.integrity_check", bank_id=bank_id, sampled=len(sample_accounts),
             missing=len(missing), passed=passed)
    return passed


# ---------------------------------------------------------------------------
# Recovery activity: warm_redis_from_db (cold-restart Redis warm)
# ---------------------------------------------------------------------------

@activity.defn
async def warm_redis_from_db(
    bank_id: str,
    db_pool=None,
    redis_client=None,
) -> dict[str, int]:
    """
    Bulk-reads cts.signature_embeddings from YugabyteDB and pipeline-writes
    packed float32 embeddings to Redis.  No embedding model required.

    Used when Redis restarts cold — avoids re-embedding 5M+ customers from CBS.
    Wired by DeltaVaultSyncWorkflow or a dedicated cold-start recovery job.
    """
    if db_pool is None or redis_client is None:
        log.warning("vault_sync.warm_from_db_skipped", bank_id=bank_id,
                    reason="no_db_pool_or_redis")
        return {"accounts": 0}

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT account_hash, specimen_index, embedding
            FROM cts.signature_embeddings
            WHERE bank_id = $1
            ORDER BY account_hash, specimen_index
            """,
            bank_id,
        )

    by_account: dict[str, list[bytes]] = defaultdict(list)
    for row in rows:
        by_account[row["account_hash"]].append(bytes(row["embedding"]))

    pipe = redis_client.pipeline()
    for account_hash, packed_list in by_account.items():
        key = f"sig:{bank_id}:{account_hash}"
        pipe.delete(key)
        for packed in packed_list:
            pipe.rpush(key, packed)
    pipe.execute()

    count = len(by_account)
    log.info("vault_sync.warm_from_db_complete", bank_id=bank_id, accounts=count)
    return {"accounts": count}


# ---------------------------------------------------------------------------
# VaultSyncWorkflow — orchestrates 5 activities
# ---------------------------------------------------------------------------

@workflow.defn
class VaultSyncWorkflow:
    def workflow_id(self, bank_id: str, sync_date: str) -> str:
        return f"cts-vaultsync-{bank_id}-{sync_date}"

    @workflow.run
    async def run(self, inp: VaultSyncInput) -> VaultSyncResult:
        """
        Temporal @workflow.run. Activities receive vault/embedding_model/redis_client
        via worker-level DI (same precedent as other activities in this codebase).
        Args passed here are only serialisable Temporal payloads.
        """
        # Step 1: Load raw specimen images from CBS
        try:
            sig_records = await workflow.execute_activity(
                load_signatures_from_cbs,
                args=[inp.bank_id],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=_INFRA_RETRY,
            )
        except Exception as exc:
            log.error("vault_sync.signature_load_failed", bank_id=inp.bank_id, error=str(exc))
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=0,
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["SIGNATURE_LOAD_FAILED"],
                triggered_by=inp.triggered_by,
            )

        # Step 2: Embed specimens and store in vault (YugabyteDB + Redis)
        embed_result = await workflow.execute_activity(
            embed_and_store_signatures,
            args=[inp.bank_id, sig_records],
            start_to_close_timeout=timedelta(seconds=600),
            retry_policy=_INFRA_RETRY,
        )

        # Step 3: Load PPS records from CBS
        try:
            pps_records = await workflow.execute_activity(
                load_pps_from_cbs,
                args=[inp.bank_id],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=_INFRA_RETRY,
            )
        except Exception as exc:
            log.error("vault_sync.pps_load_failed", bank_id=inp.bank_id, error=str(exc))
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=len(sig_records),
                signatures_embedded=embed_result.get("embedded", 0),
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["PPS_LOAD_FAILED"],
                triggered_by=inp.triggered_by,
            )

        # Step 4: Warm Redis with PPS records
        await workflow.execute_activity(
            warm_redis_vault,
            args=[inp.bank_id, inp.pepper, pps_records],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_INFRA_RETRY,
        )

        # Step 5: Integrity check on signature keys
        accounts_to_sample = [r.account_number for r in sig_records[:10]]
        integrity_ok = await workflow.execute_activity(
            verify_vault_integrity,
            args=[inp.bank_id, inp.pepper, accounts_to_sample],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_INFRA_RETRY,
        )

        log.info(
            "vault_sync.workflow_complete",
            bank_id=inp.bank_id,
            sync_date=inp.sync_date,
            signatures=len(sig_records),
            embedded=embed_result.get("embedded", 0),
            pps=len(pps_records),
            integrity=integrity_ok,
        )

        return VaultSyncResult(
            outcome="SYNC_COMPLETE",
            signatures_loaded=len(sig_records),
            signatures_embedded=embed_result.get("embedded", 0),
            pps_records_loaded=len(pps_records),
            integrity_check_passed=integrity_ok,
            triggered_by=inp.triggered_by,
        )

    async def run_with_mocks(
        self,
        inp: VaultSyncInput,
        cbs_connector=None,
        redis_client=None,
        vault=None,
        embedding_model=None,
        sample_accounts: Optional[list[str]] = None,
    ) -> VaultSyncResult:
        """Testable orchestration — same logic as run(), direct Python calls."""
        # Step 1
        try:
            sig_records = await load_signatures_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
        except Exception as exc:
            log.error("vault_sync.signature_load_failed", bank_id=inp.bank_id, error=str(exc))
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=0,
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["SIGNATURE_LOAD_FAILED"],
            )

        # Step 2
        embed_result = await embed_and_store_signatures(
            bank_id=inp.bank_id,
            signature_records=sig_records,
            vault=vault,
            embedding_model=embedding_model,
        )

        # Step 3
        try:
            pps_records = await load_pps_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
        except Exception as exc:
            log.error("vault_sync.pps_load_failed", bank_id=inp.bank_id, error=str(exc))
            return VaultSyncResult(
                outcome="PARTIAL_FAILURE",
                signatures_loaded=len(sig_records),
                signatures_embedded=embed_result.get("embedded", 0),
                pps_records_loaded=0,
                integrity_check_passed=False,
                failed_accounts=["PPS_LOAD_FAILED"],
            )

        # Step 4 — PPS only
        await warm_redis_vault(
            bank_id=inp.bank_id,
            pepper=inp.pepper,
            pps_records=pps_records,
            redis_client=redis_client,
        )

        # Step 5
        accounts_to_sample = sample_accounts if sample_accounts is not None else [
            r.account_number for r in sig_records[:10]
        ]
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
            embedded=embed_result.get("embedded", 0),
            pps=len(pps_records),
            integrity=integrity_ok,
        )

        return VaultSyncResult(
            outcome="SYNC_COMPLETE",
            signatures_loaded=len(sig_records),
            signatures_embedded=embed_result.get("embedded", 0),
            pps_records_loaded=len(pps_records),
            integrity_check_passed=integrity_ok,
            triggered_by=inp.triggered_by,
        )


# ---------------------------------------------------------------------------
# Temporal Schedule — register once per bank at worker startup
# ---------------------------------------------------------------------------

async def register_vault_sync_schedule(temporal_client, bank_id: str) -> None:
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleSpec,
    )
    from temporalio.common import RetryPolicy
    from shared.config.config_service import config_service

    schedule_id = f"cts-vaultsync-schedule-{bank_id}"
    pepper = await config_service.get_secret("pii_hash_pepper")

    try:
        await temporal_client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    VaultSyncWorkflow.run,
                    VaultSyncInput(bank_id=bank_id, pepper=pepper, triggered_by="SCHEDULED"),
                    id=f"cts-vaultsync-{bank_id}-scheduled",
                    task_queue=f"cts-processing-{bank_id}",
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(minutes=5),
                    ),
                ),
                spec=ScheduleSpec(
                    cron_expressions=["0 7 * * *"],
                ),
            ),
        )
        log.info("vault_sync.schedule_registered", bank_id=bank_id, schedule_id=schedule_id)
    except Exception as exc:
        if "already exists" in str(exc).lower() or "already registered" in str(exc).lower():
            log.info("vault_sync.schedule_exists", bank_id=bank_id, schedule_id=schedule_id)
        else:
            log.warning(
                "vault_sync.schedule_register_failed",
                bank_id=bank_id,
                schedule_id=schedule_id,
                error=str(exc),
            )
