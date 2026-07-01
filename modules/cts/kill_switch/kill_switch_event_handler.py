"""
KillSwitchEventHandler — Immudb write + notification dispatch on kill switch state changes.

Listens to Kafka `platform.config.changed` for cts.vision_ai.kill_mode.* keys.
Triggered by the config-service after maker-checker approval of a kill mode change.

Two operations, in strict order:
  1. Write immutable AuditEvent to Immudb (HSM-signed)
  2. Dispatch notifications via NotificationRoutingTable + NotificationDispatcher

The Immudb write ALWAYS completes before notifications are attempted.
A notification failure is non-fatal and logged; the audit trail is never sacrificed.

Per-instrument events (CTS_KILL_SWITCH_APPLIED) are NOT handled here —
those are written directly by alteration.py and decision.py at instrument level.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import structlog

from shared.audit.audit_event import AuditEvent, AuditEventType
from shared.notifications.routing import NotificationRoutingTable

log = structlog.get_logger()


class KillSwitchEventHandler:
    """
    Handles kill switch engage and release events for a single bank.

    Injected dependencies (all required):
      immudb_client  — must expose .write_event(bytes) -> Awaitable[dict]
      dispatcher     — NotificationDispatcher instance (connected with channels)
      hsm            — must expose .sign(bytes) -> bytes
      user_resolver  — callable(bank_id: str) -> list[user] returning all bank users

    user objects must have: .user_id, .role, .email, .phone
    """

    def __init__(
        self,
        bank_id: str,
        immudb_client: Any,
        dispatcher: Any,
        hsm: Any,
        user_resolver: Callable[[str], list[Any]],
    ) -> None:
        self.bank_id = bank_id
        self._immudb = immudb_client
        self._dispatcher = dispatcher
        self._hsm = hsm
        self._user_resolver = user_resolver
        self.routing_table = NotificationRoutingTable()

    async def handle_engage(
        self,
        mode: str,            # "KP" | "KC"
        scope: str,           # "GLOBAL" | "SB_OWN" | "SMB"
        activated_by: str,    # user email or ID who pressed the button
        smb_id: str | None = None,  # populated when scope="SMB"
    ) -> dict[str, Any]:
        """
        Called when the kill switch transitions from NONE → KP or NONE → KC.

        Returns dict with event_id and notification_count for caller logging.
        """
        payload = {
            "mode": mode,
            "scope": scope,
            "activated_by": activated_by,
        }
        if smb_id:
            payload["smb_id"] = smb_id

        # Step 1: Write to Immudb (ALWAYS first — never skip)
        event = AuditEvent(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            bank_id=self.bank_id,
            payload=payload,
        )
        signed_event = event.sign(self._hsm)
        await self._immudb.write_event(signed_event.to_json())

        log.warning(
            "kill_switch.engaged.audit_written",
            bank_id=self.bank_id,
            event_id=signed_event.event_id,
            mode=mode,
            scope=scope,
            activated_by=activated_by,
        )

        # Step 2: Notifications (non-fatal on failure)
        context = {
            "mode": mode,
            "scope": scope,
            "bank_id": self.bank_id,
            "activated_by": activated_by,
            "event_id": signed_event.event_id,
        }
        notification_count = await self._dispatch_notifications(
            event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
            context=context,
        )

        return {
            "event_id": signed_event.event_id,
            "notification_count": notification_count,
        }

    async def handle_release(
        self,
        previous_mode: str,    # "KP" | "KC" — the mode being cleared
        previous_scope: str,   # "GLOBAL" | "SB_OWN" | "SMB"
        released_by: str,      # user email or ID who released
    ) -> dict[str, Any]:
        """
        Called when the kill switch transitions back to NONE.
        """
        payload = {
            "previous_mode": previous_mode,
            "previous_scope": previous_scope,
            "released_by": released_by,
        }

        # Step 1: Write to Immudb (ALWAYS first)
        event = AuditEvent(
            event_type=AuditEventType.CTS_KILL_SWITCH_RELEASED,
            bank_id=self.bank_id,
            payload=payload,
        )
        signed_event = event.sign(self._hsm)
        await self._immudb.write_event(signed_event.to_json())

        log.info(
            "kill_switch.released.audit_written",
            bank_id=self.bank_id,
            event_id=signed_event.event_id,
            previous_mode=previous_mode,
            previous_scope=previous_scope,
            released_by=released_by,
        )

        # Step 2: Notifications
        context = {
            "mode": "NONE",
            "previous_mode": previous_mode,
            "previous_scope": previous_scope,
            "bank_id": self.bank_id,
            "released_by": released_by,
            "event_id": signed_event.event_id,
        }
        notification_count = await self._dispatch_notifications(
            event_type=AuditEventType.CTS_KILL_SWITCH_RELEASED,
            context=context,
        )

        return {
            "event_id": signed_event.event_id,
            "notification_count": notification_count,
        }

    async def _dispatch_notifications(
        self,
        event_type: AuditEventType,
        context: dict[str, Any],
    ) -> int:
        """
        Build and send notifications for the event. Non-fatal on dispatch failure.
        Returns the number of notification requests sent (0 on failure).
        """
        try:
            users = self._user_resolver(self.bank_id)
            requests = self.routing_table.build_requests(
                event_type=event_type,
                bank_id=self.bank_id,
                users=users,
                context=context,
            )
            if not requests:
                return 0
            await self._dispatcher.send_bulk(requests)
            return len(requests)
        except Exception as exc:
            log.error(
                "kill_switch.notification_dispatch_failed",
                bank_id=self.bank_id,
                event_type=event_type.value,
                error=str(exc),
            )
            return 0
