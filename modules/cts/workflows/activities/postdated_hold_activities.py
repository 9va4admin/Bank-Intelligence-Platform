"""Activities for PostDatedHoldWorkflow — persist hold state to YugabyteDB.

store_postdated_hold: called on workflow start; records the hold so ops dashboards
                      can show pending post-dated cheques and branch managers can
                      cancel before the release date.

mark_hold_cancelled:  called when cancel_hold signal arrives before release date;
                      marks the hold record as cancelled with reason.
"""
from __future__ import annotations

import structlog
from temporalio import activity

from shared.observability.otel_setup import get_tracer

log = structlog.get_logger()
tracer = get_tracer(__name__)


@activity.defn(name="store_postdated_hold")
async def store_postdated_hold(data: dict) -> None:
    """Persist a new post-dated cheque hold to YugabyteDB cts.postdated_holds."""
    with tracer.start_as_current_span("activity.store_postdated_hold") as span:
        span.set_attribute("bank_id", data.get("bank_id", ""))
        span.set_attribute("instrument_id", data.get("instrument_id", ""))
        from shared.config.config_service import config_service

        instrument_id = data.get("instrument_id", "")
        bank_id = data.get("bank_id", "")
        release_date = data.get("release_date", "")
        held_at = data.get("held_at", "")

        dsn = config_service.get("db.cts.dsn")
        try:
            import asyncpg
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    """
                    INSERT INTO cts.postdated_holds
                        (instrument_id, bank_id, release_date, held_at, status)
                    VALUES ($1, $2, $3::date, $4::timestamptz, 'PENDING')
                    ON CONFLICT (instrument_id) DO NOTHING
                    """,
                    instrument_id, bank_id, release_date, held_at,
                )
            finally:
                await conn.close()
        except Exception as exc:
            log.error(
                "store_postdated_hold.db_error",
                instrument_id=instrument_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise

        log.info(
            "store_postdated_hold.done",
            instrument_id=instrument_id,
            bank_id=bank_id,
            release_date=release_date,
        )


@activity.defn(name="mark_hold_cancelled")
async def mark_hold_cancelled(data: dict) -> None:
    """Mark a post-dated cheque hold as cancelled in YugabyteDB."""
    with tracer.start_as_current_span("activity.mark_hold_cancelled") as span:
        span.set_attribute("bank_id", data.get("bank_id", ""))
        span.set_attribute("instrument_id", data.get("instrument_id", ""))
        from shared.config.config_service import config_service

        instrument_id = data.get("instrument_id", "")
        bank_id = data.get("bank_id", "")
        cancel_reason = data.get("cancel_reason", "")
        cancelled_at = data.get("cancelled_at", "")

        dsn = config_service.get("db.cts.dsn")
        try:
            import asyncpg
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    """
                    UPDATE cts.postdated_holds
                    SET status = 'CANCELLED',
                        cancel_reason = $3,
                        cancelled_at = $4::timestamptz
                    WHERE instrument_id = $1 AND bank_id = $2
                    """,
                    instrument_id, bank_id, cancel_reason, cancelled_at,
                )
            finally:
                await conn.close()
        except Exception as exc:
            log.error(
                "mark_hold_cancelled.db_error",
                instrument_id=instrument_id,
                bank_id=bank_id,
                error=str(exc),
            )
            raise

        log.info(
            "mark_hold_cancelled.done",
            instrument_id=instrument_id,
            bank_id=bank_id,
            cancel_reason=cancel_reason,
        )
