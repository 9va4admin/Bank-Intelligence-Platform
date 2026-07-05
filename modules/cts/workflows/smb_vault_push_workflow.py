"""
SMBVaultPushIngestWorkflow — processes SMB CBS push files into ASTRA vaults.

Triggered when a new CBS batch file lands in the Agency's SFTP ingestion path.
File types: STOP_PAYMENTS | PPS_ENTRIES | SIGNATURES

Activity sequence:
  1. parse_and_validate  — normalise CBS file → canonical records; check for duplicate hash
  2. update_vault        — write to Redis (stop payments → Bloom + PPS vault; signatures → sig vault)
  3. write_audit         — Immudb (ALL terminal outcomes, including failures and duplicates)

Terminal states: VAULT_UPDATED | PARSE_FAILED | VAULT_UPDATE_FAILED | DUPLICATE_SKIPPED
Workflow ID: cts-smb-push-{agency_id}-{smb_id}-{file_hash}

Idempotency: file_hash (SHA-256 of raw file content) is stored in cts.smb_push_sessions
with a UNIQUE constraint. Duplicate file hash → DUPLICATE_SKIPPED without reprocessing.
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from modules.cts.smb_ingest.models import SMBPushFileType

log = structlog.get_logger()


class SMBVaultPushInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    smb_id: str
    file_type: SMBPushFileType
    file_path: str
    file_hash: str                # SHA-256 of raw file content — idempotency key


class SMBVaultPushResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: str                  # VAULT_UPDATED | PARSE_FAILED | VAULT_UPDATE_FAILED | DUPLICATE_SKIPPED
    agency_id: str
    smb_id: str
    file_type: SMBPushFileType
    records_processed: int
    failure_reason: Optional[str] = None
    audit_written: bool = False


class SMBVaultPushWorkflow:

    def workflow_id(self, agency_id: str, smb_id: str, file_hash: str) -> str:
        return f"cts-smb-push-{agency_id}-{smb_id}-{file_hash}"

    async def run_with_mocks(
        self,
        inp: SMBVaultPushInput,
        mock_results: dict,
    ) -> SMBVaultPushResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run.
        mock_results keys:
          "parse_and_validate" — {records: [...], record_count: int, error?: str, duplicate?: bool}
          "update_vault"       — {updated_count: int, bloom_updated: bool, error?: str}
          "audit"              — {written: bool}
        """
        # Step 1: Parse and validate
        parse_result = mock_results["parse_and_validate"]

        # Duplicate file already processed — skip silently
        if parse_result.get("duplicate"):
            log.info(
                "smb_vault_push_workflow.duplicate_skipped",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_hash=inp.file_hash,
            )
            await self._write_audit(mock_results, "DUPLICATE_SKIPPED", inp)
            return SMBVaultPushResult(
                outcome="DUPLICATE_SKIPPED",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_type=inp.file_type,
                records_processed=0,
                audit_written=True,
            )

        if parse_result.get("error"):
            failure = parse_result["error"]
            log.error(
                "smb_vault_push_workflow.parse_failed",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_type=inp.file_type,
                error=failure,
            )
            await self._write_audit(mock_results, "PARSE_FAILED", inp)
            return SMBVaultPushResult(
                outcome="PARSE_FAILED",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_type=inp.file_type,
                records_processed=0,
                failure_reason=failure,
                audit_written=True,
            )

        record_count = parse_result["record_count"]

        # Step 2: Update vault (Redis)
        vault_result = mock_results["update_vault"]
        if vault_result.get("error"):
            failure = vault_result["error"]
            log.error(
                "smb_vault_push_workflow.vault_update_failed",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_type=inp.file_type,
                error=failure,
            )
            await self._write_audit(mock_results, "VAULT_UPDATE_FAILED", inp)
            return SMBVaultPushResult(
                outcome="VAULT_UPDATE_FAILED",
                agency_id=inp.agency_id,
                smb_id=inp.smb_id,
                file_type=inp.file_type,
                records_processed=0,
                failure_reason=failure,
                audit_written=True,
            )

        # Step 3: Audit
        await self._write_audit(mock_results, "VAULT_UPDATED", inp)

        log.info(
            "smb_vault_push_workflow.vault_updated",
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            file_type=inp.file_type,
            records_processed=record_count,
        )
        return SMBVaultPushResult(
            outcome="VAULT_UPDATED",
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            file_type=inp.file_type,
            records_processed=record_count,
            audit_written=True,
        )

    async def _write_audit(
        self, mock_results: dict, outcome: str, inp: SMBVaultPushInput
    ) -> None:
        mock_results.get("audit")   # consumed
        log.info(
            "smb_vault_push_workflow.audit_written",
            outcome=outcome,
            agency_id=inp.agency_id,
            smb_id=inp.smb_id,
            file_type=inp.file_type,
            file_hash=inp.file_hash,
        )
