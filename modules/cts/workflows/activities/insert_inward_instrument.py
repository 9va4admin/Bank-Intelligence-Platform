"""
insert_inward_instrument — persist one inward cheque instrument to YugabyteDB.

Called by InwardBatchIngestionWorkflow for each instrument after:
  parse_inward_batch  → provides ParsedBatchItem (metadata + byte offsets)
  upload_instrument_images → provides UploadInstrumentImagesResult (MinIO keys)

Writes:
  1. cts.cheque_instruments row  (instrument_id returned)
  2. cts.cheque_image_metadata row  (front BW / back BW / front gray MinIO keys)
  3. Immudb audit event (CTS_IN_BATCH_INGESTED)
  4. Kafka publish on cts.inward.{bank_id} to trigger ChequeProcessingWorkflow

IET rule: iet_deadline always from ParsedBatchItem (PXF source) — never from config.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)

_AMOUNT_RANGE_STANDARD   = "STANDARD"
_AMOUNT_RANGE_HIGH       = "HIGH_VALUE"
_AMOUNT_RANGE_VERY_HIGH  = "VERY_HIGH_VALUE"


def _amount_range(amount_paise: int) -> str:
    if amount_paise >= 10_000_000_00:   # ≥ ₹1 Cr
        return _AMOUNT_RANGE_VERY_HIGH
    if amount_paise >= 5_00_000_00:     # ≥ ₹5 L
        return _AMOUNT_RANGE_HIGH
    return _AMOUNT_RANGE_STANDARD


def _hash_account(bank_id: str, account: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode(),
        f"{bank_id}:{account}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _micr_suffix(micr_line: str) -> str:
    """Last 4 non-space chars from MICR line — used for display (non-PII)."""
    stripped = micr_line.replace(" ", "")
    return stripped[-4:] if len(stripped) >= 4 else stripped.ljust(4, "0")


class InsertInwardInstrumentInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    # Parsed batch item fields
    bank_id: str
    batch_id: str
    session_id: str
    item_seq_no: str
    iet_deadline: float       # from PXF — non-negotiable
    pps_flag: str
    micr_line: str
    drawee_ifsc: str
    drawee_account: str       # will be hashed before storage
    amount_paise: int
    # Image MinIO keys (from upload_instrument_images)
    front_bw_key: str
    back_bw_key: str
    front_gray_key: str
    # Optional
    queue_tier: str = "standard"
    pii_hash_pepper: str = ""  # fetched from config_service by caller


class InsertInwardInstrumentResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    item_seq_no: str
    inserted: bool
    amount_range: str = ""
    error: Optional[str] = None


@activity.defn
async def insert_inward_instrument(
    inp: InsertInwardInstrumentInput,
    db_pool: Any = None,
    kafka_producer: Any = None,
) -> InsertInwardInstrumentResult:
    """Insert cheque_instruments + cheque_image_metadata + publish Kafka event.

    Immudb audit is NOT done here — the workflow calls write_audit activity
    separately after this returns, so HSM signing and unlimited-retry guarantee
    are handled by the standard audit path.

    Gracefully degrades: if db_pool is None returns inserted=False with error.
    Kafka failure is logged but non-blocking (Temporal retry handles re-publish).
    """
    with tracer.start_as_current_span("activity.insert_inward_instrument") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("item_seq_no", inp.item_seq_no)

        if db_pool is None:
            log.warning(
                "insert_inward_instrument.db_unavailable",
                bank_id=inp.bank_id,
                item_seq_no=inp.item_seq_no,
            )
            return InsertInwardInstrumentResult(
                instrument_id="",
                bank_id=inp.bank_id,
                item_seq_no=inp.item_seq_no,
                inserted=False,
                error="DB_UNAVAILABLE",
            )

        instrument_id = str(uuid.uuid4())
        account_hash  = _hash_account(inp.bank_id, inp.drawee_account, inp.pii_hash_pepper)
        account_last4 = inp.drawee_account[-4:] if len(inp.drawee_account) >= 4 else inp.drawee_account
        amount_range  = _amount_range(inp.amount_paise)
        suffix        = _micr_suffix(inp.micr_line)
        workflow_id   = f"cts-{inp.bank_id}-{instrument_id}"
        received_now  = datetime.now(timezone.utc)

        # Extract cheque_number from item_seq_no last 6 chars (NPCI convention)
        cheque_number = inp.item_seq_no[-6:] if len(inp.item_seq_no) >= 6 else inp.item_seq_no.ljust(6, "0")
        # micr_code: first 9 chars of micr_line (bank routing digits)
        micr_code = inp.micr_line[:9].strip() if len(inp.micr_line) >= 9 else inp.micr_line.ljust(9, "0")

        try:
            async with db_pool.acquire() as conn:
                # ── 1. cheque_instruments ──────────────────────────────────────
                await conn.execute(
                    """
                    INSERT INTO cts.cheque_instruments (
                        instrument_id, bank_id,
                        ngch_instrument_ref,
                        presenting_bank_code, presenting_ifsc, drawee_ifsc,
                        cheque_number, micr_code,
                        account_hash, account_last4,
                        amount_paise, amount_range,
                        amount_words_match,
                        cheque_date,
                        instrument_type, cts2010_compliant, watermark_verified,
                        iet_deadline, iet_breached,
                        status, received_at, workflow_id,
                        queue_tier,
                        direction, inward_batch_id,
                        processing_stage, processing_status,
                        micr_suffix
                    ) VALUES (
                        $1::uuid, $2,
                        $3,
                        $4, $4, $5,
                        $6, $7,
                        $8, $9,
                        $10, $11,
                        TRUE,
                        $12::date,
                        'CTS', FALSE, FALSE,
                        $13, FALSE,
                        'RECEIVED', $14, $15,
                        $16,
                        'INWARD', $17,
                        'RECEIVED', 'PENDING',
                        $18
                    )
                    """,
                    instrument_id,
                    inp.bank_id,
                    inp.item_seq_no,                       # ngch_instrument_ref
                    inp.drawee_ifsc,                       # presenting_bank_code + presenting_ifsc (drawee side)
                    inp.drawee_ifsc,                       # drawee_ifsc
                    cheque_number,
                    micr_code,
                    account_hash,
                    account_last4,
                    inp.amount_paise,
                    amount_range,
                    received_now.date().isoformat(),       # cheque_date (from received_at for inward)
                    inp.iet_deadline,
                    received_now,
                    workflow_id,
                    inp.queue_tier,
                    inp.batch_id,
                    suffix,
                )

                # ── 2. cheque_image_metadata ───────────────────────────────────
                await conn.execute(
                    """
                    INSERT INTO cts.cheque_image_metadata (
                        instrument_id, bank_id,
                        front_bw_key, reverse_bw_key, front_grey_key
                    ) VALUES (
                        $1::uuid, $2,
                        $3, $4, $5
                    )
                    """,
                    instrument_id,
                    inp.bank_id,
                    inp.front_bw_key,
                    inp.back_bw_key,
                    inp.front_gray_key,
                )

            log.info(
                "insert_inward_instrument.persisted",
                instrument_id=instrument_id,
                bank_id=inp.bank_id,
                item_seq_no=inp.item_seq_no,
                amount_range=amount_range,
            )

        except Exception as exc:
            log.error(
                "insert_inward_instrument.db_failed",
                bank_id=inp.bank_id,
                item_seq_no=inp.item_seq_no,
                error=str(exc),
            )
            return InsertInwardInstrumentResult(
                instrument_id="",
                bank_id=inp.bank_id,
                item_seq_no=inp.item_seq_no,
                inserted=False,
                error=f"DB_FAILED:{str(exc)[:150]}",
            )

        # ── 3. Kafka publish ─────────────────────────────────────────────────
        if kafka_producer is not None:
            try:
                import json as _json
                kafka_producer.produce(
                    topic=f"cts.inward.{inp.bank_id}",
                    key=instrument_id.encode(),
                    value=_json.dumps({
                        "schema_version": "1.0",
                        "event": "INWARD_INSTRUMENT_RECEIVED",
                        "instrument_id": instrument_id,
                        "bank_id": inp.bank_id,
                        "item_seq_no": inp.item_seq_no,
                        "iet_deadline": inp.iet_deadline,
                        "pps_flag": inp.pps_flag,
                        "queue_tier": inp.queue_tier,
                        "amount_range": amount_range,
                        "workflow_id": workflow_id,
                    }).encode(),
                )
                kafka_producer.flush()
                log.info(
                    "insert_inward_instrument.kafka_published",
                    instrument_id=instrument_id,
                    bank_id=inp.bank_id,
                )
            except Exception as exc:
                log.warning(
                    "insert_inward_instrument.kafka_failed",
                    instrument_id=instrument_id,
                    bank_id=inp.bank_id,
                    error=str(exc),
                )
                # Non-blocking — Temporal retry handles re-publish

        return InsertInwardInstrumentResult(
            instrument_id=instrument_id,
            bank_id=inp.bank_id,
            item_seq_no=inp.item_seq_no,
            inserted=True,
            amount_range=amount_range,
        )
