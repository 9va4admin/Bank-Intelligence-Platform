"""The default routing policy and the calendar, both built from configuration.

A bank that has not written a routing policy of its own gets the one the flat settings always described (alerts.email_recipients, alerts.whatsapp_recipients and its
priority floor, the bell roles and their floor), so introducing routing changes nothing for it. Nothing is invented: with nothing configured, no one is named.
"""
from __future__ import annotations

import json
from typing import Any

from shared.alerting.routing_policy import BusinessHours, Calendar, Policy, Rule, TargetSpec

_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFAULT_BELL_ROLES = ["ops_manager", "bank_it_admin"]


async def _get(config_service: Any, key: str) -> Any:
    try:
        return await config_service.get(key)
    except Exception:
        return None


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _list(value: Any) -> list[str]:
    parsed = _json(value) if isinstance(value, str) and value.strip().startswith("[") else value
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, str):
        items = parsed.split(",")
    else:
        items = []
    return [str(x).strip() for x in items if str(x).strip()]


async def load_calendar(config_service: Any) -> Calendar:
    """Timezone, business hours and holidays from alerting.timezone, alerting.business_hours and alerting.holidays; a bad value falls back alone."""
    tz = await _get(config_service, "alerting.timezone")
    hours = _json(await _get(config_service, "alerting.business_hours"))
    holidays = _json(await _get(config_service, "alerting.holidays"))
    business = BusinessHours()
    if isinstance(hours, dict):
        try:
            business = BusinessHours(**{k: v for k, v in hours.items() if k in ("days", "start", "end")})
        except Exception:  # noqa: BLE001
            business = BusinessHours()
    return Calendar(timezone=tz.strip() if isinstance(tz, str) and tz.strip() else "UTC", business=business,
                    holidays=[str(h) for h in holidays] if isinstance(holidays, list) else [])


async def build_default_bank_policy(config_service: Any) -> Policy:
    emails = _list(await _get(config_service, "alerts.email_recipients"))
    phones = _list(await _get(config_service, "alerts.whatsapp_recipients"))
    wa_floor = str(await _get(config_service, "alerts.whatsapp_min_priority") or "P0").strip().upper()
    bell_floor = str(await _get(config_service, "alerting.bell_min_priority") or "P3").strip().upper()
    roles = _list(await _get(config_service, "alerting.bell_roles")) or list(DEFAULT_BELL_ROLES)
    rules: list[Rule] = []
    for severity in ("P0", "P1", "P2", "P3"):
        targets = [TargetSpec(kind="external", ref=e, channels=["email"]) for e in emails]
        if _RANK[severity] <= _RANK.get(wa_floor, 0):
            targets += [TargetSpec(kind="external", ref=p, channels=["whatsapp"]) for p in phones]
        if _RANK[severity] <= _RANK.get(bell_floor, 3):
            targets += [TargetSpec(kind="role", ref=r, channels=["bell"]) for r in roles]
        rules.append(Rule(id=f"default-{severity.lower()}", severities=[severity], targets=targets))
    return Policy(rules=rules)
