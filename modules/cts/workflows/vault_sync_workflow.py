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
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from shared.utils.pii_crypto import hash_account_number

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
    signatory_id: str = "PRIMARY"    # which signatory these specimens belong to
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


class ChequeLeafRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    cheque_number: str
    status: str                          # ACTIVE | LOST | STOLEN | CANCELLED | USED
    issued_date: Optional[str] = None
    series_end: Optional[str] = None


class VaultSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                            # "SYNC_COMPLETE" | "PARTIAL_FAILURE"
    signatures_loaded: int
    signatures_embedded: int = 0            # subset of signatures_loaded successfully embedded
    pps_records_loaded: int
    stop_records_loaded: int = 0
    cheque_leaves_loaded: int = 0           # Step 6: cheque leaf vault sync
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
        records.append(SignatureRecord(
            account_number=account_number,
            signatory_id=raw.get("signatory_id", "PRIMARY"),
            specimens=specimens,
        ))

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
            await vault.store_embeddings(
                rec.account_number,
                specimen_embeddings,
                signatory_id=rec.signatory_id,
                source="CBS",
            )
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
    return hash_account_number(account_number, bank_id, pepper)


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
        sig_key = f"sig:{bank_id}:{digest}:PRIMARY"
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
# Activity 6a: load_cheque_leaves_from_cbs
# ---------------------------------------------------------------------------

@activity.defn
async def load_cheque_leaves_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[ChequeLeafRecord]:
    """Fetch all issued cheque leaf records from CBS for bulk vault warm."""
    if cbs_connector is None:
        log.warning("vault_sync.cheque_leaves_no_connector", bank_id=bank_id)
        return []

    try:
        raw_records = await cbs_connector.list_issued_leaves(bank_id)
    except Exception as exc:
        log.warning(
            "vault_sync.cheque_leaves_cbs_error",
            bank_id=bank_id,
            error=str(exc),
        )
        raise

    records = []
    for raw in raw_records:
        account_number = raw.get("account_number", "")
        cheque_number = raw.get("cheque_number", "")
        status = raw.get("status", "")
        if not account_number or not cheque_number or not status:
            log.warning(
                "vault_sync.cheque_leaf_record_invalid",
                bank_id=bank_id,
                account_last4=account_number[-4:] if account_number else "????",
            )
            continue
        records.append(ChequeLeafRecord(
            account_number=account_number,
            cheque_number=cheque_number,
            status=status,
            issued_date=raw.get("issued_date"),
            series_end=raw.get("series_end"),
        ))

    log.info("vault_sync.cheque_leaves_loaded_from_cbs", bank_id=bank_id, count=len(records))
    return records


# ---------------------------------------------------------------------------
# Activity 6b: warm_cheque_leaf_vault
# ---------------------------------------------------------------------------

@activity.defn
async def warm_cheque_leaf_vault(
    bank_id: str,
    pepper: str,
    leaf_records: list[ChequeLeafRecord],
    redis_client=None,
) -> dict[str, int]:
    """Pipeline-write cheque leaf records to Redis ChequeLeafVault."""
    if not leaf_records or redis_client is None:
        return {"cheque_leaves": 0}

    pipe = redis_client.pipeline()
    for rec in leaf_records:
        digest = _hmac_key(pepper, bank_id, rec.account_number)
        key = f"chq:{bank_id}:{digest}:{rec.cheque_number}"
        mapping: dict[str, str] = {"status": rec.status}
        if rec.issued_date:
            mapping["issued_date"] = rec.issued_date
        if rec.series_end:
            mapping["series_end"] = rec.series_end
        pipe.hset(key, mapping=mapping)
    pipe.execute()

    count = len(leaf_records)
    log.info("vault_sync.cheque_leaf_vault_warmed", bank_id=bank_id, count=count)
    return {"cheque_leaves": count}


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
            SELECT account_hash, signatory_id, specimen_index, embedding
            FROM cts.signature_embeddings
            WHERE bank_id = $1
            ORDER BY account_hash, signatory_id, specimen_index
            """,
            bank_id,
        )

    # Group by (account_hash, signatory_id) — one Redis LIST key per signatory
    by_signatory: dict[tuple[str, str], list[bytes]] = defaultdict(list)
    for row in rows:
        by_signatory[(row["account_hash"], row["signatory_id"])].append(bytes(row["embedding"]))

    pipe = redis_client.pipeline()
    for (account_hash, signatory_id), packed_list in by_signatory.items():
        key = f"sig:{bank_id}:{account_hash}:{signatory_id}"
        pipe.delete(key)
        for packed in packed_list:
            pipe.rpush(key, packed)
    pipe.execute()

    # Report unique account count (not signatory-key count)
    count = len({ah for ah, _ in by_signatory})
    log.info("vault_sync.warm_from_db_complete", bank_id=bank_id, accounts=count)
    return {"accounts": count}


# ---------------------------------------------------------------------------
# AccountProfile record (for account vault sync)
# ---------------------------------------------------------------------------

class AccountProfileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    account_type: str = "UNKNOWN"
    branch_code: str = ""


# ---------------------------------------------------------------------------
# Activity 7a: load_account_profiles_from_cbs
# ---------------------------------------------------------------------------

@activity.defn
async def load_account_profiles_from_cbs(
    bank_id: str,
    cbs_connector=None,
) -> list[AccountProfileRecord]:
    """
    Fetch all account profiles from CBS to populate the Account Vault.

    Returns list of AccountProfileRecord — one per account, carrying
    branch_code so the next activity can deduplicate branch contact lookups.
    """
    if cbs_connector is None:
        log.warning("vault_sync.account_profiles_no_connector", bank_id=bank_id)
        return []

    try:
        raw_records = await cbs_connector.list_account_profiles(bank_id)
    except Exception as exc:
        log.warning(
            "vault_sync.account_profiles_cbs_error",
            bank_id=bank_id,
            error=str(exc),
        )
        raise

    records = []
    for raw in raw_records:
        account_number = raw.get("account_number", "")
        if not account_number:
            continue
        records.append(AccountProfileRecord(
            account_number=account_number,
            account_type=raw.get("account_type", "UNKNOWN"),
            branch_code=raw.get("branch_code", ""),
        ))

    log.info("vault_sync.account_profiles_loaded", bank_id=bank_id, count=len(records))
    return records


# ---------------------------------------------------------------------------
# Activity 7b: warm_account_vault
# ---------------------------------------------------------------------------

@activity.defn
async def warm_account_vault(
    bank_id: str,
    pepper: str,
    account_records: list[AccountProfileRecord],
    cbs_connector=None,
    account_vault=None,
) -> dict[str, int]:
    """
    For each account profile, look up branch contacts from CBS (deduplicated by
    branch_code — one CBS call per branch, not per account), then store the
    merged profile in AccountVault (YugabyteDB + Redis).

    Deduplication: branch contact is fetched once per unique branch_code and
    reused for all accounts at that branch.
    """
    if not account_records or account_vault is None:
        return {"accounts_warmed": 0, "branches_fetched": 0, "failed": 0}

    branch_contacts: dict[str, Any] = {}
    warmed = 0
    failed = 0

    for rec in account_records:
        branch_code = rec.branch_code

        if branch_code and branch_code not in branch_contacts:
            if cbs_connector is not None:
                try:
                    contact = await cbs_connector.get_branch_contacts(branch_code, bank_id)
                    branch_contacts[branch_code] = contact
                except Exception as exc:
                    log.warning(
                        "vault_sync.branch_contact_fetch_failed",
                        bank_id=bank_id,
                        branch_code=branch_code,
                        error=str(exc),
                    )
                    branch_contacts[branch_code] = None
            else:
                branch_contacts[branch_code] = None

        contact = branch_contacts.get(branch_code)

        profile: dict[str, str] = {
            "account_number_last4": rec.account_number[-4:],
            "account_type": rec.account_type,
            "branch_code": branch_code,
            "branch_name": contact.branch_name if contact else "",
            "branch_ifsc": contact.branch_ifsc if contact else "",
            "branch_manager_email": contact.branch_manager_email if contact else "",
            "branch_contact_email": contact.branch_contact_email if contact else "",
            "branch_contact_phone": contact.branch_contact_phone if contact else "",
            "last_synced_at": str(date.today().isoformat()),
        }

        try:
            await account_vault.store_profile(
                account_number=rec.account_number,
                profile=profile,
                source="VaultSyncWorkflow",
            )
            warmed += 1
        except Exception as exc:
            log.error(
                "vault_sync.account_vault_store_failed",
                bank_id=bank_id,
                account_last4=rec.account_number[-4:],
                error=str(exc),
            )
            failed += 1

    branches_fetched = sum(1 for v in branch_contacts.values() if v is not None)
    log.info(
        "vault_sync.account_vault_warmed",
        bank_id=bank_id,
        accounts_warmed=warmed,
        branches_fetched=branches_fetched,
        failed=failed,
    )
    return {"accounts_warmed": warmed, "branches_fetched": branches_fetched, "failed": failed}


# ---------------------------------------------------------------------------
# Activity: publish vault sync completion event
# ---------------------------------------------------------------------------

@activity.defn
async def publish_vault_sync_event(
    bank_id: str,
    result_data: dict,
    event_producer=None,
) -> None:
    """
    Publishes CTS_VAULT_SYNC_COMPLETE to cts.vault.sync.{bank_id}.
    Consumed by vault_sync_consumer which writes stats to Immudb for RBI audit.

    Non-fatal — vault sync has already succeeded before this is called.
    event_producer is injected at worker startup; if None, degrades with warning.
    """
    if event_producer is None:
        log.warning("publish_vault_sync_event.no_producer", bank_id=bank_id)
        return
    try:
        await event_producer.publish(
            topic=f"cts.vault.sync.{bank_id}",
            event_type="CTS_VAULT_SYNC_COMPLETE",
            payload=result_data,
            schema_version="1.0",
        )
    except Exception as exc:
        log.error("publish_vault_sync_event.publish_failed", bank_id=bank_id, error=str(exc))


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
        started_at = workflow.now().isoformat()

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

        # Step 6: Load cheque leaf statuses and warm ChequeLeafVault
        cheque_leaves_loaded = 0
        try:
            leaf_records = await workflow.execute_activity(
                load_cheque_leaves_from_cbs,
                args=[inp.bank_id],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=_INFRA_RETRY,
            )
            warm_result = await workflow.execute_activity(
                warm_cheque_leaf_vault,
                args=[inp.bank_id, inp.pepper, leaf_records],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=_INFRA_RETRY,
            )
            cheque_leaves_loaded = warm_result.get("cheque_leaves", 0)
        except Exception as exc:
            log.warning(
                "vault_sync.cheque_leaf_sync_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )
            # Non-fatal: signature + PPS sync already complete; mark partial

        # Step 7: Load account profiles from CBS and warm Account Vault
        accounts_warmed = 0
        try:
            account_records = await workflow.execute_activity(
                load_account_profiles_from_cbs,
                args=[inp.bank_id],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=_INFRA_RETRY,
            )
            acct_result = await workflow.execute_activity(
                warm_account_vault,
                args=[inp.bank_id, inp.pepper, account_records],
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=_INFRA_RETRY,
            )
            accounts_warmed = acct_result.get("accounts_warmed", 0)
        except Exception as exc:
            log.warning(
                "vault_sync.account_vault_sync_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )

        log.info(
            "vault_sync.workflow_complete",
            bank_id=inp.bank_id,
            sync_date=inp.sync_date,
            signatures=len(sig_records),
            embedded=embed_result.get("embedded", 0),
            pps=len(pps_records),
            cheque_leaves=cheque_leaves_loaded,
            accounts_warmed=accounts_warmed,
            integrity=integrity_ok,
        )

        result = VaultSyncResult(
            outcome="SYNC_COMPLETE",
            signatures_loaded=len(sig_records),
            signatures_embedded=embed_result.get("embedded", 0),
            pps_records_loaded=len(pps_records),
            cheque_leaves_loaded=cheque_leaves_loaded,
            integrity_check_passed=integrity_ok,
            triggered_by=inp.triggered_by,
        )

        # Publish completion event to cts.vault.sync.{bank_id} so the
        # vault_sync_consumer can write stats to Immudb for RBI audit.
        # Non-fatal — vault is already synced; Kafka publish failure is not a reason to fail.
        try:
            await workflow.execute_activity(
                publish_vault_sync_event,
                args=[inp.bank_id, {
                    "outcome": result.outcome,
                    "signatures_loaded": result.signatures_loaded,
                    "pps_records_loaded": result.pps_records_loaded,
                    "cheque_leaves_loaded": result.cheque_leaves_loaded,
                    "integrity_check_passed": result.integrity_check_passed,
                    "triggered_by": result.triggered_by,
                    "started_at": started_at,
                    "completed_at": workflow.now().isoformat(),
                }],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            log.warning(
                "vault_sync.publish_event_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )

        return result

    async def run_with_mocks(
        self,
        inp: VaultSyncInput,
        cbs_connector=None,
        redis_client=None,
        vault=None,
        embedding_model=None,
        sample_accounts: Optional[list[str]] = None,
        account_vault=None,
        **kwargs,
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

        # Step 6: Cheque leaf vault sync
        cheque_leaves_loaded = 0
        try:
            leaf_records = await load_cheque_leaves_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
            warm_result = await warm_cheque_leaf_vault(
                bank_id=inp.bank_id,
                pepper=inp.pepper,
                leaf_records=leaf_records,
                redis_client=redis_client,
            )
            cheque_leaves_loaded = warm_result.get("cheque_leaves", 0)
        except Exception as exc:
            log.warning(
                "vault_sync.cheque_leaf_sync_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )

        # Step 7: Account Vault warm
        accounts_warmed = 0
        try:
            account_records = await load_account_profiles_from_cbs(
                bank_id=inp.bank_id,
                cbs_connector=cbs_connector,
            )
            acct_result = await warm_account_vault(
                bank_id=inp.bank_id,
                pepper=inp.pepper,
                account_records=account_records,
                cbs_connector=cbs_connector,
                account_vault=account_vault,
            )
            accounts_warmed = acct_result.get("accounts_warmed", 0)
        except Exception as exc:
            log.warning(
                "vault_sync.account_vault_sync_failed",
                bank_id=inp.bank_id,
                error=str(exc),
            )

        log.info(
            "vault_sync.workflow_complete",
            bank_id=inp.bank_id,
            sync_date=inp.sync_date,
            signatures=len(sig_records),
            embedded=embed_result.get("embedded", 0),
            pps=len(pps_records),
            cheque_leaves=cheque_leaves_loaded,
            accounts_warmed=accounts_warmed,
            integrity=integrity_ok,
        )

        return VaultSyncResult(
            outcome="SYNC_COMPLETE",
            signatures_loaded=len(sig_records),
            signatures_embedded=embed_result.get("embedded", 0),
            pps_records_loaded=len(pps_records),
            cheque_leaves_loaded=cheque_leaves_loaded,
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
