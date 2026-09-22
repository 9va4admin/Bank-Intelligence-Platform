"""
Clearing session activities — seal lots, update session status.

seal_all_lots: resolves the ENDORSED lots for a bank/clearing-date (optionally restricted to given PUs), each
enriched with its branch IFSC and NPCI routing number (from the branch's PU), and ensures the
cts.clearing_sessions row exists (creating cts.clearing_zones / cts.processing_centers rows on demand — nothing
in this platform onboards them today, and clearing_sessions.center_id is a required FK).

Historical bug (found on a real run): this used to look up lots by the caller-supplied session_id, which was
either the scanner's EEH session id (lots never match a client-generated one) or a value invented per API call
with no lot ever tagged with it — the query always returned []. Lots are the real grouping unit; the session is
identified by (bank_id, clearing_date, session_type) instead.

update_session_status: marks the clearing session SUBMITTED/EXCEPTION in DB.

Both activities degrade gracefully when db_pool is unavailable (dev / test).
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)

# Fixed namespaces for deterministic ids — never change (would re-key every existing row).
_ZONE_CENTER_NAMESPACE = uuid.UUID("6f1d2a52-5b57-4c0e-9a1b-a57a00000002")
_SESSION_NAMESPACE = uuid.UUID("6f1d2a52-5b57-4c0e-9a1b-a57a00000003")


def clearing_session_uuid(bank_id: str, clearing_date: str, session_type: str) -> uuid.UUID:
    """Deterministic per (bank, date, session_type) — idempotent with the workflow id
    (cts-clearsess-{bank_id}-{clearing_date}-{session_type}), so retriggering reuses the same DB row."""
    return uuid.uuid5(_SESSION_NAMESPACE, f"{bank_id}:{clearing_date}:{session_type}")


async def _ensure_zone_and_center(conn, bank_id: str, zone_id: str) -> str:
    """Get-or-create cts.clearing_zones + cts.processing_centers for this (bank, zone). Neither is populated by
    any onboarding flow today; this is the same self-healing get-or-create pattern as lot assignment."""
    zrow = await conn.fetchrow("SELECT zone_id FROM cts.clearing_zones WHERE zone_id = $1", zone_id)
    if zrow is None:
        await conn.execute(
            "INSERT INTO cts.clearing_zones (zone_id, zone_name, is_active) VALUES ($1, $1, TRUE) "
            "ON CONFLICT (zone_id) DO NOTHING",
            zone_id,
        )
    crow = await conn.fetchrow(
        "SELECT center_id FROM cts.processing_centers WHERE bank_id = $1 AND zone_id = $2",
        bank_id, zone_id,
    )
    if crow is not None:
        return crow["center_id"]
    center_id = uuid.uuid5(_ZONE_CENTER_NAMESPACE, f"{bank_id}:{zone_id}")
    await conn.execute(
        "INSERT INTO cts.processing_centers (center_id, bank_id, zone_id, center_name, center_code, is_active) "
        "VALUES ($1, $2, $3, $4, $5, TRUE) ON CONFLICT (center_id) DO NOTHING",
        center_id, bank_id, zone_id, f"{bank_id.upper()} {zone_id} RPC", f"{bank_id}-{zone_id}"[:32],
    )
    return center_id


# ── seal_all_lots ─────────────────────────────────────────────────────────────

class SealAllLotsInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str             # scanner/API-supplied; kept for audit correlation only, not used to look up lots
    bank_id: str
    pu_ids: list[str]           # empty = every PU of the bank
    clearing_date: str          # YYYY-MM-DD
    session_type: str = "MORNING"


class SealAllLotsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    sealed_lots: list[dict]     # [{lot_id, sequence_number, instrument_count, branch_id, branch_ifsc,
                                 #   pu_id, routing_no, zone_id}, ...]
    session_uuid: str = ""
    status: str                 # "OK" | "DEGRADED"


@activity.defn
async def seal_all_lots(
    inp: SealAllLotsInput,
    db_pool: Any = None,
) -> SealAllLotsResult:
    """
    Resolve every ENDORSED lot for this bank + clearing date (restricted to inp.pu_ids' branches when given),
    ensure the clearing_sessions row exists, and return the lots with the routing metadata NGCH filing needs.
    Degrades gracefully when db_pool is None.
    """
    if isinstance(inp, dict):
        inp = SealAllLotsInput(**inp)
    with tracer.start_as_current_span("activity.seal_all_lots") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning(
                "seal_all_lots.db_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return SealAllLotsResult(sealed_lots=[], status="DEGRADED")

        session_uuid = clearing_session_uuid(inp.bank_id, inp.clearing_date, inp.session_type)

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT l.lot_id, l.sequence_number, l.instrument_count, l.branch_id,
                       b.branch_ifsc, b.pu_id, pu.ngch_participant_code AS routing_no,
                       pu.clearing_zone AS zone_id
                  FROM cts.lots l
                  JOIN cts.branches b ON b.branch_id = l.branch_id AND b.bank_id = l.bank_id
                  JOIN cts.processing_units pu ON pu.pu_id = b.pu_id AND pu.bank_id = l.bank_id
                 WHERE l.bank_id = $1
                   AND l.clearing_date = $2::date
                   AND l.status = 'ENDORSED'
                   AND (cardinality($3::text[]) = 0 OR b.pu_id = ANY($3::text[]))
                """,
                inp.bank_id, inp.clearing_date, inp.pu_ids,
            )
            sealed = [dict(r) for r in rows]

            zones = {r["zone_id"] for r in sealed}
            center_id = None
            for zone_id in zones:
                center_id = await _ensure_zone_and_center(conn, inp.bank_id, zone_id)
            if center_id is None:
                # No lots yet (EMPTY_SESSION path) — still record the session under a bank-default zone so the
                # audit trail has a row, rather than skipping the insert.
                center_id = await _ensure_zone_and_center(conn, inp.bank_id, "DEFAULT")

            await conn.execute(
                """
                INSERT INTO cts.clearing_sessions
                    (session_id, bank_id, center_id, session_date, session_type, clearing_type, status,
                     clearing_date)
                VALUES ($1, $2, $3, $4::date, $5, '14', 'PENDING', $4::date)
                ON CONFLICT (session_id) DO NOTHING
                """,
                session_uuid, inp.bank_id, center_id, inp.clearing_date, inp.session_type,
            )

        log.info(
            "seal_all_lots.complete",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            lot_count=len(sealed),
        )
        return SealAllLotsResult(sealed_lots=sealed, session_uuid=str(session_uuid), status="OK")


# ── mark_lots_submitted ────────────────────────────────────────────────────────

class MarkLotsSubmittedInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    lot_ids: list[str]


@activity.defn
async def mark_lots_submitted(inp: MarkLotsSubmittedInput, db_pool: Any = None) -> None:
    """Move successfully-filed lots past ENDORSED so a later session on the same date never re-picks them."""
    if isinstance(inp, dict):
        inp = MarkLotsSubmittedInput(**inp)
    if db_pool is None or not inp.lot_ids:
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE cts.lots SET status = 'SUBMITTED' WHERE bank_id = $1 AND lot_id = ANY($2::text[])",
            inp.bank_id, inp.lot_ids,
        )


# ── update_session_status ─────────────────────────────────────────────────────

class UpdateSessionStatusInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    bank_id: str
    status: str                 # "SUBMITTED" | "SUBMITTED_TO_SB" | "EXCEPTION" | "EMPTY_SESSION"
    npci_ack_ref: Optional[str] = None
    failure_reason: Optional[str] = None


class UpdateSessionStatusResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    updated: bool
    status: str


@activity.defn
async def update_session_status(
    inp: UpdateSessionStatusInput,
    db_pool: Any = None,
) -> UpdateSessionStatusResult:
    """
    Mark the clearing session record in YugabyteDB with its terminal status.
    Degrades gracefully when db_pool is None.
    """
    if isinstance(inp, dict):
        inp = UpdateSessionStatusInput(**inp)
    with tracer.start_as_current_span("activity.update_session_status") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if db_pool is None:
            log.warning(
                "update_session_status.db_unavailable",
                session_id=inp.session_id,
                bank_id=inp.bank_id,
            )
            return UpdateSessionStatusResult(updated=False, status=inp.status)

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.clearing_sessions
                   SET status            = $1,
                       ngch_session_ref  = $2,
                       failure_reason    = $3
                 WHERE session_id = $4::uuid AND bank_id = $5
                """,
                inp.status,
                inp.npci_ack_ref,
                inp.failure_reason,
                inp.session_id,
                inp.bank_id,
            )

        log.info(
            "update_session_status.updated",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            status=inp.status,
        )
        return UpdateSessionStatusResult(updated=True, status=inp.status)
