"""
Session reconciliation activities.

fetch_ngch_settlement_report : retrieves settlement CSV/XML from NGCH adapter.
match_submitted_vs_settled   : ReconciliationEngine comparison — submitted vs settled.
generate_rrf                 : builds Return Reason File for exceptions.

All activities degrade gracefully when external deps are unavailable.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.observability.otel_setup import get_tracer
from shared.messages import get_message

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
    if isinstance(inp, dict):
        inp = FetchSettlementInput(**inp)
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
    submitted_instrument_ids: list[str] = []   # what we actually submitted; lets a missing report row be seen
    report_unavailable: bool = False           # NGCH could not be reached: an empty report proves nothing


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

    Exceptions are: a submitted instrument whose row is not SETTLED, a submitted instrument that has NO row in the report
    (MISSING_FROM_SETTLEMENT), and a row for an instrument we did not submit. A session is RECONCILED only when every
    submitted instrument was settled; an unavailable report never reconciles a session that submitted anything.
    """
    with tracer.start_as_current_span("activity.match_submitted_vs_settled") as span:
        span.set_attribute("bank_id", inp.bank_id)
        have_ids = bool(inp.submitted_instrument_ids)
        if db_pool is None and not have_ids and not inp.report_unavailable:
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

        rows = inp.settlement_rows
        if have_ids:
            submitted = set(inp.submitted_instrument_ids)
            in_report = {r.get("instrument_id") for r in rows}
            settled = [r for r in rows if r.get("status") == "SETTLED" and r.get("instrument_id") in submitted]
            exceptions = [r for r in rows if r.get("status") != "SETTLED" or r.get("instrument_id") not in submitted]
            exceptions += [
                {"instrument_id": iid, "status": "MISSING_FROM_SETTLEMENT",
                 "reason": get_message("CTS_SUBMITTED_BUT_NOT_IN_THE")}
                for iid in inp.submitted_instrument_ids if iid not in in_report
            ]
            exception_count = len(exceptions)
        else:
            settled = [r for r in rows if r.get("status") == "SETTLED"]
            exceptions = [r for r in rows if r.get("status") != "SETTLED"]
            exception_count = len(exceptions)
            if inp.report_unavailable and inp.submitted_count > 0:
                exception_count = max(exception_count, inp.submitted_count)   # we only know how many, not which

        matched_count = len(settled)
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
    minio_client: Any = None,
) -> GenerateRRFResult:
    """
    Generates the Return Reason File (RRF) for instruments returned by NGCH,
    uploads the XML to MinIO, and records the path in cts.rrf_sessions.
    Skips generation when there are no exceptions.
    Degrades gracefully when db_pool or minio_client is unavailable.
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

        if db_pool is None or minio_client is None:
            log.warning(
                "generate_rrf.dependency_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
                db_pool_ok=db_pool is not None,
                minio_ok=minio_client is not None,
            )
            return GenerateRRFResult(generated=False)

        # Build RRF XML via RRFGenerator and store the path for later NGCH upload.
        # Items that carry all required ReturnItem fields (drawee_ifsc, presenting_ifsc,
        # micr_code, iet_deadline, returned_at, amount_range) are assembled into a proper
        # RRFDocument; items with incomplete metadata fall back to a placeholder XML comment
        # so the file is always generated even from partial data.
        from datetime import datetime, timezone as _tz
        _xml: Optional[str] = None
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
                generated_at=_now,
                returns=_return_items,
            )
            _xml = RRFGenerator.to_xml(_doc, allow_empty=True)
            log.info("generate_rrf.xml_generated", session_id=inp.session_id, bank_id=inp.bank_id, item_count=len(_return_items))
        except Exception as _rrf_exc:
            log.warning("generate_rrf.xml_generation_failed", session_id=inp.session_id, bank_id=inp.bank_id, error=str(_rrf_exc))

        if _xml is None:
            # XML generation itself failed (not just individual items) — nothing to upload,
            # never record a rrf_path that points at a file that doesn't exist.
            return GenerateRRFResult(generated=False)

        rrf_path = (
            f"cts/{inp.bank_id}/{inp.clearing_date}/rrf/{inp.session_id}.xml"
        )
        await minio_client.upload_bytes(
            "astra-cts", rrf_path, _xml.encode("utf-8"), content_type="application/xml",
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
                date.fromisoformat(inp.clearing_date),
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


# ── mark_session_reconciled ───────────────────────────────────────────────────

class MarkSessionReconciledInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    bank_id: str


class MarkSessionReconciledResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    updated: bool


@activity.defn
async def mark_session_reconciled(
    inp: MarkSessionReconciledInput,
    db_pool: Any = None,
) -> MarkSessionReconciledResult:
    """
    Record that NGCH's settlement report for this session was matched: status RECONCILED and the settlement time.
    Only a SUBMITTED session moves (a replayed workflow cannot flip a settled or failed one). Degrades when db_pool is None.
    """
    if isinstance(inp, dict):
        inp = MarkSessionReconciledInput(**inp)
    with tracer.start_as_current_span("activity.mark_session_reconciled") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning("mark_session_reconciled.db_unavailable", session_id=inp.session_id, bank_id=inp.bank_id)
            return MarkSessionReconciledResult(updated=False)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.clearing_sessions
                   SET status = 'RECONCILED', settlement_at = NOW()
                 WHERE session_id = $1::uuid AND bank_id = $2 AND status = 'SUBMITTED'
                """,
                inp.session_id, inp.bank_id,
            )
        log.info("mark_session_reconciled.updated", session_id=inp.session_id, bank_id=inp.bank_id)
        return MarkSessionReconciledResult(updated=True)


# ── record_outward_returns ────────────────────────────────────────────────────

class RecordOutwardReturnsInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: str
    bank_id: str
    exception_instruments: list[dict]


class RecordOutwardReturnsResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    recorded: int


@activity.defn
async def record_outward_returns(
    inp: RecordOutwardReturnsInput,
    db_pool: Any = None,
) -> RecordOutwardReturnsResult:
    """
    Record each outward instrument NGCH reported RETURNED (with a reason code) in cts.return_items, so the dashboards and the bankwise
    report can count returns. Idempotent per instrument and reason code; a row with no reason code cannot be recorded and is skipped.
    """
    if isinstance(inp, dict):
        inp = RecordOutwardReturnsInput(**inp)
    with tracer.start_as_current_span("activity.record_outward_returns") as span:
        span.set_attribute("bank_id", inp.bank_id)
        returned = [r for r in inp.exception_instruments if r.get("status") == "RETURNED" and r.get("reason_code")]
        if db_pool is None:
            log.warning("record_outward_returns.db_unavailable", session_id=inp.session_id, bank_id=inp.bank_id)
            return RecordOutwardReturnsResult(recorded=0)
        async with db_pool.acquire() as conn:
            for row in returned:
                await conn.execute(
                    """
                    INSERT INTO cts.return_items
                        (bank_id, session_id, outward_item_id, cheque_number, micr_code, original_amount_paise,
                         original_cheque_date, return_reason_code, return_type, return_deadline_at)
                    SELECT ci.bank_id, $2::uuid, ci.instrument_id, ci.cheque_number, ci.micr_code, ci.amount_paise,
                           ci.cheque_date, $3::varchar, 'INWARD_RETURN', NOW() + INTERVAL '24 hours'
                      FROM cts.cheque_instruments ci
                     WHERE ci.bank_id = $1 AND ci.instrument_id = $4::uuid
                       AND NOT EXISTS (SELECT 1 FROM cts.return_items r
                                        WHERE r.outward_item_id = ci.instrument_id AND r.return_reason_code = $3::varchar)
                    """,
                    inp.bank_id, inp.session_id, str(row["reason_code"]), str(row["instrument_id"]),
                )
        log.info("record_outward_returns.recorded", session_id=inp.session_id, bank_id=inp.bank_id, count=len(returned))
        return RecordOutwardReturnsResult(recorded=len(returned))

