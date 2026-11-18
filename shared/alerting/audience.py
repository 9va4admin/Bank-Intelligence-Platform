"""From routing targets to concrete deliveries (docs/design/alerting-1b-plan.md).

A routing result names people ("this user", "everyone with this role", an external address) and channels. A delivery needs a place to send to. People are reached on the
bell by their user id; on email and WhatsApp by the contact details of their account (platform.local_auth_accounts). Someone with no contact detail is still reached on
the bell and the gap is reported, never silently skipped. Groups are not supported yet and say so.
"""
from __future__ import annotations

from typing import Any

import structlog

from shared.alerting.bell import resolve_bell_users
from shared.alerting.engine import Target
from shared.alerting.routing_policy import ResolvedTarget

log = structlog.get_logger()

DEFAULT_MAX_RECIPIENTS = 200
DEFAULT_DIRECTORY_DAYS = 90
_CONTACT_COLUMN = {"email": "email", "whatsapp": "phone", "sms": "phone"}      # channels that need an address, and where it comes from


async def _setting(cfg: Any, key: str, default: int) -> int:
    try:
        return int(await cfg.get(key))
    except Exception:
        return default


async def _contacts(pool: Any, bank_id: str, user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    rows = await pool.fetch("SELECT user_id, email, phone FROM platform.local_auth_accounts WHERE bank_id=$1 AND is_active = TRUE AND user_id = ANY($2::text[])",
                            bank_id, user_ids)
    return {r["user_id"]: dict(r) for r in rows}


async def deliverable_targets(targets: list[ResolvedTarget], *, pool: Any, config_service: Any, bank_id: str) -> tuple[list[Target], list[str]]:
    """(deliveries, warnings). Each (channel, recipient) appears once."""
    out: list[Target] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()

    def add(channel: str, recipient: str) -> None:
        if (channel, recipient) not in seen:
            seen.add((channel, recipient))
            out.append(Target(channel, recipient))

    def warn(text: str) -> None:
        if text not in warnings:
            warnings.append(text)

    people: list[tuple[str, list[str]]] = []                    # (user id, channels) to be looked up
    for target in targets:
        if target.kind == "external":
            for channel in target.channels:
                add(channel, target.ref)
        elif target.kind == "user":
            people.append((target.ref, target.channels))
        elif target.kind == "role":
            try:
                users = await resolve_bell_users(pool, bank_id, roles=[target.ref], limit=await _setting(config_service, "alerting.bell_max_recipients", DEFAULT_MAX_RECIPIENTS),
                                                 seen_within_days=await _setting(config_service, "alerting.bell_directory_days", DEFAULT_DIRECTORY_DAYS))
            except Exception as exc:  # noqa: BLE001
                log.warning("audience.role_lookup_failed", bank_id=bank_id, role=target.ref, error=type(exc).__name__)
                warn(f"role_lookup_failed:{target.ref}")
                continue
            people.extend((user, target.channels) for user in users)
        elif target.kind == "group":
            warn(f"group_unsupported:{target.ref}")
        else:                                                   # oncall should have been expanded already
            warn(f"unexpanded:{target.kind}:{target.ref}")

    needs_contact = sorted({user for user, channels in people if any(c in _CONTACT_COLUMN for c in channels)})
    contacts = await _contacts(pool, bank_id, needs_contact) if needs_contact else {}
    for user, channels in people:
        for channel in channels:
            if channel == "bell":
                add("bell", user)
            elif channel in _CONTACT_COLUMN:
                address = (contacts.get(user) or {}).get(_CONTACT_COLUMN[channel])
                if address:
                    add(channel, address)
                else:
                    warn(f"no_contact:{channel}:{user}")
    return out, warnings
