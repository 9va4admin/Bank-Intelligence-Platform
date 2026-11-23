"""Reminders for overdue post-incident reviews and mitigation actions (docs/design/alerting-blueprint.md, section 18).

One sweep: every overdue review or action that was not reminded within the reminder interval is claimed, and ONE alert goes out through the real alert path
(an incident for the component "alert-reviews", routed, delivered and escalated like any other). When nothing is overdue any more and that incident is still open,
one recovery notice resolves it. If the alert cannot be sent the claim is undone, so the next sweep tries again. The alert names counts only, never an incident or a person.
Settings (Layer 3): alerting.pir_due_days_p0, alerting.pir_due_days_p1, alerting.review_reminder_hours, alerting.review_sweep_seconds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from modules.cts.workflows.activities.platform_health_activities import DispatchAlertInput
from shared.messages import get_message

log = structlog.get_logger()

COMPONENT = "alert-reviews"
Send = Callable[[DispatchAlertInput], Awaitable[Any]]


class SweepResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    reviews: int = 0
    actions: int = 0
    recovered: bool = False
    failed: bool = False


async def _number(config: Any, key: str, default: int) -> int:
    try:
        return int(await config.get(key))
    except Exception:  # noqa: BLE001
        return default


async def sweep_overdue_reviews(pool: Any, bank_id: str, config: Any, send: Send, *, now: Optional[datetime] = None) -> SweepResult:
    moment = now or datetime.now(timezone.utc)
    p0 = await _number(config, "alerting.pir_due_days_p0", 3)
    p1 = await _number(config, "alerting.pir_due_days_p1", 7)
    every = await _number(config, "alerting.review_reminder_hours", 24)
    review_ids = [r["review_id"] for r in await pool.fetch(
        "UPDATE platform.alert_reviews SET last_reminded_at=$2 WHERE bank_id=$1 AND status='DUE' "
        "AND resolved_at + make_interval(days => CASE severity WHEN 'P0' THEN $3::int ELSE $4::int END) < $2 "
        "AND (last_reminded_at IS NULL OR last_reminded_at < $2 - make_interval(hours => $5::int)) RETURNING review_id", bank_id, moment, p0, p1, every)]
    action_ids = [r["action_id"] for r in await pool.fetch(
        "UPDATE platform.alert_actions SET last_reminded_at=$2 WHERE bank_id=$1 AND status IN ('OPEN','IN_PROGRESS') AND due_on < $2::date "
        "AND (last_reminded_at IS NULL OR last_reminded_at < $2 - make_interval(hours => $3::int)) RETURNING action_id", bank_id, moment, every)]
    if review_ids or action_ids:
        try:
            await send(DispatchAlertInput(bank_id=bank_id, event_type="COMPONENT_DOWN", severity="WARN", priority="P2", component=COMPONENT, occurred_at=moment.timestamp(),
                                          message=get_message("ALERT_REVIEW_OVERDUE_MESSAGE", reviews=len(review_ids), actions=len(action_ids))))
        except Exception as exc:  # noqa: BLE001
            log.warning("review_reminders.send_failed", bank_id=bank_id, error_type=type(exc).__name__)
            await pool.execute("UPDATE platform.alert_reviews SET last_reminded_at=NULL WHERE bank_id=$1 AND review_id = ANY($2::text[])", bank_id, review_ids)
            await pool.execute("UPDATE platform.alert_actions SET last_reminded_at=NULL WHERE bank_id=$1 AND action_id = ANY($2::text[])", bank_id, action_ids)
            return SweepResult(failed=True)
        return SweepResult(reviews=len(review_ids), actions=len(action_ids))
    still_overdue = await pool.fetchval(
        "SELECT (SELECT COUNT(*) FROM platform.alert_reviews WHERE bank_id=$1 AND status='DUE' AND resolved_at + make_interval(days => CASE severity WHEN 'P0' THEN $3::int ELSE $4::int END) < $2) "
        "+ (SELECT COUNT(*) FROM platform.alert_actions WHERE bank_id=$1 AND status IN ('OPEN','IN_PROGRESS') AND due_on < $2::date)", bank_id, moment, p0, p1)
    if still_overdue:
        return SweepResult()                                                       # overdue items exist but were reminded recently: nothing to send yet
    open_incident = await pool.fetchval("SELECT 1 FROM platform.alert_incidents WHERE bank_id=$1 AND component=$2 AND state <> 'RESOLVED' LIMIT 1", bank_id, COMPONENT)
    if not open_incident:
        return SweepResult()
    try:
        await send(DispatchAlertInput(bank_id=bank_id, event_type="COMPONENT_RECOVERED", severity="INFO", priority="P3", component=COMPONENT, occurred_at=moment.timestamp(),
                                      message=get_message("ALERT_REVIEW_CAUGHT_UP_MESSAGE")))
    except Exception as exc:  # noqa: BLE001
        log.warning("review_reminders.recovery_failed", bank_id=bank_id, error_type=type(exc).__name__)
        return SweepResult(failed=True)
    return SweepResult(recovered=True)
