"""Go-Live alerting readiness: the machine-checkable items of the alerting blueprint (section 19), shown on the existing Go-Live screen.

Each check answers one question and never breaks the others: if a store cannot be read the item is a warning that says so.
Settings (Layer 3): alerting.oncall_gap_days, alerting.oncall_gap_step_minutes, alerting.readiness_test_send_days,
alerting.readiness_open_incident_hours, alerting.public_mail_hosts.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.alerting.policy_defaults import build_default_bank_policy, load_calendar
from shared.alerting.routing_policy import validate_policy
from shared.messages import get_message

log = structlog.get_logger()

Status = Literal["PASS", "WARN", "FAIL", "SKIP"]

# the plain-language reason for each way a policy can be refused (the same wording the routing screen shows)
_PROBLEM_KEYS = {
    "p0_not_covered": "UI_ALERTING_RT_CODE_P0_NOT_COVERED", "p0_needs_a_target": "UI_ALERTING_RT_CODE_P0_TARGET", "p0_needs_two_channels": "UI_ALERTING_RT_CODE_P0_CHANNELS",
    "duplicate_rule_id": "UI_ALERTING_RT_CODE_DUPLICATE", "unknown_channel": "UI_ALERTING_RT_CODE_CHANNEL", "escalation_not_increasing": "UI_ALERTING_RT_CODE_ESCALATION_ORDER",
    "negative_minutes": "UI_ALERTING_RT_CODE_NEGATIVE", "quiet_hold_not_allowed": "UI_ALERTING_RT_CODE_HOLD", "escalation_must_end_with_a_person": "UI_ALERTING_RT_CODE_ESCALATION_PERSON",
}
_ROUTING_URL, _ONCALL_URL, _SETTINGS_URL = "/admin/alert-routing", "/ops/oncall", "/admin/alert-settings"


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    check_id: str
    label: str
    status: Status
    detail: str
    action_url: Optional[str] = None


def _item(check_id: str, label_key: str, status: Status, detail: str, action_url: Optional[str]) -> ReadinessCheck:
    return ReadinessCheck(check_id=check_id, label=get_message(label_key), status=status, detail=detail, action_url=action_url)


def _unavailable(check_id: str, label_key: str, action_url: Optional[str], exc: Exception) -> ReadinessCheck:
    log.warning("alerting.readiness.check_failed", check=check_id, error_type=type(exc).__name__)
    return _item(check_id, label_key, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), action_url)


async def _number(config: Any, key: str) -> float:
    return float(await config.get(key))


def _platform(config: Any, key: str) -> Optional[str]:
    try:
        value = config.get_platform(key)
    except Exception:  # noqa: BLE001
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _routing(config: Any, bank_id: str, policy_store: Any) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_ROUTING_LABEL"
    try:
        policy = await policy_store.get_active(bank_id, "BANK", None)
        own = policy is not None
        if policy is None:
            policy = await build_default_bank_policy(config)
        errors = validate_policy(policy, level="BANK")
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_routing", label, _ROUTING_URL, exc)
    if errors:
        problems = " ".join(get_message(_PROBLEM_KEYS[e]) for e in errors if e in _PROBLEM_KEYS) or ", ".join(errors)
        return _item("alert_routing", label, "FAIL", get_message("UI_GOLIVE_ALERT_ROUTING_OWN", problems=problems), _ROUTING_URL)
    return _item("alert_routing", label, "PASS", get_message("UI_GOLIVE_ALERT_ROUTING_OK"), _ROUTING_URL)


async def _oncall(config: Any, bank_id: str, oncall_store: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_ONCALL_LABEL"
    try:
        rotas = await oncall_store.list_rotas(bank_id)
        if not rotas:
            return _item("alert_oncall", label, "WARN", get_message("UI_GOLIVE_ALERT_ONCALL_NONE"), _ONCALL_URL)
        days, step = int(await _number(config, "alerting.oncall_gap_days")), int(await _number(config, "alerting.oncall_gap_step_minutes"))
        calendar = await load_calendar(config)
        for rota in rotas:
            gaps = await oncall_store.gaps(bank_id, rota["name"], calendar, start=now, days=days, step_minutes=step)
            if gaps:
                return _item("alert_oncall", label, "FAIL", get_message("UI_GOLIVE_ALERT_ONCALL_GAPS", gaps=len(gaps), days=days, rota=rota["name"]), _ONCALL_URL)
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_oncall", label, _ONCALL_URL, exc)
    return _item("alert_oncall", label, "PASS", get_message("UI_GOLIVE_ALERT_ONCALL_OK", days=days, rotas=len(rotas)), _ONCALL_URL)


async def _email(config: Any) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_EMAIL_LABEL"
    host = _platform(config, "smtp.host")
    if host is None:
        return _item("alert_email", label, "FAIL", get_message("UI_GOLIVE_ALERT_EMAIL_NONE"), _SETTINGS_URL)
    try:
        raw = await config.get("alerting.public_mail_hosts")
        public = [str(h).lower() for h in (json.loads(raw) if isinstance(raw, str) else raw)]
    except Exception:  # noqa: BLE001
        public = []
    if host.lower() in public:
        return _item("alert_email", label, "WARN", get_message("UI_GOLIVE_ALERT_EMAIL_PUBLIC", host=host), _SETTINGS_URL)
    return _item("alert_email", label, "PASS", get_message("UI_GOLIVE_ALERT_EMAIL_OK", host=host), _SETTINGS_URL)


async def _recent_delivery(config: Any, bank_id: str, pool: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_DELIVERY_LABEL"
    try:
        days = int(await _number(config, "alerting.readiness_test_send_days"))
        channels = ["bell"] + (["email"] if _platform(config, "smtp.host") else []) \
            + (["whatsapp"] if _platform(config, "whatsapp.api_url") and _platform(config, "whatsapp.phone_number_id") else [])
        rows = await pool.fetch("SELECT DISTINCT channel FROM platform.alert_deliveries WHERE bank_id=$1 AND status='SENT' AND completed_at >= $2",
                                bank_id, now - timedelta(days=days))
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_recent_delivery", label, _SETTINGS_URL, exc)
    done = {r["channel"] for r in rows}
    missing = [c for c in channels if c not in done]
    if missing:
        return _item("alert_recent_delivery", label, "FAIL", get_message("UI_GOLIVE_ALERT_DELIVERY_MISSING", days=days, channels=", ".join(missing)), _SETTINGS_URL)
    return _item("alert_recent_delivery", label, "PASS", get_message("UI_GOLIVE_ALERT_DELIVERY_OK", days=days, channels=", ".join(channels)), _SETTINGS_URL)


async def _open_incidents(config: Any, bank_id: str, pool: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_OPEN_LABEL"
    try:
        hours = int(await _number(config, "alerting.readiness_open_incident_hours"))
        count = await pool.fetchval("SELECT COUNT(*) FROM platform.alert_incidents WHERE bank_id=$1 AND state <> 'RESOLVED' AND opened_at < $2",
                                    bank_id, now - timedelta(hours=hours))
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_open_incidents", label, "/ops/incidents", exc)
    if count:
        return _item("alert_open_incidents", label, "WARN", get_message("UI_GOLIVE_ALERT_OPEN_STALE", count=count, hours=hours), "/ops/incidents")
    return _item("alert_open_incidents", label, "PASS", get_message("UI_GOLIVE_ALERT_OPEN_OK", hours=hours), "/ops/incidents")


async def alerting_readiness(*, config: Any, bank_id: str, pool: Any, policy_store: Any, oncall_store: Any, now: Optional[datetime] = None) -> list[ReadinessCheck]:
    """The alerting items for the Go-Live screen. `policy_store` and `oncall_store` are the same stores the routing screens use."""
    moment = now or datetime.now(timezone.utc)
    return [await _routing(config, bank_id, policy_store), await _oncall(config, bank_id, oncall_store, moment), await _email(config),
            await _recent_delivery(config, bank_id, pool, moment), await _open_incidents(config, bank_id, pool, moment)]
