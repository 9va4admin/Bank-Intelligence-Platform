"""Pruning the working copy of alert history so the tables do not grow for ever.

Immudb keeps the legal record (10 years); the database keeps what operators look at. Never removed: an incident that is not resolved (nor the deliveries shown with it), a delivery that is
still in flight or waiting to retry, a critical notification nobody has acknowledged. A run removes at most `batch_size` rows of each kind (so it never
holds the database for long); the next run continues. Zero days for a kind means keep everything of that kind.
Settings (Layer 3): alerting.retention_days, alerting.history_retention_days, alerting.inbox_retention_days, alerting.prune_batch_size.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    incident_days: int = 730          # resolved incidents and finished deliveries
    history_days: int = 730           # component state history
    inbox_days: int = 90              # bell notifications
    batch_size: int = 5000


class PruneResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    incidents: int = 0
    deliveries: int = 0
    state_changes: int = 0
    notifications: int = 0


def _deleted(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])


async def prune_alert_history(pool: Any, bank_id: str, policy: RetentionPolicy) -> PruneResult:
    out = {"incidents": 0, "deliveries": 0, "state_changes": 0, "notifications": 0}
    batch = max(1, policy.batch_size)
    if policy.incident_days > 0:
        out["incidents"] = _deleted(await pool.execute(
            "DELETE FROM platform.alert_incidents WHERE bank_id=$1 AND incident_id IN ("
            "  SELECT incident_id FROM platform.alert_incidents WHERE bank_id=$1 AND state='RESOLVED' "
            "  AND resolved_at < NOW() - make_interval(days => $2) LIMIT $3)", bank_id, policy.incident_days, batch))
        out["deliveries"] = _deleted(await pool.execute(
            "DELETE FROM platform.alert_deliveries WHERE bank_id=$1 AND delivery_id IN ("
            "  SELECT d.delivery_id FROM platform.alert_deliveries d WHERE d.bank_id=$1 AND d.status IN ('SENT','UNDELIVERED','SKIPPED') "
            "  AND d.completed_at < NOW() - make_interval(days => $2) "
            "  AND NOT EXISTS (SELECT 1 FROM platform.alert_incidents i WHERE i.bank_id=d.bank_id AND i.incident_id=d.incident_id AND i.state <> 'RESOLVED') "
            "  LIMIT $3)", bank_id, policy.incident_days, batch))
    if policy.history_days > 0:
        out["state_changes"] = _deleted(await pool.execute(
            "DELETE FROM platform.component_state_history WHERE bank_id=$1 AND id IN ("
            "  SELECT id FROM platform.component_state_history WHERE bank_id=$1 AND changed_at < NOW() - make_interval(days => $2) LIMIT $3)",
            bank_id, policy.history_days, batch))
    if policy.inbox_days > 0:
        out["notifications"] = _deleted(await pool.execute(
            "DELETE FROM platform.user_notifications WHERE bank_id=$1 AND notification_id IN ("
            "  SELECT notification_id FROM platform.user_notifications WHERE bank_id=$1 AND created_at < NOW() - make_interval(days => $2) "
            "  AND NOT (severity='P0' AND acked_at IS NULL) LIMIT $3)", bank_id, policy.inbox_days, batch))
    return PruneResult(**out)


async def load_retention_policy(config_service: Any) -> RetentionPolicy:
    """Read the policy; a missing or malformed value falls back to the default for that setting alone."""
    defaults = RetentionPolicy()
    values: dict[str, int] = {}
    for field_name, key, minimum in (("incident_days", "alerting.retention_days", 0), ("history_days", "alerting.history_retention_days", 0),
                                     ("inbox_days", "alerting.inbox_retention_days", 0), ("batch_size", "alerting.prune_batch_size", 1)):
        try:
            value = int(await config_service.get(key))
        except Exception:  # noqa: BLE001
            continue
        if value >= minimum:
            values[field_name] = value
    return defaults.model_copy(update=values)
