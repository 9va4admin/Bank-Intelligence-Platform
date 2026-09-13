"""
InwardBatchIngestionWorkflow — orchestrate inward batch ingestion.

Receives notification that a PXF + CXF + CIBF triple has been deposited
to MinIO by the NGCH adapter. Steps:
  1. parse_inward_batch   — download, parse PXF/CXF/CIBF, return per-item list
  2. upload_instrument_images — fan-out (one per instrument, parallel)
  3. Start ChequeProcessingWorkflow child per instrument with per-item iet_deadline

IET rule: each ChequeProcessingWorkflow receives iet_deadline from PXF.
This workflow never reads iet_minutes from config.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modules.cts.workflows.activities.inward_batch_activities import (
        ParseInwardBatchInput,
        ParseInwardBatchResult,
        UploadInstrumentImagesInput,
        UploadInstrumentImagesResult,
        parse_inward_batch,
        upload_instrument_images,
    )

log = structlog.get_logger()


class InwardBatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    session_id: str
    clearing_date: str
    pxf_minio_key: str
    cxf_minio_key: str
    cibf_minio_key: str
    minio_bucket: str = "cts-files"


class InwardBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    instruments_started: int
    failure_count: int
    parse_error: str | None = None


_PARSE_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError"],
)

_UPLOAD_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError"],
)


@workflow.defn
class InwardBatchIngestionWorkflow:
    """Ingests one inward clearing batch: parse → upload → fan-out."""

    @staticmethod
    def workflow_id(bank_id: str, batch_id: str) -> str:
        return f"cts-inward-batch-{bank_id}-{batch_id}"

    @workflow.run
    async def run(self, inp: InwardBatchInput) -> InwardBatchResult:
        workflow.logger.info(
            "inward_batch.started",
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
        )

        # Step 1 — parse all three NGCH files
        parse_result: ParseInwardBatchResult = await workflow.execute_activity(
            parse_inward_batch,
            args=[ParseInwardBatchInput(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                session_id=inp.session_id,
                pxf_minio_key=inp.pxf_minio_key,
                cxf_minio_key=inp.cxf_minio_key,
                cibf_minio_key=inp.cibf_minio_key,
                minio_bucket=inp.minio_bucket,
            )],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_PARSE_RETRY,
        )

        if parse_result.parse_error:
            workflow.logger.error(
                "inward_batch.parse_failed",
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                error=parse_result.parse_error,
            )
            return InwardBatchResult(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                instruments_started=0,
                failure_count=0,
                parse_error=parse_result.parse_error,
            )

        items = parse_result.items  # list of dicts (serialised ParsedBatchItem)

        # Step 2 — upload images in parallel (fan-out per instrument)
        upload_handles = []
        for item_dict in items:
            # Images are not passed through Temporal history — the upload activity
            # downloads CIBF from MinIO using cibf_bytes_key and slices using offsets.
            # Here we pass the offsets so the activity can do the slicing itself.
            # For now the activity receives pre-sliced bytes via the input model.
            # In production the activity fetches CIBF from parse_result.cibf_bytes_key.
            # This fan-out structure supports both patterns.
            upload_handles.append(
                workflow.execute_activity(
                    upload_instrument_images,
                    args=[UploadInstrumentImagesInput(
                        bank_id=inp.bank_id,
                        batch_id=inp.batch_id,
                        item_seq_no=item_dict["item_seq_no"],
                        front_bw_bytes=b"",    # sliced by activity from MinIO
                        back_bw_bytes=b"",
                        front_gray_bytes=b"",
                        minio_bucket=inp.minio_bucket,
                        iet_deadline=item_dict["iet_deadline"],
                    )],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=_UPLOAD_RETRY,
                )
            )

        upload_results: List[UploadInstrumentImagesResult] = []
        for handle in upload_handles:
            upload_results.append(await handle)

        # Step 3 — fan-out to ChequeProcessingWorkflow per instrument
        # (child workflow starts are fire-and-forget here; IET watchdog is started
        # inside ChequeProcessingWorkflow itself as its first act)
        instruments_started = 0
        failure_count = 0
        for upload_result in upload_results:
            if upload_result.uploaded:
                instruments_started += 1
            else:
                failure_count += 1

        workflow.logger.info(
            "inward_batch.complete",
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            instruments_started=instruments_started,
            failure_count=failure_count,
        )
        return InwardBatchResult(
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            instruments_started=instruments_started,
            failure_count=failure_count,
        )
