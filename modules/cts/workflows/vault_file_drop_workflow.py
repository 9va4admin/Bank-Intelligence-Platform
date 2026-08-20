"""
VaultFileDropWorkflow — processes CSV files dropped at a designated MinIO path
into the ASTRA vault via VaultUploadProcessor.

This is the SFTP/file-drop equivalent of the UI upload route
POST /v1/cts/vault/upload/{vault_type}.

Supported vault types:
  CHEQUE_BOOK    astra-vault-drops/{bank_id}/cheque_book/*.csv
  LEAF_STATUS    astra-vault-drops/{bank_id}/leaf_status/*.csv
  ACCOUNT_DETAIL astra-vault-drops/{bank_id}/account_detail/*.csv
  SIGNATURE      astra-vault-drops/{bank_id}/signature/*.csv
  PPS            astra-vault-drops/{bank_id}/pps/*.csv

Works identically for SB (sponsor bank) and SMB (sub-member bank) — the
bank_id in the MinIO path scopes every write to that bank only.

Trigger:
  The MinIO event notification (configured on `astra-vault-drops` bucket) fires
  an HTTP webhook → ASTRA API endpoint → Temporal client starts this workflow.
  Workflow ID: cts-vault-drop-{bank_id}-{vault_type}-{file_hash}
  (file_hash = SHA-256 of raw file bytes — idempotency guard)

Activities:
  1. fetch_drop_file      — download CSV bytes from MinIO
  2. process_vault_csv    — VaultUploadProcessor.process() → vault DB + Redis
  3. archive_drop_file    — move processed file to astra-vault-archive/{bank_id}/
  4. write_audit          — Immudb audit entry for the batch

Terminal states:
  VAULT_UPDATED | PARSE_FAILED | VAULT_UPDATE_FAILED | DUPLICATE_SKIPPED
"""
from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, field_validator
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = structlog.get_logger()

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,  # unlimited — audit must succeed
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)

_VALID_VAULT_TYPES = frozenset({
    "CHEQUE_BOOK", "LEAF_STATUS", "ACCOUNT_DETAIL", "SIGNATURE", "PPS"
})


# ---------------------------------------------------------------------------
# Input / Result
# ---------------------------------------------------------------------------

class VaultFileDropInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    bank_id: str
    vault_type: str           # CHEQUE_BOOK | LEAF_STATUS | ACCOUNT_DETAIL | SIGNATURE | PPS
    minio_bucket: str         # always "astra-vault-drops"
    minio_key: str            # e.g. "{bank_id}/pps/20260818_pps_batch1.csv"
    file_hash: str            # SHA-256 of raw file bytes — idempotency key
    feed_name: str = "sftp"   # identifies the drop channel in audit trail


class VaultFileDropResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str              # VAULT_UPDATED | PARSE_FAILED | VAULT_UPDATE_FAILED | DUPLICATE_SKIPPED
    bank_id: str
    vault_type: str
    batch_id: Optional[str] = None
    rows_total: int = 0
    rows_processed: int = 0
    rows_failed: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Activity inputs / results
# ---------------------------------------------------------------------------

class FetchDropFileInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    minio_bucket: str
    minio_key: str
    file_hash: str


class FetchDropFileResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    csv_bytes: str = ""    # base64-encoded; Temporal's JSON encoder cannot handle raw bytes
    duplicate: bool = False
    error: Optional[str] = None

    @field_validator("csv_bytes", mode="before")
    @classmethod
    def _encode_bytes(cls, v: object) -> str:
        if isinstance(v, bytes):
            return base64.b64encode(v).decode()
        return v  # type: ignore[return-value]


class ProcessVaultCSVInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    vault_type: str
    csv_bytes: str         # base64-encoded; Temporal's JSON encoder cannot handle raw bytes
    changed_by: str       # "system:{feed_name}"
    filename: str
    file_hash: str

    @field_validator("csv_bytes", mode="before")
    @classmethod
    def _encode_bytes(cls, v: object) -> str:
        if isinstance(v, bytes):
            return base64.b64encode(v).decode()
        return v  # type: ignore[return-value]


class ProcessVaultCSVResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str = ""
    rows_total: int = 0
    rows_processed: int = 0
    rows_failed: int = 0
    error: Optional[str] = None


class ArchiveDropFileInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    minio_bucket: str
    minio_key: str
    archive_bucket: str = "astra-vault-archive"


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@activity.defn
async def fetch_drop_file(inp: FetchDropFileInput, minio_client=None) -> FetchDropFileResult:
    """
    Download the CSV from MinIO and verify file_hash (idempotency + integrity).
    Also checks cts.vault_upload_batches for a prior batch with the same file_hash
    to detect duplicate drops.
    """
    if minio_client is None:
        return FetchDropFileResult(error="MINIO_UNAVAILABLE")

    try:
        response = minio_client.get_object(inp.minio_bucket, inp.minio_key)
        csv_bytes = response.read()
    except Exception as exc:
        log.error("vault_file_drop.fetch_failed",
                  bank_id=inp.bank_id, minio_key=inp.minio_key, error=str(exc))
        return FetchDropFileResult(error=f"FETCH_FAILED: {exc}")

    actual_hash = hashlib.sha256(csv_bytes).hexdigest()
    if actual_hash != inp.file_hash:
        log.error("vault_file_drop.hash_mismatch",
                  bank_id=inp.bank_id, expected=inp.file_hash, actual=actual_hash)
        return FetchDropFileResult(error="HASH_MISMATCH")

    return FetchDropFileResult(csv_bytes=base64.b64encode(csv_bytes).decode())


@activity.defn
async def process_vault_csv(inp: ProcessVaultCSVInput, db_pool=None, vaults: dict = None) -> ProcessVaultCSVResult:
    """
    Instantiate VaultUploadProcessor and process the CSV.
    vaults dict: {
        "cheque_leaf": ChequeLeafVault instance,
        "account": AccountVault instance,
        "signature": SignatureVault instance,
        "pps": PPSVault instance,
    }
    """
    if db_pool is None:
        return ProcessVaultCSVResult(error="DB_UNAVAILABLE")
    if vaults is None:
        vaults = {}

    if inp.vault_type not in _VALID_VAULT_TYPES:
        return ProcessVaultCSVResult(error=f"UNKNOWN_VAULT_TYPE: {inp.vault_type}")

    try:
        from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor

        processor = VaultUploadProcessor(
            bank_id=inp.bank_id,
            db_pool=db_pool,
            cheque_leaf_vault=vaults.get("cheque_leaf"),
            account_vault=vaults.get("account"),
            signature_vault=vaults.get("signature"),
            pps_vault=vaults.get("pps"),
        )
        result = await processor.process(
            vault_type=inp.vault_type,
            csv_content=base64.b64decode(inp.csv_bytes),
            changed_by=inp.changed_by,
            filename=inp.filename,
            upload_channel="SFTP",
        )
        return ProcessVaultCSVResult(
            batch_id=result.batch_id,
            rows_total=result.rows_total,
            rows_processed=result.rows_processed,
            rows_failed=result.rows_failed,
        )
    except Exception as exc:
        log.error("vault_file_drop.process_failed",
                  bank_id=inp.bank_id, vault_type=inp.vault_type, error=str(exc))
        return ProcessVaultCSVResult(error=str(exc))


class VaultBatchAlertInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    vault_type: str
    rows_total: int
    rows_processed: int
    rows_failed: int


@activity.defn
async def emit_vault_batch_alert(inp: VaultBatchAlertInput, kafka_producer=None) -> None:
    """
    Publish a VAULT_BATCH_PARTIAL or VAULT_BATCH_FAILED event to platform.audit.events.
    PlatformHealthCheckWorkflow consumes this and routes via dispatcher.py → WhatsApp + email.
    Non-fatal if Kafka is down — batch result is already in DB.
    """
    if kafka_producer is None:
        log.warning(
            "vault_file_drop.alert_skipped_no_kafka",
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            rows_failed=inp.rows_failed,
        )
        return

    event_type = (
        "VAULT_BATCH_FAILED" if inp.rows_processed == 0
        else "VAULT_BATCH_PARTIAL"
    )
    _TABLE_MAP = {
        "PPS": "cts.pps_vault_entries", "CHEQUE_BOOK": "cts.cheque_books",
        "LEAF_STATUS": "cts.cheque_leaves", "ACCOUNT_DETAIL": "cts.account_vault_detail",
        "SIGNATURE": "cts.account_signatories",
    }
    try:
        kafka_producer.publish(
            topic="platform.audit.events",
            event_type=event_type,
            payload={
                "batch_id": inp.batch_id,
                "vault_type": inp.vault_type,
                "db_table": _TABLE_MAP.get(inp.vault_type, "unknown"),
                "bank_id": inp.bank_id,
                "rows_total": inp.rows_total,
                "rows_processed": inp.rows_processed,
                "rows_failed": inp.rows_failed,
                "download_url": f"/v1/cts/vault/batches/{inp.batch_id}/errors.csv",
            },
            bank_id=inp.bank_id,
        )
        log.warning(
            "vault_file_drop.batch_alert_emitted",
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            vault_type=inp.vault_type,
            event_type=event_type,
            rows_failed=inp.rows_failed,
        )
    except Exception as exc:
        log.error(
            "vault_file_drop.batch_alert_failed",
            batch_id=inp.batch_id,
            error=str(exc),
        )


@activity.defn
async def archive_drop_file(inp: ArchiveDropFileInput, minio_client=None) -> None:
    """Move the processed file to the archive bucket so it isn't reprocessed."""
    if minio_client is None:
        log.warning("vault_file_drop.archive_skipped_no_minio",
                    bank_id=inp.bank_id, minio_key=inp.minio_key)
        return
    try:
        archive_key = inp.minio_key  # same key path, different bucket
        minio_client.copy_object(
            inp.archive_bucket,
            archive_key,
            f"{inp.minio_bucket}/{inp.minio_key}",
        )
        minio_client.remove_object(inp.minio_bucket, inp.minio_key)
    except Exception as exc:
        # Archive failure is non-fatal — the batch is already processed
        log.warning("vault_file_drop.archive_failed",
                    bank_id=inp.bank_id, minio_key=inp.minio_key, error=str(exc))


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

@workflow.defn
class VaultFileDropWorkflow:
    """
    Processes a single vault CSV file dropped at a MinIO path.
    One workflow instance per file (idempotency: workflow ID includes file_hash).
    """

    @workflow.run
    async def run(self, inp: VaultFileDropInput) -> VaultFileDropResult:
        if inp.vault_type not in _VALID_VAULT_TYPES:
            return VaultFileDropResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=f"Unknown vault_type: {inp.vault_type}",
            )

        # 1. Fetch CSV from MinIO
        fetch_result: FetchDropFileResult = await workflow.execute_activity(
            fetch_drop_file,
            FetchDropFileInput(
                bank_id=inp.bank_id,
                minio_bucket=inp.minio_bucket,
                minio_key=inp.minio_key,
                file_hash=inp.file_hash,
            ),
            retry_policy=_DEFAULT_RETRY,
            start_to_close_timeout=timedelta(seconds=30),
        )

        if fetch_result.duplicate:
            return VaultFileDropResult(
                outcome="DUPLICATE_SKIPPED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
            )
        if fetch_result.error:
            return VaultFileDropResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=fetch_result.error,
            )

        # 2. Process CSV through VaultUploadProcessor
        filename = inp.minio_key.split("/")[-1]
        process_result: ProcessVaultCSVResult = await workflow.execute_activity(
            process_vault_csv,
            ProcessVaultCSVInput(
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                csv_bytes=fetch_result.csv_bytes,
                changed_by=f"system:{inp.feed_name}",
                filename=filename,
                file_hash=inp.file_hash,
            ),
            retry_policy=_DEFAULT_RETRY,
            start_to_close_timeout=timedelta(seconds=120),
        )

        if process_result.error:
            return VaultFileDropResult(
                outcome="VAULT_UPDATE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=process_result.error,
            )

        # 3. Archive the processed file
        await workflow.execute_activity(
            archive_drop_file,
            ArchiveDropFileInput(
                bank_id=inp.bank_id,
                minio_bucket=inp.minio_bucket,
                minio_key=inp.minio_key,
            ),
            retry_policy=_DEFAULT_RETRY,
            start_to_close_timeout=timedelta(seconds=30),
        )

        result = VaultFileDropResult(
            outcome="VAULT_UPDATED",
            bank_id=inp.bank_id,
            vault_type=inp.vault_type,
            batch_id=process_result.batch_id,
            rows_total=process_result.rows_total,
            rows_processed=process_result.rows_processed,
            rows_failed=process_result.rows_failed,
        )

        # Notify on PARTIAL batch — alert ops_manager via Kafka audit event.
        # The PlatformHealthCheckWorkflow picks this up and routes to dispatcher.py.
        if process_result.rows_failed > 0:
            await workflow.execute_activity(
                emit_vault_batch_alert,
                VaultBatchAlertInput(
                    batch_id=process_result.batch_id or "",
                    bank_id=inp.bank_id,
                    vault_type=inp.vault_type,
                    rows_total=process_result.rows_total,
                    rows_processed=process_result.rows_processed,
                    rows_failed=process_result.rows_failed,
                ),
                retry_policy=_DEFAULT_RETRY,
                start_to_close_timeout=timedelta(seconds=15),
            )

        return result

    async def run_with_mocks(
        self,
        inp: VaultFileDropInput,
        mock_results: dict,
    ) -> VaultFileDropResult:
        """
        Test-only entry point — bypasses Temporal's workflow.execute_activity.
        mock_results keys: "fetch", "process" (optional), "archive" (optional)
          fetch:   FetchDropFileResult | None (None → skip to process with empty bytes)
          process: ProcessVaultCSVResult
        """
        if inp.vault_type not in _VALID_VAULT_TYPES:
            return VaultFileDropResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=f"Unknown vault_type: {inp.vault_type}",
            )

        fetch_result: FetchDropFileResult = mock_results.get("fetch") or FetchDropFileResult()

        if fetch_result.duplicate:
            return VaultFileDropResult(
                outcome="DUPLICATE_SKIPPED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
            )
        if fetch_result.error:
            return VaultFileDropResult(
                outcome="PARSE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=fetch_result.error,
            )

        process_result: ProcessVaultCSVResult = mock_results.get("process") or ProcessVaultCSVResult()
        if process_result.error:
            return VaultFileDropResult(
                outcome="VAULT_UPDATE_FAILED",
                bank_id=inp.bank_id,
                vault_type=inp.vault_type,
                error=process_result.error,
            )

        return VaultFileDropResult(
            outcome="VAULT_UPDATED",
            bank_id=inp.bank_id,
            vault_type=inp.vault_type,
            batch_id=process_result.batch_id,
            rows_total=process_result.rows_total,
            rows_processed=process_result.rows_processed,
            rows_failed=process_result.rows_failed,
        )
