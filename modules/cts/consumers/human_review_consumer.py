"""
Human review consumer — reads cts.human.review.{bank_id}.

On every CTS_HUMAN_REVIEW_REQUIRED event:
  1. Writes CTS_REVIEW_ASSIGNED audit record to Immudb (RBI-auditable event)
  2. Updates cts.cheque_instruments status to IN_HUMAN_REVIEW in YugabyteDB
     so the ops UI can display the work queue and assign to a reviewer.
  3. Triggers allocation based on allocation_mode (Layer 3 config):
       AUTO   — immediately auto-assigns to a reviewer from the active pool
       HYBRID — schedules deferred auto-assign after hybrid_auto_assign_timeout_minutes
       SELF   — no auto-assign; reviewer self-claims from the queue

IET deadline is captured in the audit record so reviewers know urgency.
"""
import time as _time

import structlog

from shared.event_bus.schemas import KafkaEventEnvelope

log = structlog.get_logger()

_HANDLED_EVENT_TYPES = {"CTS_HUMAN_REVIEW_REQUIRED"}

_UPDATE_STATUS_SQL = """
UPDATE cts.cheque_instruments
   SET status            = 'IN_HUMAN_REVIEW',
       review_assigned_at = NOW()
 WHERE instrument_id = $1
   AND bank_id       = $2
"""


async def handle_human_review_event(
    envelope: KafkaEventEnvelope,
    immudb=None,
    db=None,
    redis=None,
    config_svc=None,
    consumer_bank_id: str = "",
) -> None:
    """
    Handler registered with EventConsumer for cts.human.review.{bank_id}.

    All failures are caught and logged — consumer never crashes on a bad message.
    redis and config_svc are optional; when absent, allocation steps are skipped
    and the instrument stays unclaimed (SELF mode fallback).
    """
    if consumer_bank_id and envelope.bank_id != consumer_bank_id:
        return

    if envelope.event_type not in _HANDLED_EVENT_TYPES:
        log.debug(
            "human_review_consumer.skipped_unknown_event_type",
            event_type=envelope.event_type,
            bank_id=envelope.bank_id,
        )
        return

    payload = envelope.payload
    instrument_id = payload.get("instrument_id", "")
    workflow_id = payload.get("workflow_id", "")
    iet_deadline = payload.get("iet_deadline")
    context_bundle = payload.get("context_bundle", {})

    # 1. Immudb audit write — every routing to human review is RBI-auditable
    if immudb is not None:
        try:
            await immudb.write_event(
                event_type="CTS_REVIEW_ASSIGNED",
                bank_id=envelope.bank_id,
                payload={
                    "instrument_id": instrument_id,
                    "workflow_id": workflow_id,
                    "iet_deadline": iet_deadline,
                    "context_bundle": context_bundle,
                },
            )
        except Exception as exc:
            log.error(
                "human_review_consumer.immudb_write_failed",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )
    else:
        log.warning(
            "human_review_consumer.immudb_unavailable",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )

    # 2. YugabyteDB — move instrument to IN_HUMAN_REVIEW so ops UI shows it
    if db is not None:
        try:
            async with await db.acquire() as conn:
                await conn.execute(
                    _UPDATE_STATUS_SQL,
                    instrument_id,
                    envelope.bank_id,
                )
        except Exception as exc:
            log.error(
                "human_review_consumer.db_update_failed",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )
    else:
        log.warning(
            "human_review_consumer.db_unavailable",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )

    # 3. Allocation — AUTO fires immediately; HYBRID schedules deferred; SELF no-ops
    if redis is None:
        log.warning(
            "human_review_consumer.redis_unavailable_skipping_allocation",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )
        return

    cts_config: dict = {}
    if config_svc is not None:
        try:
            cts_config = await config_svc.get_cts_config(envelope.bank_id)
        except Exception as exc:
            log.warning(
                "human_review_consumer.config_fetch_failed",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )

    allocation_mode = cts_config.get("allocation_mode", "SELF")

    if allocation_mode == "SELF":
        log.debug(
            "human_review_consumer.allocation_self_mode_no_op",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )
        return

    from modules.cts.allocation.lock_service import LockService
    from modules.cts.allocation.allocation_service import AllocationService

    lock_svc = LockService(redis_client=redis)
    alloc_svc = AllocationService(lock_service=lock_svc)

    if allocation_mode == "AUTO":
        # Immediately auto-assign from the active reviewer pool
        try:
            available = await lock_svc.get_active_reviewers(envelope.bank_id)
            result = await alloc_svc.auto_assign(instrument_id, available, cts_config)
            if result.claimed:
                log.info(
                    "human_review_consumer.auto_assigned",
                    instrument_id=instrument_id,
                    reviewer_id=result.reviewer_id,
                    bank_id=envelope.bank_id,
                )
            else:
                log.warning(
                    "human_review_consumer.auto_assign_failed_no_active_reviewers",
                    instrument_id=instrument_id,
                    bank_id=envelope.bank_id,
                    active_reviewer_count=len(available),
                )
        except Exception as exc:
            log.error(
                "human_review_consumer.auto_assign_error",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )

    elif allocation_mode == "HYBRID":
        # Schedule deferred auto-assign — fires after hybrid_auto_assign_timeout_minutes
        # if no reviewer has self-claimed by then. pop_due_hybrid_pending() is called
        # on each queue poll in cts_inward.py.
        timeout_minutes = int(cts_config.get("hybrid_auto_assign_timeout_minutes", 5))
        assign_after_ts = _time.time() + timeout_minutes * 60
        try:
            await lock_svc.add_hybrid_pending(envelope.bank_id, instrument_id, assign_after_ts)
            log.info(
                "human_review_consumer.hybrid_pending_scheduled",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                assign_after_ts=assign_after_ts,
                timeout_minutes=timeout_minutes,
            )
        except Exception as exc:
            log.error(
                "human_review_consumer.hybrid_pending_schedule_error",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )


async def run_consumer(
    bank_id: str,
    bootstrap_servers: str,
    immudb=None,
    db=None,
    redis=None,
    config_svc=None,
) -> None:
    """Start the EventConsumer for cts.human.review.{bank_id}. Runs until cancelled."""
    from shared.event_bus.consumer import EventConsumer

    consumer = EventConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=f"cg-cts-human-review-consumer-{bank_id}",
        bank_id=bank_id,
        topics=[f"cts.human.review.{bank_id}"],
    )
    consumer.connect()
    consumer.register_handler(
        "CTS_HUMAN_REVIEW_REQUIRED",
        lambda env: handle_human_review_event(
            env,
            immudb=immudb,
            db=db,
            redis=redis,
            config_svc=config_svc,
            consumer_bank_id=bank_id,
        ),
    )
    log.info("human_review_consumer.started", bank_id=bank_id)
    await consumer.run()
