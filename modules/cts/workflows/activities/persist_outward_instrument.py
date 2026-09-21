"""persist_outward_instrument — write the full outward cheque record when a scan is ACCEPTED.

Until now an accepted outward scan left only a masked cts.outward_scan_events row, so lot -> endorsement ->
NGCH file build had nothing to read. This writes one cts.cheque_instruments row (direction='OUTWARD') carrying
MICR, amount, date, image keys and the lot assignment. Idempotent per instrument (Temporal retries).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import urlparse

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.lot.db_lots import ensure_open_lot
from modules.cts.preprocessing.micr_validator import validate_micr_line
from shared.observability.otel_setup import get_tracer
from shared.utils.instrument_uuid import to_instrument_uuid
from shared.utils.masking import mask_amount
from shared.utils.pii_crypto import hash_account_number

log = structlog.get_logger()
tracer = get_tracer(__name__)


class PersistOutwardInstrumentInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    instrument_id: str
    scan_id: str
    bank_ifsc: str
    session_id: str = ""
    branch_id: Optional[str] = None
    pu_id: Optional[str] = None
    micr_line: str
    cheque_number: str = ""
    amount_str: Optional[str] = None          # decimal rupees
    cheque_date: Optional[str] = None         # ISO date
    registered_drawee_ifsc: Optional[str] = None
    image_front_url: str
    image_rear_url: str
    image_front_gray_url: Optional[str] = None
    front_dpi: Optional[int] = None


class PersistOutwardInstrumentResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_uuid: str
    lot_id: Optional[str] = None
    inserted: bool


def object_key_from_url(url: str) -> str:
    """s3://bucket/key or http(s)://host/bucket/key?sig -> key."""
    p = urlparse(url)
    path = p.path.lstrip("/")
    if p.scheme == "s3":
        return path
    return path.split("/", 1)[1] if "/" in path else path


async def persist_outward_instrument_row(conn, inp: PersistOutwardInstrumentInput, pepper: str,
                                         today: Optional[date] = None) -> PersistOutwardInstrumentResult:
    micr = validate_micr_line(inp.micr_line)
    if micr.micr_code is None or not (micr.cheque_number or inp.cheque_number):
        raise ValueError(f"MICR line not parseable for {inp.instrument_id}: {micr.flags}")
    if not inp.cheque_date:
        raise ValueError(f"cheque_date missing for {inp.instrument_id}")
    if inp.amount_str is None:
        raise ValueError(f"amount missing for {inp.instrument_id}")
    cheque_date = date.fromisoformat(inp.cheque_date)
    amount = Decimal(inp.amount_str)
    amount_paise = int(amount * 100)

    iid = to_instrument_uuid(inp.bank_id, inp.instrument_id)
    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT lot_id FROM cts.cheque_instruments WHERE instrument_id = $1 AND bank_id = $2",
            iid, inp.bank_id,
        )
        if existing is not None:
            return PersistOutwardInstrumentResult(instrument_uuid=str(iid), lot_id=existing["lot_id"], inserted=False)

        lot_id = None
        if inp.branch_id and inp.session_id:
            lot_id, _ = await ensure_open_lot(
                conn, bank_id=inp.bank_id, branch_id=inp.branch_id, session_id=inp.session_id,
                clearing_date=today or date.today(),
            )

        account_field = micr.account_field or ""
        account_hash = hash_account_number(account_field, inp.bank_id, pepper)
        front_key = object_key_from_url(inp.image_front_url)
        rear_key = object_key_from_url(inp.image_rear_url)
        gray_key = object_key_from_url(inp.image_front_gray_url) if inp.image_front_gray_url else front_key
        cheque_number = micr.cheque_number or inp.cheque_number
        drawee_ifsc = inp.registered_drawee_ifsc or ""
        now = datetime.now(timezone.utc)
        await conn.execute(
            """
            INSERT INTO cts.cheque_instruments (
                instrument_id, bank_id, presenting_bank_code, presenting_ifsc, drawee_ifsc,
                cheque_number, micr_code, account_hash, account_last4,
                amount_paise, amount_range, amount_words_match, cheque_date,
                instrument_type, cts2010_compliant, watermark_verified,
                iet_deadline, iet_breached, status, received_at, workflow_id,
                direction, processing_stage, processing_status, micr_suffix,
                pu_id, branch_id, clearing_session_id,
                lot_id, image_front_bw_key, image_back_bw_key, image_front_gray_key,
                dpi, trans_code, payor_bank_rout_no
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10, $11, TRUE, $12,
                'CTS', TRUE, FALSE,
                0, FALSE, 'ACCEPTED', $13, $14,
                'OUTWARD', 'LOT_ASSIGNED', 'ACCEPTED', $15,
                $16, $17, $18,
                $19, $20, $21, $22,
                $23, $24, $25
            )
            """,
            iid, inp.bank_id, inp.bank_ifsc[:4], inp.bank_ifsc, drawee_ifsc,
            cheque_number, micr.micr_code, account_hash, account_field[-4:],
            amount_paise, mask_amount(float(amount)), cheque_date,
            now, f"cts-outward-{inp.bank_id}-{inp.scan_id}",
            (inp.micr_line or "")[-4:],
            inp.pu_id, inp.branch_id, inp.session_id or None,
            lot_id, front_key, rear_key, gray_key,
            inp.front_dpi, micr.transaction_code, micr.micr_code,
        )
    return PersistOutwardInstrumentResult(instrument_uuid=str(iid), lot_id=lot_id, inserted=True)


@activity.defn(name="persist_outward_instrument")
async def persist_outward_instrument(inp: PersistOutwardInstrumentInput) -> PersistOutwardInstrumentResult:
    if isinstance(inp, dict):
        inp = PersistOutwardInstrumentInput(**inp)
    with tracer.start_as_current_span("activity.persist_outward_instrument") as span:
        span.set_attribute("bank_id", inp.bank_id)
        from shared.config.config_service import config_service
        if not config_service._ready:
            await config_service.initialise()
        dsn = await config_service.get_secret("db.cts.dsn")
        pepper = await config_service.get_secret("pii_hash_pepper")
        import asyncpg
        from shared.db.codecs import register_lenient_codecs
        conn = await asyncpg.connect(dsn)          # raises on failure -> Temporal retries; never a silent skip
        try:
            await register_lenient_codecs(conn)
            return await persist_outward_instrument_row(conn, inp, pepper)
        finally:
            await conn.close()
