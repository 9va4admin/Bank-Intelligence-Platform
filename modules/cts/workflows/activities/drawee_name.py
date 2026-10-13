"""
record_drawee_name — inward Drawee Name from the account-number lookup in CBS.

The drawee name shown to an inward reviewer must come from the bank's own account record,
never from OCR of the cheque face. Decision (2026-10-13, bank owner): the name is stored as
plain text (exempt from column encryption/masking) in cts.inward_drawee_name.

It is deliberately NOT returned in the activity result: workflow history is not a place for
customer names. A failed lookup degrades to "no name" and never changes the cheque decision.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.cbs_connector.exceptions import AccountNotFoundError
from shared.observability.otel_setup import get_tracer
from shared.utils.instrument_uuid import to_instrument_uuid

log = structlog.get_logger()
tracer = get_tracer(__name__)


class DraweeNameInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    bank_id: str
    instrument_id: str


class DraweeNameResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    stored: bool
    reason: Optional[str] = None


_SQL = """
INSERT INTO cts.inward_drawee_name (bank_id, instrument_id, drawee_name)
VALUES ($1, $2, $3)
ON CONFLICT (bank_id, instrument_id) DO UPDATE SET drawee_name = EXCLUDED.drawee_name
""".strip()


async def record_drawee_name(inp: DraweeNameInput, cbs_connector: Any, db_conn: Any = None) -> DraweeNameResult:
    with tracer.start_as_current_span("activity.record_drawee_name") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("instrument_id", inp.instrument_id)
        try:
            info = await cbs_connector.get_account_info(inp.account_number, inp.bank_id)
        except AccountNotFoundError:
            return DraweeNameResult(stored=False, reason="ACCOUNT_NOT_FOUND")
        except Exception as exc:
            log.warning("drawee_name.cbs_unavailable", bank_id=inp.bank_id, instrument_id=inp.instrument_id, error=str(exc))
            return DraweeNameResult(stored=False, reason="CBS_UNAVAILABLE")

        name = (info.holder_name or "").strip()
        if not name:
            return DraweeNameResult(stored=False, reason="NO_NAME")
        if db_conn is None:
            return DraweeNameResult(stored=False, reason="DB_UNAVAILABLE")
        try:
            await db_conn.execute(_SQL, inp.bank_id, to_instrument_uuid(inp.bank_id, inp.instrument_id), name)
        except Exception as exc:
            log.warning("drawee_name.db_error", bank_id=inp.bank_id, instrument_id=inp.instrument_id, error=str(exc))
            return DraweeNameResult(stored=False, reason="DB_ERROR")
        return DraweeNameResult(stored=True)
