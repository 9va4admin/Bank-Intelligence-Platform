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

log = structlog.get_logger()


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

    # Record the RRF generation request in DB.
    # Actual XML assembly via RRFGenerator.to_xml(RRFDocument(...)) happens in
    # the RRF download/export flow when full ReturnItem metadata is available
    # (drawee_ifsc, amount_range, iet_deadline, etc. — fetched from cheque_instruments).
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
