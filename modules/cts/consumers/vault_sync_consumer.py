"""
Vault sync consumer — reads cts.vault.sync.{bank_id}.

On every CTS_VAULT_SYNC_COMPLETE event:
  - outcome=SYNC_COMPLETE     → Immudb write with VAULT_SYNC event type
  - outcome=PARTIAL_FAILURE   → Immudb write with VAULT_SYNC_FAILED event type

Captured stats: signatures_loaded, pps_records_loaded, cheque_leaves_loaded,
integrity_check_passed, triggered_by, started_at, completed_at.

This provides the RBI-auditable record of vault synchronisation history —
when it happened, what was loaded, and whether the integrity check passed.
"""
import structlog

from shared.event_bus.schemas import KafkaEventEnvelope

log = structlog.get_logger()

_HANDLED_EVENT_TYPES = {"CTS_VAULT_SYNC_COMPLETE"}

_OUTCOME_TO_AUDIT_TYPE = {
    "SYNC_COMPLETE": "VAULT_SYNC",
    "PARTIAL_FAILURE": "VAULT_SYNC_FAILED",
}


async def handle_vault_sync_event(
    envelope: KafkaEventEnvelope,
    immudb=None,
    consumer_bank_id: str = "",
) -> None:
    """
    Handler registered with EventConsumer for cts.vault.sync.{bank_id}.

    All failures are caught and logged — consumer never crashes on a bad message.
    """
    if consumer_bank_id and envelope.bank_id != consumer_bank_id:
        return

    if envelope.event_type not in _HANDLED_EVENT_TYPES:
        log.debug(
            "vault_sync_consumer.skipped_unknown_event_type",
            event_type=envelope.event_type,
            bank_id=envelope.bank_id,
        )
        return

    payload = envelope.payload
    outcome = payload.get("outcome", "SYNC_COMPLETE")
    audit_event_type = _OUTCOME_TO_AUDIT_TYPE.get(outcome, "VAULT_SYNC")

    audit_payload = {
        "outcome": outcome,
        "signatures_loaded": payload.get("signatures_loaded", 0),
        "pps_records_loaded": payload.get("pps_records_loaded", 0),
        "cheque_leaves_loaded": payload.get("cheque_leaves_loaded", 0),
        "integrity_check_passed": payload.get("integrity_check_passed", True),
        "triggered_by": payload.get("triggered_by", "SCHEDULED"),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
    }

    if immudb is not None:
        try:
            await immudb.write_event(
                event_type=audit_event_type,
                bank_id=envelope.bank_id,
                payload=audit_payload,
            )
        except Exception as exc:
            log.error(
                "vault_sync_consumer.immudb_write_failed",
                outcome=outcome,
                bank_id=envelope.bank_id,
                error=str(exc),
            )
    else:
        log.warning(
            "vault_sync_consumer.immudb_unavailable",
            outcome=outcome,
            bank_id=envelope.bank_id,
        )


async def run_consumer(
    bank_id: str,
    bootstrap_servers: str,
    immudb=None,
) -> None:
    """Start the EventConsumer for cts.vault.sync.{bank_id}. Runs until cancelled."""
    from shared.event_bus.consumer import EventConsumer

    consumer = EventConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=f"cg-cts-vault-sync-consumer-{bank_id}",
        bank_id=bank_id,
        topics=[f"cts.vault.sync.{bank_id}"],
    )
    consumer.connect()
    consumer.register_handler(
        "CTS_VAULT_SYNC_COMPLETE",
        lambda env: handle_vault_sync_event(env, immudb=immudb, consumer_bank_id=bank_id),
    )
    log.info("vault_sync_consumer.started", bank_id=bank_id)
    await consumer.run()
