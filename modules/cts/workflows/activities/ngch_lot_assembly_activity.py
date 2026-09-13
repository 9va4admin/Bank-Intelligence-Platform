"""
build_and_upload_ngch_files — Temporal activity.

Replaces the old build_ngch_file stub in ngch_submission_activities.py.

Full pipeline:
  1. DB: cts.outward_scan_events → ACCEPTED instrument_ids for the lot
  2. DB: cts.cheque_instruments  → cheque fields (micr_code, amount_paise, etc.)
  3. DB: cts.cheque_image_metadata → MinIO keys for front_bw, back_bw, front_grey
  4. MinIO: download image bytes per instrument (3 images × N instruments)
  5. Construct List[InstrumentBuildInput]
  6. Call build_ngch_file() pure function (CHI Spec Rev 3.00 compliant)
  7. MinIO: upload CXF file + CIBF file
  8. Return FetchAndBuildResult (MinIO keys + filenames + instrument_count)

DI args (None = unavailable / dev mode):
  db_pool     — asyncpg pool (or compatible)
  minio_client — minio.Minio (sync) or compatible
  hsm          — injected signer; must implement sign(bytes) -> bytes (256 B)
  config_svc   — shared.config.config_service.config_service
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.activities")


class FetchAndBuildInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    lot_number: str
    session_id: str
    clearing_date: str      # ISO format: "YYYY-MM-DD"
    bank_ifsc: str


class FetchAndBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    cxf_minio_key: str      # MinIO object key for the CXF file
    cibf_minio_key: str     # MinIO object key for the CIBF file
    cxf_filename: str       # spec-compliant filename (CXF_...)
    cibf_filename: str      # spec-compliant filename (CIBF_...)
    instrument_count: int


@activity.defn
async def build_and_upload_ngch_files(
    inp: FetchAndBuildInput,
    db_pool: Any = None,
    minio_client: Any = None,
    hsm: Any = None,
    config_svc: Any = None,
) -> FetchAndBuildResult:
    """
    Fetch instruments for the lot, build spec-compliant CXF + CIBF, upload to MinIO.

    Raises ValueError when no ACCEPTED instruments are found for the lot (caller
    must not submit an empty lot to NGCH).
    """
    with tracer.start_as_current_span("activity.build_and_upload_ngch_files") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("lot_number", inp.lot_number)

        # ── 1. Config ──────────────────────────────────────────────────────────
        if config_svc is None:
            from shared.config.config_service import config_service as config_svc  # type: ignore

        cts_cfg = await config_svc.get_cts_config(inp.bank_id)
        routing_no: str = cts_cfg.get("cts.npci_routing_no", "000000000")
        clearing_type: str = cts_cfg.get("cts.clearing_type", "14")
        trans_code: str = cts_cfg.get("cts.micr_trans_code", "10")
        doc_type: str = cts_cfg.get("cts.ngch_doc_type", "01")
        cheque_width_px: int = int(cts_cfg.get("cts.cheque_width_px", "1200"))
        cheque_height_px: int = int(cts_cfg.get("cts.cheque_height_px", "500"))
        cheque_bit_depth: int = int(cts_cfg.get("cts.cheque_bit_depth", "1"))
        minio_bucket: str = cts_cfg.get("cts.minio_bucket", "astra-cts")

        # ── 2. DB: ACCEPTED instrument_ids for lot ─────────────────────────────
        async with db_pool.acquire() as conn:
            event_rows = await conn.fetch(
                """
                SELECT instrument_id
                FROM cts.outward_scan_events
                WHERE lot_id    = $1
                  AND bank_id   = $2
                  AND outcome   = 'ACCEPTED'
                  AND instrument_id IS NOT NULL
                ORDER BY scanned_at
                """,
                inp.lot_number,
                inp.bank_id,
            )

        if not event_rows:
            raise ValueError(
                f"No ACCEPTED instruments found for lot {inp.lot_number!r} "
                f"in bank {inp.bank_id!r} — cannot build NGCH file"
            )

        instrument_ids = [r["instrument_id"] for r in event_rows]
        span.set_attribute("instrument_count_db", len(instrument_ids))

        # ── 3. DB: cheque fields ───────────────────────────────────────────────
        async with db_pool.acquire() as conn:
            instr_rows = await conn.fetch(
                """
                SELECT instrument_id,
                       cheque_number,
                       micr_code,
                       drawee_ifsc,
                       presenting_ifsc,
                       amount_paise,
                       cheque_date::TEXT AS cheque_date,
                       account_last4
                FROM cts.cheque_instruments
                WHERE instrument_id = ANY($1)
                  AND bank_id       = $2
                """,
                instrument_ids,
                inp.bank_id,
            )

        instr_map = {r["instrument_id"]: dict(r) for r in instr_rows}

        # ── 4. DB: image metadata (MinIO keys) ─────────────────────────────────
        async with db_pool.acquire() as conn:
            img_rows = await conn.fetch(
                """
                SELECT instrument_id,
                       front_bw_key,
                       reverse_bw_key,
                       front_grey_key,
                       dpi_front
                FROM cts.cheque_image_metadata
                WHERE instrument_id = ANY($1)
                  AND bank_id       = $2
                """,
                instrument_ids,
                inp.bank_id,
            )

        img_map = {r["instrument_id"]: dict(r) for r in img_rows}

        # ── 5. Date/time strings for filename and CXF ──────────────────────────
        clearing_date_obj = datetime.strptime(inp.clearing_date, "%Y-%m-%d")
        date_ddmmyyyy = clearing_date_obj.strftime("%d%m%Y")
        time_hhmmss = datetime.now(timezone.utc).strftime("%H%M%S")

        # ── 6. Construct InstrumentBuildInput list ─────────────────────────────
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput

        instruments: List[InstrumentBuildInput] = []
        for seq, instrument_id in enumerate(instrument_ids, start=1):
            instr = instr_map.get(instrument_id)
            img = img_map.get(instrument_id)

            if not instr or not img:
                log.warning(
                    "build_and_upload_ngch_files.missing_data",
                    instrument_id=instrument_id,
                    has_instr=bool(instr),
                    has_img=bool(img),
                    bank_id=inp.bank_id,
                    lot_number=inp.lot_number,
                )
                continue

            # Download the three images from MinIO
            front_bw_bytes   = _download(minio_client, minio_bucket, img["front_bw_key"])
            back_bw_bytes    = _download(minio_client, minio_bucket, img["reverse_bw_key"])
            front_gray_bytes = _download(minio_client, minio_bucket, img["front_grey_key"])

            # item_seq_no: 9-digit routing + 5-digit per-lot sequence = 14 chars
            item_seq_no = f"{routing_no}{seq:05d}"
            # Assembled MICR line (cheque serial + sort code)
            micr_line = f"{instr['cheque_number']}{instr['micr_code']}"
            dpi = int(img.get("dpi_front") or 200)

            instruments.append(InstrumentBuildInput(
                item_seq_no=item_seq_no,
                payor_bank_rout_no=instr["micr_code"],   # 9-digit MICR sort code = drawee routing
                account_no=f"****{instr['account_last4']}",
                serial_no=instr["cheque_number"],
                trans_code=trans_code,
                doc_type=doc_type,
                micr_line=micr_line,
                drawee_ifsc=instr["drawee_ifsc"],
                amount_paise=int(instr["amount_paise"]),
                front_bw_bytes=front_bw_bytes,
                back_bw_bytes=back_bw_bytes,
                front_gray_bytes=front_gray_bytes,
                width_px=cheque_width_px,
                height_px=cheque_height_px,
                dpi=dpi,
                bit_depth=cheque_bit_depth,
                presenting_bank_rout_no=routing_no,
                cycle_no="01",
                presentment_date=date_ddmmyyyy,
                batch_id=inp.lot_number,
            ))

        if not instruments:
            raise ValueError(
                f"All instruments for lot {inp.lot_number!r} are missing DB records — "
                f"cannot build NGCH file"
            )

        log.info(
            "build_and_upload_ngch_files.instruments_ready",
            bank_id=inp.bank_id,
            lot_number=inp.lot_number,
            instrument_count=len(instruments),
        )

        # ── 7. Call spec-compliant build_ngch_file pure function ───────────────
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file as _build_pure,
            BuildNGCHFileInput,
        )

        build_result = _build_pure(
            BuildNGCHFileInput(
                bank_id=inp.bank_id,
                lot_number=inp.lot_number,
                session_id=inp.session_id,
                routing_no=routing_no,
                clearing_type=clearing_type,
                file_id="0001",
                date_ddmmyyyy=date_ddmmyyyy,
                time_hhmmss=time_hhmmss,
                instruments=instruments,
            ),
            hsm=hsm,
        )

        # ── 8. Upload CXF + CIBF to MinIO ─────────────────────────────────────
        cxf_key  = f"cts/ngch/{inp.bank_id}/{inp.lot_number}/{build_result.cxf_filename}"
        cibf_key = f"cts/ngch/{inp.bank_id}/{inp.lot_number}/{build_result.cibf_filename}"

        _upload(minio_client, minio_bucket, cxf_key, build_result.cxf_bytes, "application/xml")
        _upload(minio_client, minio_bucket, cibf_key, build_result.cibf_bytes, "application/octet-stream")

        span.set_attribute("cxf_key", cxf_key)
        span.set_attribute("cibf_key", cibf_key)
        span.set_attribute("instrument_count", build_result.instrument_count)

        log.info(
            "build_and_upload_ngch_files.complete",
            bank_id=inp.bank_id,
            lot_number=inp.lot_number,
            cxf_key=cxf_key,
            cibf_key=cibf_key,
            instrument_count=build_result.instrument_count,
            cxf_bytes=len(build_result.cxf_bytes),
            cibf_bytes=len(build_result.cibf_bytes),
        )

        return FetchAndBuildResult(
            cxf_minio_key=cxf_key,
            cibf_minio_key=cibf_key,
            cxf_filename=build_result.cxf_filename,
            cibf_filename=build_result.cibf_filename,
            instrument_count=build_result.instrument_count,
        )


# ── MinIO helpers (sync — minio-py is synchronous) ────────────────────────────

def _download(minio_client: Any, bucket: str, key: str) -> bytes:
    resp = minio_client.get_object(bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def _upload(minio_client: Any, bucket: str, key: str, data: bytes, content_type: str) -> None:
    minio_client.put_object(
        bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
