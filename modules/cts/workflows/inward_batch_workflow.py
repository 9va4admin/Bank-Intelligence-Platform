"""
InwardBatchIngestionWorkflow — full inward batch ingestion pipeline.

Receives notification that a PXF + CXF + CIBF triple has been deposited
to MinIO by the NGCH adapter. Steps:
  1. parse_inward_batch   — download, parse PXF/CXF/CIBF, return per-item list
  2. upload_instrument_images — upload front BW / back BW / front gray per instrument
  3. insert_inward_instrument — write to cts.cheque_instruments + cheque_image_metadata
                                + publish cts.inward.{bank_id} Kafka event
  4. start_child_workflow ChequeProcessingWorkflow per instrument (fan-out, parallel)

IET rule: iet_deadline per instrument always comes from PXF. Never from config.
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
    from modules.cts.workflows.activities.insert_inward_instrument import (
        InsertInwardInstrumentInput,
        InsertInwardInstrumentResult,
        insert_inward_instrument,
    )
    from modules.cts.workflows.cheque_workflow import (
        ChequeProcessingWorkflow,
        ChequeWorkflowInput,
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

_DB_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValidationError"],
)


@workflow.defn
class InwardBatchIngestionWorkflow:
    """Ingests one inward clearing batch: parse → upload → DB insert → fan-out."""

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

        # ── Step 1: parse PXF + CXF + CIBF ──────────────────────────────────
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

        # ── Step 2: upload images in parallel ────────────────────────────────
        upload_handles = []
        for item_dict in items:
            upload_handles.append(
                workflow.execute_activity(
                    upload_instrument_images,
                    args=[UploadInstrumentImagesInput(
                        bank_id=inp.bank_id,
                        batch_id=inp.batch_id,
                        item_seq_no=item_dict["item_seq_no"],
                        front_bw_bytes=b"",    # activity fetches CIBF from MinIO staging key
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

        # ── Step 3: DB insert + Kafka + ChequeProcessingWorkflow per instrument
        instruments_started = 0
        failure_count = 0

        for item_dict, upload_result in zip(items, upload_results):
            if not upload_result.uploaded:
                failure_count += 1
                continue

            # 3a. Persist to YugabyteDB + publish Kafka event
            insert_result: InsertInwardInstrumentResult = await workflow.execute_activity(
                insert_inward_instrument,
                args=[InsertInwardInstrumentInput(
                    bank_id=inp.bank_id,
                    batch_id=inp.batch_id,
                    session_id=inp.session_id,
                    item_seq_no=item_dict["item_seq_no"],
                    iet_deadline=item_dict["iet_deadline"],   # from PXF — IET safety
                    pps_flag=item_dict["pps_flag"],
                    micr_line=item_dict["micr_line"],
                    drawee_ifsc=item_dict["drawee_ifsc"],
                    drawee_account=item_dict["drawee_account"],
                    amount_paise=item_dict["amount_paise"],
                    front_bw_key=upload_result.front_bw_key,
                    back_bw_key=upload_result.back_bw_key,
                    front_gray_key=upload_result.front_gray_key,
                )],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DB_RETRY,
            )

            if not insert_result.inserted:
                failure_count += 1
                continue

            # 3b. Fan-out: one ChequeProcessingWorkflow per instrument
            # IETWatchdogWorkflow is started inside ChequeProcessingWorkflow as its first act.
            # parent_close_policy=ABANDON: processing survives even if this batch workflow ends.
            await workflow.start_child_workflow(
                ChequeProcessingWorkflow.run,
                args=[ChequeWorkflowInput(
                    instrument_id=insert_result.instrument_id,
                    bank_id=inp.bank_id,
                    image_url=upload_result.front_bw_key,
                    account_number=item_dict["drawee_account"],
                    cheque_number=item_dict["item_seq_no"][-6:],
                    presented_amount=item_dict["amount_paise"] / 100.0,
                    presented_payee="",    # Vision LLM extracts this inside the workflow
                    iet_deadline=item_dict["iet_deadline"],   # from PXF — IET watchdog uses this
                    ngch_ifsc=item_dict["drawee_ifsc"],
                )],
                id=f"cts-{inp.bank_id}-{insert_result.instrument_id}",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )

            instruments_started += 1

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
