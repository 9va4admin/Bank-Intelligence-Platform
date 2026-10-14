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


_PAYEE_SQL = """
INSERT INTO cts.outward_payee_name (bank_id, instrument_id, payee_name)
VALUES ($1, $2, $3)
ON CONFLICT (bank_id, instrument_id) DO UPDATE SET payee_name = EXCLUDED.payee_name
""".strip()

_SQL = """
INSERT INTO cts.inward_drawee_name (bank_id, instrument_id, drawee_name)
VALUES ($1, $2, $3)
ON CONFLICT (bank_id, instrument_id) DO UPDATE SET drawee_name = EXCLUDED.drawee_name
""".strip()


async def _lookup_and_store(account_number, bank_id, instrument_id, cbs_connector, db_conn, sql, key, span_name) -> DraweeNameResult:
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("bank_id", bank_id)
        span.set_attribute("instrument_id", instrument_id)
        try:
            info = await cbs_connector.get_account_info(account_number, bank_id)
        except AccountNotFoundError:
            return DraweeNameResult(stored=False, reason="ACCOUNT_NOT_FOUND")
        except Exception as exc:
            log.warning("holder_name.cbs_unavailable", bank_id=bank_id, instrument_id=instrument_id, error=str(exc))
            return DraweeNameResult(stored=False, reason="CBS_UNAVAILABLE")

        name = (info.holder_name or "").strip()
        if not name:
            return DraweeNameResult(stored=False, reason="NO_NAME")
        if db_conn is None:
            return DraweeNameResult(stored=False, reason="DB_UNAVAILABLE")
        try:
            await db_conn.execute(sql, bank_id, key, name)
        except Exception as exc:
            log.warning("holder_name.db_error", bank_id=bank_id, instrument_id=instrument_id, error=str(exc))
            return DraweeNameResult(stored=False, reason="DB_ERROR")
        return DraweeNameResult(stored=True)


async def record_drawee_name(inp: DraweeNameInput, cbs_connector: Any, db_conn: Any = None) -> DraweeNameResult:
    return await _lookup_and_store(inp.account_number, inp.bank_id, inp.instrument_id, cbs_connector, db_conn,
                                   _SQL, to_instrument_uuid(inp.bank_id, inp.instrument_id), "activity.record_drawee_name")


class PayeeNameInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    payee_account_number: str     # the deposit-slip / rear-image account the cheque is credited to
    bank_id: str
    instrument_id: str


async def record_payee_name(inp: PayeeNameInput, cbs_connector: Any, db_conn: Any = None) -> DraweeNameResult:
    """Outward Payee Name: holder of the payee (deposit-slip) account per CBS. Same plain-text
    decision and degradation rules as the inward drawee name; keyed by the text instrument_id."""
    return await _lookup_and_store(inp.payee_account_number, inp.bank_id, inp.instrument_id, cbs_connector, db_conn,
                                   _PAYEE_SQL, inp.instrument_id, "activity.record_payee_name")
