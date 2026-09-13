"""
Inward Batch Ingestion Activities — parse PXF + CXF + CIBF from NGCH,
extract per-instrument images, upload to MinIO, prepare fanout.

Activity sequence (driven by InwardBatchIngestionWorkflow):
  1. parse_inward_batch   — download PXF/CXF/CIBF from MinIO, parse all three
  2. upload_instrument_images — for each instrument, upload front BW / back BW /
                                front gray TIFF/JFIF to individual MinIO keys
  3. (workflow) start_child ChequeProcessingWorkflow per instrument, passing
                image URLs from step 2 and iet_deadline from PXF

IET rule (non-negotiable):
  - iet_deadline per instrument comes from PXF ItemExpiryTime (already UTC unix timestamp)
  - NEVER fall back to config iet_minutes for per-instrument IET
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, List, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


# ── ParsedBatchItem ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParsedBatchItem:
    """Per-instrument data after parsing both PXF and CXF.

    iet_deadline is from PXF (not config). Byte offsets are from CXF.
    """
    item_seq_no: str
    iet_deadline: float       # UTC unix timestamp from PXF ItemExpiryTime
    pps_flag: str             # P/D/Y/Z/N/R/U from PXF
    micr_line: str
    drawee_ifsc: str
    drawee_account: str
    amount_paise: int
    # CIBF byte offsets (from CXF)
    front_bw_ds_offset: int
    front_bw_image_offset: int
    front_bw_image_length: int
    back_bw_ds_offset: int
    back_bw_image_offset: int
    back_bw_image_length: int
    front_gray_ds_offset: int
    front_gray_image_offset: int
    front_gray_image_length: int


# ── parse_inward_batch ────────────────────────────────────────────────────────

class ParseInwardBatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    session_id: str
    pxf_minio_key: str
    cxf_minio_key: str
    cibf_minio_key: str
    minio_bucket: str


class ParseInwardBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    bank_id: str
    instrument_count: int
    items: List[dict] = []        # serialised ParsedBatchItem dicts
    cibf_bytes_key: str = ""      # MinIO key where CIBF bytes are stored (for upload step)
    parse_error: Optional[str] = None


@activity.defn
async def parse_inward_batch(
    inp: ParseInwardBatchInput,
    minio_client: Any = None,
) -> ParseInwardBatchResult:
    """Download PXF + CXF + CIBF from MinIO and parse them into ParsedBatchItem list.

    CIBF bytes are written back to MinIO at a staging key so the upload activity
    can reference them without passing raw bytes through Temporal history.

    Returns ParseInwardBatchResult with instrument_count=0 and parse_error set
    if MinIO is unavailable or parsing fails.
    """
    with tracer.start_as_current_span("activity.parse_inward_batch") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("batch_id", inp.batch_id)

        if minio_client is None:
            log.warning(
                "parse_inward_batch.minio_unavailable",
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
            )
            return ParseInwardBatchResult(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                instrument_count=0,
                parse_error="MINIO_UNAVAILABLE",
            )

        try:
            pxf_bytes  = _download(minio_client, inp.minio_bucket, inp.pxf_minio_key)
            cxf_bytes  = _download(minio_client, inp.minio_bucket, inp.cxf_minio_key)
            cibf_bytes = _download(minio_client, inp.minio_bucket, inp.cibf_minio_key)
        except Exception as exc:
            log.error(
                "parse_inward_batch.download_failed",
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return ParseInwardBatchResult(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                instrument_count=0,
                parse_error=f"DOWNLOAD_FAILED:{str(exc)[:100]}",
            )

        try:
            from modules.cts.ngch.pxf_parser import PXFParser
            from modules.cts.ngch.cxf_parser import CXFParser

            pxf_instruments = PXFParser().parse(pxf_bytes)
            cxf_file = CXFParser().parse(cxf_bytes)

            # Build lookup: item_seq_no → PXF InwardInstrument
            pxf_map = {inst.item_seq_no: inst for inst in pxf_instruments}

            items: List[ParsedBatchItem] = []
            for cxf_item in cxf_file.items:
                pxf_inst = pxf_map.get(cxf_item.item_seq_no)
                if pxf_inst is None:
                    log.warning(
                        "parse_inward_batch.pxf_item_missing",
                        item_seq_no=cxf_item.item_seq_no,
                        batch_id=inp.batch_id,
                    )
                    continue

                items.append(ParsedBatchItem(
                    item_seq_no=cxf_item.item_seq_no,
                    iet_deadline=pxf_inst.iet_deadline,
                    pps_flag=pxf_inst.pps_flag,
                    micr_line=cxf_item.micr_line,
                    drawee_ifsc=cxf_item.drawee_ifsc,
                    drawee_account=pxf_inst.drawee_account,
                    amount_paise=cxf_item.amount_paise,
                    front_bw_ds_offset=cxf_item.front_bw_ds_offset,
                    front_bw_image_offset=cxf_item.front_bw_image_offset,
                    front_bw_image_length=cxf_item.front_bw_image_length,
                    back_bw_ds_offset=cxf_item.back_bw_ds_offset,
                    back_bw_image_offset=cxf_item.back_bw_image_offset,
                    back_bw_image_length=cxf_item.back_bw_image_length,
                    front_gray_ds_offset=cxf_item.front_gray_ds_offset,
                    front_gray_image_offset=cxf_item.front_gray_image_offset,
                    front_gray_image_length=cxf_item.front_gray_image_length,
                ))

        except Exception as exc:
            log.error(
                "parse_inward_batch.parse_failed",
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return ParseInwardBatchResult(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                instrument_count=0,
                parse_error=f"PARSE_FAILED:{str(exc)[:100]}",
            )

        # Store CIBF at a staging key so upload activities can retrieve it
        cibf_staging_key = (
            f"cts/inward/{inp.bank_id}/{inp.session_id}/staging/{inp.batch_id}_cibf.img"
        )
        try:
            minio_client.put_object(
                bucket_name=inp.minio_bucket,
                object_name=cibf_staging_key,
                data=io.BytesIO(cibf_bytes),
                length=len(cibf_bytes),
                content_type="application/octet-stream",
            )
        except Exception as exc:
            log.warning(
                "parse_inward_batch.cibf_staging_failed",
                batch_id=inp.batch_id,
                error=str(exc),
            )
            # Return what we parsed — upload activities will fail but batch is recorded
            return ParseInwardBatchResult(
                batch_id=inp.batch_id,
                bank_id=inp.bank_id,
                instrument_count=len(items),
                items=[_item_to_dict(i) for i in items],
                parse_error=f"CIBF_STAGING_FAILED:{str(exc)[:100]}",
            )

        log.info(
            "parse_inward_batch.complete",
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            instrument_count=len(items),
        )
        return ParseInwardBatchResult(
            batch_id=inp.batch_id,
            bank_id=inp.bank_id,
            instrument_count=len(items),
            items=[_item_to_dict(i) for i in items],
            cibf_bytes_key=cibf_staging_key,
        )


def _download(minio_client: Any, bucket: str, key: str) -> bytes:
    response = minio_client.get_object(bucket_name=bucket, object_name=key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _item_to_dict(item: ParsedBatchItem) -> dict:
    return {
        "item_seq_no": item.item_seq_no,
        "iet_deadline": item.iet_deadline,
        "pps_flag": item.pps_flag,
        "micr_line": item.micr_line,
        "drawee_ifsc": item.drawee_ifsc,
        "drawee_account": item.drawee_account,
        "amount_paise": item.amount_paise,
        "front_bw_ds_offset": item.front_bw_ds_offset,
        "front_bw_image_offset": item.front_bw_image_offset,
        "front_bw_image_length": item.front_bw_image_length,
        "back_bw_ds_offset": item.back_bw_ds_offset,
        "back_bw_image_offset": item.back_bw_image_offset,
        "back_bw_image_length": item.back_bw_image_length,
        "front_gray_ds_offset": item.front_gray_ds_offset,
        "front_gray_image_offset": item.front_gray_image_offset,
        "front_gray_image_length": item.front_gray_image_length,
    }


# ── upload_instrument_images ──────────────────────────────────────────────────

class UploadInstrumentImagesInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    batch_id: str
    item_seq_no: str
    cibf_staging_key: str        # MinIO key of staged CIBF — activity slices images from it
    front_bw_image_offset: int
    front_bw_image_length: int
    back_bw_image_offset: int
    back_bw_image_length: int
    front_gray_image_offset: int
    front_gray_image_length: int
    minio_bucket: str
    iet_deadline: float = 0.0   # passed through to result for workflow to use


class UploadInstrumentImagesResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    item_seq_no: str
    uploaded: bool
    front_bw_key: str = ""
    back_bw_key: str = ""
    front_gray_key: str = ""
    iet_deadline: float = 0.0
    error: Optional[str] = None


@activity.defn
async def upload_instrument_images(
    inp: UploadInstrumentImagesInput,
    minio_client: Any = None,
) -> UploadInstrumentImagesResult:
    """Upload front BW, back BW, and front gray images for one inward instrument.

    MinIO keys follow the pattern:
      cts/inward/{bank_id}/{batch_id}/instruments/{item_seq_no}/{view}.tiff
    """
    with tracer.start_as_current_span("activity.upload_instrument_images") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("item_seq_no", inp.item_seq_no)

        if minio_client is None:
            log.warning(
                "upload_instrument_images.minio_unavailable",
                item_seq_no=inp.item_seq_no,
                bank_id=inp.bank_id,
            )
            return UploadInstrumentImagesResult(
                item_seq_no=inp.item_seq_no,
                uploaded=False,
                iet_deadline=inp.iet_deadline,
                error="MINIO_UNAVAILABLE",
            )

        base = f"cts/inward/{inp.bank_id}/{inp.batch_id}/instruments/{inp.item_seq_no}"
        fbw_key  = f"{base}/front_bw.tiff"
        bbw_key  = f"{base}/back_bw.tiff"
        fgry_key = f"{base}/front_gray.jfif"

        try:
            # Download the staged CIBF once and slice out the three image regions
            cibf = _download(minio_client, inp.minio_bucket, inp.cibf_staging_key)
            front_bw_bytes = cibf[
                inp.front_bw_image_offset: inp.front_bw_image_offset + inp.front_bw_image_length
            ]
            back_bw_bytes = cibf[
                inp.back_bw_image_offset: inp.back_bw_image_offset + inp.back_bw_image_length
            ]
            front_gray_bytes = cibf[
                inp.front_gray_image_offset: inp.front_gray_image_offset + inp.front_gray_image_length
            ]

            for key, data, ctype in [
                (fbw_key,  front_bw_bytes,   "image/tiff"),
                (bbw_key,  back_bw_bytes,    "image/tiff"),
                (fgry_key, front_gray_bytes, "image/jpeg"),
            ]:
                minio_client.put_object(
                    bucket_name=inp.minio_bucket,
                    object_name=key,
                    data=io.BytesIO(data),
                    length=len(data),
                    content_type=ctype,
                )

            log.info(
                "upload_instrument_images.uploaded",
                item_seq_no=inp.item_seq_no,
                bank_id=inp.bank_id,
                fbw_key=fbw_key,
            )
            return UploadInstrumentImagesResult(
                item_seq_no=inp.item_seq_no,
                uploaded=True,
                front_bw_key=fbw_key,
                back_bw_key=bbw_key,
                front_gray_key=fgry_key,
                iet_deadline=inp.iet_deadline,
            )
        except Exception as exc:
            log.error(
                "upload_instrument_images.failed",
                item_seq_no=inp.item_seq_no,
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return UploadInstrumentImagesResult(
                item_seq_no=inp.item_seq_no,
                uploaded=False,
                iet_deadline=inp.iet_deadline,
                error=str(exc)[:200],
            )
