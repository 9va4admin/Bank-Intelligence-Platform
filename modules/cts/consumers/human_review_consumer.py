"""
Human review consumer — reads cts.human.review.{bank_id}.

On every CTS_HUMAN_REVIEW_REQUIRED event:
  1. Writes CTS_REVIEW_ASSIGNED audit record to Immudb (RBI-auditable event)
  2. Updates cts.cheque_instruments status to IN_HUMAN_REVIEW in YugabyteDB
     so the ops UI can display the work queue and assign to a reviewer.

IET deadline is captured in the audit record so reviewers know urgency.
"""
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
    consumer_bank_id: str = "",
) -> None:
    """
    Handler registered with EventConsumer for cts.human.review.{bank_id}.

    All failures are caught and logged — consumer never crashes on a bad message.
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


async def run_consumer(
    bank_id: str,
    bootstrap_servers: str,
    immudb=None,
    db=None,
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
        lambda env: handle_human_review_event(env, immudb=immudb, db=db, consumer_bank_id=bank_id),
    )
    log.info("human_review_consumer.started", bank_id=bank_id)
    await consumer.run()
