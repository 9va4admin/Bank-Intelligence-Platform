"""The bell channel and who is on it.

BellChannel plugs into NotificationDispatcher like the email and WhatsApp channels: the recipient is a user id, and sending means writing into
that user's inbox (shared/alerting/inbox.py). resolve_bell_users finds the people a bank wants on the bell: the active users of the configured roles.
"""
from __future__ import annotations

from typing import Any

from shared.alerting.inbox import InboxStore
from shared.alerting.templates import AlertContent, TemplateSettings, render_short
from shared.messages import get_message


class BellChannel:
    def __init__(self, store: InboxStore | None, template_settings: TemplateSettings) -> None:
        self._store, self._settings = store, template_settings

    async def send(self, request) -> dict[str, Any]:
        if self._store is None:
            raise RuntimeError(get_message("ALERT_BELL_NOT_CONNECTED"))
        ctx = request.context
        priority = str(getattr(request, "priority", "") or "P2")
        content = AlertContent(bank_id=str(ctx.get("bank_id", "")), severity=priority, component=str(ctx.get("component", "")),
                               event_type=str(ctx.get("event_type", "")), message=str(ctx.get("message", "")),
                               incident_id=str(ctx.get("incident_id", "")), occurred_at=float(ctx.get("occurred_at") or 0.0))
        title, body = render_short(content, self._settings)
        incident_id = content.incident_id or None
        link = self._settings.incident_path.format(incident_id=incident_id) if incident_id else None
        notification_id = await self._store.add(bank_id=content.bank_id, user_id=request.recipient, severity=priority if priority in ("P0", "P1", "P2", "P3") else "P2",
                                                title=title, body=body, action_link=link, incident_id=incident_id)
        return {"message_id": notification_id, "status": "sent"}


async def resolve_bell_users(pool: Any, bank_id: str, *, roles: list[str], limit: int, seen_within_days: int = 0) -> list[str]:
    """Active users of the given roles in this bank: locally managed accounts, plus everyone who has signed in (identity-provider users included, from
    platform.user_directory) within `seen_within_days` (0 = no limit). Each person once."""
    if not roles:
        return []
    rows = await pool.fetch(
        "SELECT user_id FROM ("
        "  SELECT user_id FROM platform.local_auth_accounts WHERE bank_id=$1 AND is_active = TRUE AND role = ANY($2::text[]) "
        "  UNION "
        "  SELECT user_id FROM platform.user_directory WHERE bank_id=$1 AND is_active = TRUE AND role = ANY($2::text[]) "
        "    AND ($4::int <= 0 OR last_seen > NOW() - make_interval(days => $4::int))"
        ") people ORDER BY user_id LIMIT $3",
        bank_id, list(roles), max(1, limit), int(seen_within_days))
    return [r["user_id"] for r in rows]
