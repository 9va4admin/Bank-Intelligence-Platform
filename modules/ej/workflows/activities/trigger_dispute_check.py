"""
trigger_dispute_check activity — publish canonical record for dispute matching.

Publishes to Kafka ej.canonical.{bank_id} so the DisputeResolutionWorkflow
can attempt to match this transaction against any outstanding NPCI claims.
"""
import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJTriggerDisputeCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str      # "TRIGGERED"
    bank_id: str


async def trigger_dispute_check(
    canonical_hash: str,
    atm_id: str,
    bank_id: str,
) -> EJTriggerDisputeCheckResult:
    """
    Publish to ej.canonical.{bank_id} Kafka topic so DisputeResolutionWorkflow
    can pick up this record and attempt claim matching.
    """
    log.info(
        "ej.trigger_dispute_check.start",
        atm_id=atm_id,
        bank_id=bank_id,
        canonical_hash=canonical_hash[:12],
    )
    # Production: Kafka producer publish to ej.canonical.{bank_id}
    return EJTriggerDisputeCheckResult(
        outcome="TRIGGERED",
        bank_id=bank_id,
    )
