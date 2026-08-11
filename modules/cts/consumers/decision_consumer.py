"""
Decision consumer — reads cts.decisions.{bank_id}.

On every CTS_NGCH_FILED event:
  1. Writes CTS_NGCH_FILED audit record to Immudb (acknowledgement_id + decision)
  2. Updates cts.cheque_instruments with the NGCH acknowledgement_id so
     the ops UI reads the final decision from YugabyteDB, not Temporal.

This decouples the ops UI from the Temporal workflow engine — Temporal is
an internal execution engine, not a data API for frontends.
"""
import structlog

from shared.event_bus.schemas import KafkaEventEnvelope

log = structlog.get_logger()

_HANDLED_EVENT_TYPES = {"CTS_NGCH_FILED"}

_UPDATE_ACK_SQL = """
UPDATE cts.cheque_instruments
   SET ngch_acknowledgement_id = $1,
       final_decision          = $2,
       decision_recorded_at    = NOW()
 WHERE instrument_id = $3
   AND bank_id       = $4
"""


async def handle_decision_event(
    envelope: KafkaEventEnvelope,
    immudb=None,
    db=None,
    consumer_bank_id: str = "",
) -> None:
    """
    Handler registered with EventConsumer for cts.decisions.{bank_id}.

    All failures are caught and logged — the consumer must never crash
    on a single bad message; the Kafka offset is committed either way.
    """
    if consumer_bank_id and envelope.bank_id != consumer_bank_id:
        return

    if envelope.event_type not in _HANDLED_EVENT_TYPES:
        log.debug(
            "decision_consumer.skipped_unknown_event_type",
            event_type=envelope.event_type,
            bank_id=envelope.bank_id,
        )
        return

    payload = envelope.payload
    instrument_id = payload.get("instrument_id", "")
    decision = payload.get("decision", "")
    acknowledgement_id = payload.get("acknowledgement_id", "")
    workflow_id = payload.get("workflow_id", "")

    # 1. Immudb audit write
    if immudb is not None:
        try:
            await immudb.write_event(
                event_type="CTS_NGCH_FILED",
                bank_id=envelope.bank_id,
                payload={
                    "instrument_id": instrument_id,
                    "decision": decision,
                    "acknowledgement_id": acknowledgement_id,
                    "workflow_id": workflow_id,
                },
            )
        except Exception as exc:
            log.error(
                "decision_consumer.immudb_write_failed",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )
    else:
        log.warning(
            "decision_consumer.immudb_unavailable",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )

    # 2. YugabyteDB — store acknowledgement_id so UI reads from DB
    if db is not None:
        try:
            async with await db.acquire() as conn:
                await conn.execute(
                    _UPDATE_ACK_SQL,
                    acknowledgement_id,
                    decision,
                    instrument_id,
                    envelope.bank_id,
                )
        except Exception as exc:
            log.error(
                "decision_consumer.db_update_failed",
                instrument_id=instrument_id,
                bank_id=envelope.bank_id,
                error=str(exc),
            )
    else:
        log.warning(
            "decision_consumer.db_unavailable",
            instrument_id=instrument_id,
            bank_id=envelope.bank_id,
        )


async def run_consumer(
    bank_id: str,
    bootstrap_servers: str,
    immudb=None,
    db=None,
) -> None:
    """Start the EventConsumer for cts.decisions.{bank_id}. Runs until cancelled."""
    from shared.event_bus.consumer import EventConsumer

    consumer = EventConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=f"cg-cts-decision-consumer-{bank_id}",
        bank_id=bank_id,
        topics=[f"cts.decisions.{bank_id}"],
    )
    consumer.connect()
    consumer.register_handler(
        "CTS_NGCH_FILED",
        lambda env: handle_decision_event(env, immudb=immudb, db=db, consumer_bank_id=bank_id),
    )
    log.info("decision_consumer.started", bank_id=bank_id)
    await consumer.run()
