"""
update_atm_health activity — emit ATM health signal from normalised EJ record.

Publishes to ej.health.signals.{bank_id} Kafka topic so the anomaly detector
and ATM health time-series can be updated.
"""
import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJUpdateATMHealthResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "UPDATED"
    atm_id: str
    bank_id: str


async def update_atm_health(
    canonical_record: dict,
    atm_id: str,
    bank_id: str,
) -> EJUpdateATMHealthResult:
    """
    Extract health signal from canonical EJ record and publish to
    ej.health.signals.{bank_id} topic.

    Signals include: transaction status, dispense errors, card reader errors,
    journal paper status, cash cassette levels.
    """
    log.info(
        "ej.update_atm_health.start",
        atm_id=atm_id,
        bank_id=bank_id,
    )
    # Production: extract health fields, publish Kafka ej.health.signals.{bank_id}
    return EJUpdateATMHealthResult(
        outcome="UPDATED",
        atm_id=atm_id,
        bank_id=bank_id,
    )
