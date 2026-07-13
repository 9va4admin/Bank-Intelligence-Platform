"""
NotificationRoutingTable — maps AuditEventType → recipient roles → channels.

This is the single source of truth for who gets notified, on which channel,
at what priority, and whether to auto-create an incident ticket.

Usage:
    rt = NotificationRoutingTable()
    spec = rt.get_spec(AuditEventType.CTS_KILL_SWITCH_ENGAGED)
    requests = rt.build_requests(
        event_type=AuditEventType.CTS_KILL_SWITCH_ENGAGED,
        bank_id="kotak-mah",
        users=[...],      # list of user objects with .role, .email, .phone, .user_id
        context={"mode": "KC", "scope": "GLOBAL"},
    )

Design principles:
  - Every AuditEventType has exactly one RoutingSpec (even if notify=False)
  - build_requests() returns NotificationRequest objects ready for dispatcher.send()
  - Bell channel uses user_id as recipient; Email uses email; WhatsApp uses phone
  - audit-only events (notify=False) return [] from build_requests()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from shared.audit.audit_event import AuditEventType
from shared.notifications.dispatcher import NotificationRequest


class Priority(str, Enum):
    P0 = "P0"   # 30-min SLA, immediate WhatsApp + Email
    P1 = "P1"   # 4-hr SLA, Email + WhatsApp on escalation
    P2 = "P2"   # 24-hr SLA, Email only
    P3 = "P3"   # No SLA, Bell or Email informational


class Channel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    BELL = "bell"


@dataclass(frozen=True)
class RecipientRule:
    role: str                       # matches Role enum value string e.g. "BANK_IT_ADMIN"
    channels: tuple[Channel, ...]   # ordered: first = primary
    template_suffix: str            # appended to event domain prefix for template_id


@dataclass(frozen=True)
class RoutingSpec:
    event_type: AuditEventType
    priority: Priority
    notify: bool                        # False = audit-only, no NotificationRequest generated
    create_incident: bool
    recipients: tuple[RecipientRule, ...]  # empty when notify=False


def _r(role: str, channels: list[Channel], suffix: str) -> RecipientRule:
    return RecipientRule(role=role, channels=tuple(channels), template_suffix=suffix)


def _spec(
    event_type: AuditEventType,
    priority: Priority,
    notify: bool,
    create_incident: bool,
    recipients: list[RecipientRule] | None = None,
) -> RoutingSpec:
    return RoutingSpec(
        event_type=event_type,
        priority=priority,
        notify=notify,
        create_incident=create_incident,
        recipients=tuple(recipients or []),
    )


def _build_routing_table() -> dict[AuditEventType, RoutingSpec]:
    E = AuditEventType
    P = Priority
    Ch = Channel

    return {

        # ── CTS Kill Switch ────────────────────────────────────────────────────
        E.CTS_KILL_SWITCH_ENGAGED: _spec(
            E.CTS_KILL_SWITCH_ENGAGED, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("BANK_IT_ADMIN",       [Ch.EMAIL, Ch.WHATSAPP], "IT_ADMIN"),
                _r("OPS_MANAGER",         [Ch.EMAIL, Ch.WHATSAPP], "OPS_MGR"),
                _r("COMPLIANCE_OFFICER",  [Ch.EMAIL],               "COMPLIANCE"),
            ],
        ),
        E.CTS_KILL_SWITCH_RELEASED: _spec(
            E.CTS_KILL_SWITCH_RELEASED, P.P3, notify=True, create_incident=False,
            recipients=[
                _r("BANK_IT_ADMIN",       [Ch.EMAIL], "IT_ADMIN"),
                _r("OPS_MANAGER",         [Ch.EMAIL], "OPS_MGR"),
                _r("COMPLIANCE_OFFICER",  [Ch.EMAIL], "COMPLIANCE"),
            ],
        ),
        E.CTS_KILL_SWITCH_APPLIED: _spec(
            E.CTS_KILL_SWITCH_APPLIED, P.P3, notify=False, create_incident=False,
        ),

        # ── CTS Inward — IET ──────────────────────────────────────────────────
        E.CTS_IET_WATCHDOG_FIRED: _spec(
            E.CTS_IET_WATCHDOG_FIRED, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("OPS_REVIEWER",  [Ch.BELL, Ch.WHATSAPP],        "REVIEWER"),
                _r("OPS_MANAGER",   [Ch.BELL, Ch.WHATSAPP, Ch.EMAIL], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.WHATSAPP],                  "IT_ADMIN"),
            ],
        ),

        # ── CTS Inward — Human review ─────────────────────────────────────────
        E.CTS_REVIEW_ASSIGNED: _spec(
            E.CTS_REVIEW_ASSIGNED, P.P3, notify=True, create_incident=False,
            recipients=[
                _r("OPS_REVIEWER", [Ch.BELL, Ch.WHATSAPP], "REVIEWER"),
            ],
        ),
        E.CTS_REVIEW_TIMEOUT: _spec(
            E.CTS_REVIEW_TIMEOUT, P.P1, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.EMAIL, Ch.WHATSAPP], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL],               "IT_ADMIN"),
            ],
        ),
        E.CTS_HUMAN_REVIEW_ESCALATED: _spec(
            E.CTS_HUMAN_REVIEW_ESCALATED, P.P3, notify=False, create_incident=False,
        ),
        E.CTS_HUMAN_REVIEW_RESOLVED: _spec(
            E.CTS_HUMAN_REVIEW_RESOLVED, P.P3, notify=False, create_incident=False,
        ),

        # ── CTS Outward — Outward Q decisions (audit-only) ────────────────────
        E.CTS_OUTWARD_QUEUE_DECISION: _spec(
            E.CTS_OUTWARD_QUEUE_DECISION, P.P3, notify=False, create_incident=False,
        ),

        # ── CTS Inward — other decisions (audit-only) ─────────────────────────
        E.CTS_DECISION: _spec(
            E.CTS_DECISION, P.P3, notify=False, create_incident=False,
        ),
        E.CTS_VAULT_MISS: _spec(
            E.CTS_VAULT_MISS, P.P3, notify=False, create_incident=False,
        ),

        # ── CTS NGCH / transport ──────────────────────────────────────────────
        E.CTS_NGCH_FILED: _spec(
            E.CTS_NGCH_FILED, P.P3, notify=False, create_incident=False,
        ),
        E.CTS_NGCH_TERMINAL_FAILURE: _spec(
            E.CTS_NGCH_TERMINAL_FAILURE, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.EMAIL, Ch.WHATSAPP], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL, Ch.WHATSAPP], "IT_ADMIN"),
            ],
        ),
        E.CTS_NGCH_CERT_EXPIRED: _spec(
            E.CTS_NGCH_CERT_EXPIRED, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("BANK_IT_ADMIN", [Ch.WHATSAPP, Ch.EMAIL], "IT_ADMIN"),
                _r("OPS_MANAGER",   [Ch.WHATSAPP, Ch.EMAIL], "OPS_MGR"),
            ],
        ),

        # ── CBS connector ──────────────────────────────────────────────────────
        E.CBS_UNREACHABLE: _spec(
            E.CBS_UNREACHABLE, P.P1, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.WHATSAPP, Ch.BELL], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL, Ch.BELL],     "IT_ADMIN"),
            ],
        ),
        E.CBS_AUTH_FAILED: _spec(
            E.CBS_AUTH_FAILED, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("BANK_IT_ADMIN", [Ch.WHATSAPP, Ch.EMAIL], "IT_ADMIN"),
                _r("OPS_MANAGER",   [Ch.WHATSAPP],            "OPS_MGR"),
            ],
        ),
        E.CBS_RECOVERED: _spec(
            E.CBS_RECOVERED, P.P3, notify=True, create_incident=False,
            recipients=[
                _r("OPS_MANAGER", [Ch.BELL], "OPS_MGR"),
            ],
        ),

        # ── Vault ──────────────────────────────────────────────────────────────
        E.VAULT_STALE: _spec(
            E.VAULT_STALE, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.WHATSAPP, Ch.EMAIL], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.WHATSAPP, Ch.EMAIL], "IT_ADMIN"),
            ],
        ),
        E.VAULT_INTEGRITY_FAIL: _spec(
            E.VAULT_INTEGRITY_FAIL, P.P0, notify=True, create_incident=True,
            recipients=[
                _r("BANK_IT_ADMIN", [Ch.WHATSAPP, Ch.EMAIL], "IT_ADMIN"),
                _r("OPS_MANAGER",   [Ch.WHATSAPP, Ch.EMAIL], "OPS_MGR"),
            ],
        ),
        E.VAULT_SYNC_FAILED: _spec(
            E.VAULT_SYNC_FAILED, P.P1, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.EMAIL, Ch.WHATSAPP], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL],               "IT_ADMIN"),
            ],
        ),
        E.VAULT_SYNC: _spec(
            E.VAULT_SYNC, P.P3, notify=False, create_incident=False,
        ),

        # ── EJ module ──────────────────────────────────────────────────────────
        E.EJ_PARSED: _spec(
            E.EJ_PARSED, P.P3, notify=False, create_incident=False,
        ),
        E.EJ_DISPUTE_RESOLVED: _spec(
            E.EJ_DISPUTE_RESOLVED, P.P3, notify=False, create_incident=False,
        ),
        E.EJ_DISPUTE_ESCALATED: _spec(
            E.EJ_DISPUTE_ESCALATED, P.P2, notify=True, create_incident=False,
            recipients=[
                _r("OPS_MANAGER",    [Ch.BELL, Ch.EMAIL], "OPS_MGR"),
                _r("FRAUD_ANALYST",  [Ch.BELL],            "ANALYST"),
            ],
        ),
        E.EJ_ATM_HEALTH_CHANGED: _spec(
            E.EJ_ATM_HEALTH_CHANGED, P.P1, notify=True, create_incident=True,
            recipients=[
                _r("OPS_MANAGER",   [Ch.EMAIL, Ch.WHATSAPP], "OPS_MGR"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL],               "IT_ADMIN"),
                _r("ML_ENGINEER",   [Ch.EMAIL],               "ML_ENG"),
            ],
        ),
        E.EJ_OEM_UNKNOWN: _spec(
            E.EJ_OEM_UNKNOWN, P.P2, notify=True, create_incident=True,
            recipients=[
                _r("ML_ENGINEER",   [Ch.BELL, Ch.EMAIL], "ML_ENG"),
                _r("BANK_IT_ADMIN", [Ch.EMAIL],           "IT_ADMIN"),
            ],
        ),

        # ── MCP Connection lifecycle ───────────────────────────────────────────
        E.MCP_CONN_CREATED: _spec(
            E.MCP_CONN_CREATED, P.P3, notify=False, create_incident=False,
        ),
        E.MCP_CONN_UPDATED: _spec(
            E.MCP_CONN_UPDATED, P.P3, notify=False, create_incident=False,
        ),
        E.MCP_CONN_DELETED: _spec(
            E.MCP_CONN_DELETED, P.P3, notify=True, create_incident=False,
            recipients=[
                _r("BANK_IT_ADMIN", [Ch.EMAIL], "IT_ADMIN"),
            ],
        ),
        E.MCP_CONN_TESTED_OK: _spec(
            E.MCP_CONN_TESTED_OK, P.P3, notify=False, create_incident=False,
        ),
        E.MCP_CONN_TESTED_FAIL: _spec(
            E.MCP_CONN_TESTED_FAIL, P.P2, notify=True, create_incident=False,
            recipients=[
                _r("BANK_IT_ADMIN", [Ch.EMAIL, Ch.BELL], "IT_ADMIN"),
                _r("OPS_MANAGER",   [Ch.BELL],            "OPS_MGR"),
            ],
        ),
        E.MCP_CONN_SYNC_TRIGGERED: _spec(
            E.MCP_CONN_SYNC_TRIGGERED, P.P3, notify=False, create_incident=False,
        ),

        # ── Platform / infra ───────────────────────────────────────────────────
        E.CONFIG_CHANGE: _spec(
            E.CONFIG_CHANGE, P.P3, notify=False, create_incident=False,
        ),
        E.DIAGNOSTIC_ACCESS: _spec(
            E.DIAGNOSTIC_ACCESS, P.P3, notify=False, create_incident=False,
        ),
        E.BANK_ONBOARDED: _spec(
            E.BANK_ONBOARDED, P.P3, notify=False, create_incident=False,
        ),
    }


class NotificationRoutingTable:
    """
    Immutable routing table — instantiate once at startup, reuse for every event.

    get_spec(event_type) → RoutingSpec
    build_requests(event_type, bank_id, users, context) → list[NotificationRequest]
    """

    def __init__(self) -> None:
        self._table: dict[AuditEventType, RoutingSpec] = _build_routing_table()

    def get_spec(self, event_type: AuditEventType) -> RoutingSpec:
        return self._table[event_type]

    def build_requests(
        self,
        event_type: AuditEventType,
        bank_id: str,
        users: list[Any],         # objects with .role, .email, .phone, .user_id
        context: dict[str, Any],
    ) -> list[NotificationRequest]:
        """
        Build NotificationRequest objects for all users that match the routing spec.

        Returns [] when spec.notify is False (audit-only events).
        Bell channel → recipient = user.user_id
        Email channel → recipient = user.email
        WhatsApp channel → recipient = user.phone
        """
        spec = self.get_spec(event_type)
        if not spec.notify:
            return []

        # Index users by role for O(1) lookup
        users_by_role: dict[str, list[Any]] = {}
        for user in users:
            role = user.role if isinstance(user.role, str) else user.role.value
            users_by_role.setdefault(role, []).append(user)

        requests: list[NotificationRequest] = []
        event_prefix = _template_prefix(event_type)

        for rule in spec.recipients:
            matched_users = users_by_role.get(rule.role, [])
            for user in matched_users:
                for channel in rule.channels:
                    recipient = _recipient_for_channel(channel, user)
                    if not recipient:
                        continue
                    template_id = f"{event_prefix}_{rule.template_suffix}"
                    requests.append(NotificationRequest(
                        channel=channel.value,
                        recipient=recipient,
                        template_id=template_id,
                        context=context,
                    ))

        return requests


def _recipient_for_channel(channel: Channel, user: Any) -> str | None:
    if channel == Channel.EMAIL:
        return getattr(user, "email", None)
    if channel == Channel.WHATSAPP:
        return getattr(user, "phone", None)
    if channel == Channel.BELL:
        return getattr(user, "user_id", None)
    return None


def _template_prefix(event_type: AuditEventType) -> str:
    """Map AuditEventType to its notification template prefix."""
    _prefixes: dict[AuditEventType, str] = {
        AuditEventType.CTS_KILL_SWITCH_ENGAGED:   "CTS_KS_ENGAGED",
        AuditEventType.CTS_KILL_SWITCH_RELEASED:  "CTS_KS_RELEASED",
        AuditEventType.CTS_IET_WATCHDOG_FIRED:    "CTS_IET_WATCHDOG",
        AuditEventType.CTS_REVIEW_ASSIGNED:       "CTS_HR_ASSIGNED",
        AuditEventType.CTS_REVIEW_TIMEOUT:        "CTS_HR_TIMEOUT",
        AuditEventType.CTS_NGCH_TERMINAL_FAILURE: "CTS_NGCH_TERMINAL",
        AuditEventType.CTS_NGCH_CERT_EXPIRED:     "CTS_NGCH_CERT",
        AuditEventType.CBS_UNREACHABLE:           "CBS_UNREACHABLE",
        AuditEventType.CBS_AUTH_FAILED:           "CBS_AUTH_FAILED",
        AuditEventType.CBS_RECOVERED:             "CBS_RECOVERED",
        AuditEventType.VAULT_STALE:               "VAULT_STALE",
        AuditEventType.VAULT_INTEGRITY_FAIL:      "VAULT_INTEGRITY",
        AuditEventType.VAULT_SYNC_FAILED:         "VAULT_SYNC_FAILED",
        AuditEventType.EJ_DISPUTE_ESCALATED:      "EJ_DISPUTE_ESCALATED",
        AuditEventType.EJ_ATM_HEALTH_CHANGED:     "EJ_ATM",
        AuditEventType.EJ_OEM_UNKNOWN:            "EJ_OEM_UNKNOWN",
    }
    return _prefixes.get(event_type, event_type.value)
