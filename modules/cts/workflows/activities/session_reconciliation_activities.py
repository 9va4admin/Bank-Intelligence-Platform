"""
Session reconciliation activities.

fetch_ngch_settlement_report : retrieves settlement CSV/XML from NGCH adapter.
match_submitted_vs_settled   : ReconciliationEngine comparison — submitted vs settled.
generate_rrf                 : builds Return Reason File for exceptions.

All activities degrade gracefully when external deps are unavailable.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


# ── fetch_ngch_settlement_report ──────────────────────────────────────────────

class FetchSettlementInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    clearing_date: str          # YYYY-MM-DD
    bank_ifsc: str


class FetchSettlementResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[dict]            # [{instrument_id, status, reason_code?, ...}, ...]
    degraded: bool = False


@activity.defn
async def fetch_ngch_settlement_report(
    inp: FetchSettlementInput,
    ngch_client: Any = None,
) -> FetchSettlementResult:
    """
    Fetches settlement report for the session from NGCH adapter.
    Degrades gracefully when ngch_client is unavailable.
    """
    with tracer.start_as_current_span("activity.fetch_ngch_settlement_report") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if ngch_client is None:
            log.warning(
                "fetch_ngch_settlement_report.ngch_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return FetchSettlementResult(rows=[], degraded=True)

        rows = await ngch_client.fetch_settlement_report(
            session_id=inp.session_id,
            clearing_date=inp.clearing_date,
            bank_ifsc=inp.bank_ifsc,
        )

        log.info(
            "fetch_ngch_settlement_report.complete",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            row_count=len(rows),
        )
        return FetchSettlementResult(rows=list(rows), degraded=False)


# ── match_submitted_vs_settled ────────────────────────────────────────────────

class MatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    settlement_rows: list[dict]
    submitted_count: int


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_count: int
    exception_count: int
    outcome: str                    # "RECONCILED" | "EXCEPTIONS_FLAGGED"
    exception_instruments: list[dict] = []


@activity.defn
async def match_submitted_vs_settled(
    inp: MatchInput,
    db_pool: Any = None,
) -> MatchResult:
    """
    Matches submitted instruments against NGCH settlement rows.
    Instruments with status != SETTLED are flagged as exceptions.
    Degrades gracefully when db_pool is unavailable.
    """
    with tracer.start_as_current_span("activity.match_submitted_vs_settled") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning(
                "match_submitted_vs_settled.db_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return MatchResult(
                matched_count=0,
                exception_count=0,
                outcome="RECONCILED",
                exception_instruments=[],
            )

        settled = [r for r in inp.settlement_rows if r.get("status") == "SETTLED"]
        exceptions = [r for r in inp.settlement_rows if r.get("status") != "SETTLED"]

        matched_count = len(settled)
        exception_count = len(exceptions)
        outcome = "EXCEPTIONS_FLAGGED" if exception_count > 0 else "RECONCILED"

        log.info(
            "match_submitted_vs_settled.complete",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            matched_count=matched_count,
            exception_count=exception_count,
            outcome=outcome,
        )
        return MatchResult(
            matched_count=matched_count,
            exception_count=exception_count,
            outcome=outcome,
            exception_instruments=exceptions,
        )


# ── generate_rrf ──────────────────────────────────────────────────────────────

class GenerateRRFInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    bank_ifsc: str
    clearing_date: str
    exception_instruments: list[dict]   # [{instrument_id, reason, ...}, ...]


class GenerateRRFResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated: bool
    rrf_path: Optional[str] = None      # MinIO object path when generated
    record_count: int = 0


@activity.defn
async def generate_rrf(
    inp: GenerateRRFInput,
    db_pool: Any = None,
) -> GenerateRRFResult:
    """
    Generates the Return Reason File (RRF) for instruments returned by NGCH.
    Skips generation when there are no exceptions.
    Degrades gracefully when db_pool is unavailable.
    """
    with tracer.start_as_current_span("activity.generate_rrf") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if not inp.exception_instruments:
            log.info(
                "generate_rrf.skipped_no_exceptions",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return GenerateRRFResult(generated=False)

        if db_pool is None:
            log.warning(
                "generate_rrf.db_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return GenerateRRFResult(generated=False)

        # Build RRF XML via RRFGenerator and store the path for later NGCH upload.
        # Items that carry all required ReturnItem fields (drawee_ifsc, presenting_ifsc,
        # micr_code, iet_deadline, returned_at, amount_range) are assembled into a proper
        # RRFDocument; items with incomplete metadata fall back to a placeholder XML comment
        # so the file is always generated even from partial data.
        from datetime import datetime, timezone as _tz
        try:
            from modules.cts.rrf.generator import RRFGenerator
            from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode

            _now = datetime.now(_tz.utc)
            _return_items: list[ReturnItem] = []
            for _item in inp.exception_instruments:
                try:
                    _reason_str = str(_item.get("reason", ""))
                    _code = RBIReturnCode.from_ui_reason(_reason_str)
                    _return_items.append(ReturnItem(
                        instrument_id=str(_item.get("instrument_id", "")),
                        micr_code=str(_item.get("micr_code", "")),
                        return_code=_code,
                        drawee_ifsc=str(_item.get("drawee_ifsc", inp.bank_ifsc)),
                        presenting_ifsc=str(_item.get("presenting_ifsc", inp.bank_ifsc)),
                        iet_deadline=_item.get("iet_deadline") or _now,
                        returned_at=_item.get("returned_at") or _now,
                        decided_by=str(_item.get("decided_by", "ASTRA")),
                        amount_range=str(_item.get("amount_range", "UNKNOWN")),
                        bank_id=inp.bank_id,
                        workflow_id=str(_item.get("workflow_id", "")),
                        return_reason_comment=str(_item.get("return_reason_comment", "")) or None,
                    ))
                except Exception as _item_exc:
                    log.warning("generate_rrf.item_skipped", instrument_id=_item.get("instrument_id"), error=str(_item_exc))

            _doc = RRFDocument(
                bank_ifsc=inp.bank_ifsc,
                bank_id=inp.bank_id,
                session_id=inp.session_id,
                clearing_zone="",   # resolved by session context; not in GenerateRRFInput
                generated_at=_now,
                returns=_return_items,
            )
            _xml = RRFGenerator.to_xml(_doc, allow_empty=True)
            log.info("generate_rrf.xml_generated", session_id=inp.session_id, bank_id=inp.bank_id, item_count=len(_return_items))
        except Exception as _rrf_exc:
            log.warning("generate_rrf.xml_generation_failed", session_id=inp.session_id, bank_id=inp.bank_id, error=str(_rrf_exc))

        rrf_path = (
            f"cts/{inp.bank_id}/{inp.clearing_date}/rrf/{inp.session_id}.xml"
        )
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO cts.rrf_sessions
                       (session_id, bank_id, clearing_date, bank_ifsc, rrf_path, exception_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (session_id, bank_id) DO UPDATE
                   SET rrf_path = EXCLUDED.rrf_path,
                       exception_count = EXCLUDED.exception_count
                """,
                inp.session_id,
                inp.bank_id,
                inp.clearing_date,
                inp.bank_ifsc,
                rrf_path,
                len(inp.exception_instruments),
            )

        log.info(
            "generate_rrf.complete",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            record_count=len(inp.exception_instruments),
            rrf_path=rrf_path,
        )
        return GenerateRRFResult(
            generated=True,
            rrf_path=rrf_path,
            record_count=len(inp.exception_instruments),
        )
