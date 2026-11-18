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

from shared.alerting.dns_check import domain_of
from shared.alerting.policy_defaults import build_default_bank_policy, load_calendar
from shared.alerting.routing_policy import validate_policy
from shared.messages import get_message
from shared.utils.masking import mask_email, mask_phone

log = structlog.get_logger()

Status = Literal["PASS", "WARN", "FAIL", "SKIP"]

# the plain-language reason for each way a policy can be refused (the same wording the routing screen shows)
_PROBLEM_KEYS = {
    "p0_not_covered": "UI_ALERTING_RT_CODE_P0_NOT_COVERED", "p0_needs_a_target": "UI_ALERTING_RT_CODE_P0_TARGET", "p0_needs_two_channels": "UI_ALERTING_RT_CODE_P0_CHANNELS",
    "duplicate_rule_id": "UI_ALERTING_RT_CODE_DUPLICATE", "unknown_channel": "UI_ALERTING_RT_CODE_CHANNEL", "escalation_not_increasing": "UI_ALERTING_RT_CODE_ESCALATION_ORDER",
    "negative_minutes": "UI_ALERTING_RT_CODE_NEGATIVE", "quiet_hold_not_allowed": "UI_ALERTING_RT_CODE_HOLD", "escalation_must_end_with_a_person": "UI_ALERTING_RT_CODE_ESCALATION_PERSON",
}
_ROUTING_URL, _ONCALL_URL, _SETTINGS_URL, _CONTACTS_URL = "/admin/alert-routing", "/ops/oncall", "/admin/alert-settings", "/admin/alert-contacts"


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


_AUDIT_REASON_KEYS = {"not_connected": "UI_GOLIVE_ALERT_AUDIT_REASON_NOT_CONNECTED", "write_failed": "UI_GOLIVE_ALERT_AUDIT_REASON_WRITE_FAILED", "verify_failed": "UI_GOLIVE_ALERT_AUDIT_REASON_VERIFY_FAILED"}


async def _audit_path(config: Any, bank_id: str, proof_store: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_AUDIT_LABEL"
    if proof_store is None:
        return _item("alert_audit_path", label, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), _SETTINGS_URL)
    try:
        days = int(await _number(config, "alerting.readiness_audit_proof_days"))
        proof = await proof_store.latest(bank_id, "audit_path")
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_audit_path", label, _SETTINGS_URL, exc)
    if proof is None:
        return _item("alert_audit_path", label, "FAIL", get_message("UI_GOLIVE_ALERT_AUDIT_NONE"), _SETTINGS_URL)
    if not proof.ok:
        reason = get_message(_AUDIT_REASON_KEYS[proof.detail.get("reason")]) if proof.detail.get("reason") in _AUDIT_REASON_KEYS else str(proof.detail.get("reason", ""))
        return _item("alert_audit_path", label, "FAIL", get_message("UI_GOLIVE_ALERT_AUDIT_FAILED", reason=reason), _SETTINGS_URL)
    age_days = (now - proof.ran_at).days
    if age_days > days:
        return _item("alert_audit_path", label, "WARN", get_message("UI_GOLIVE_ALERT_AUDIT_OLD", days=age_days), _SETTINGS_URL)
    return _item("alert_audit_path", label, "PASS", get_message("UI_GOLIVE_ALERT_AUDIT_OK", when=proof.ran_at.strftime("%d %b %Y, %H:%M UTC"), who=proof.ran_by), _SETTINGS_URL)


async def _mail_dns(config: Any, bank_id: str, proof_store: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_DNS_LABEL"
    domain = domain_of(_platform(config, "smtp.from_address") or _platform(config, "smtp.username"))
    if domain is None:
        return _item("alert_mail_dns", label, "SKIP", get_message("UI_GOLIVE_ALERT_DNS_NO_ADDRESS"), _SETTINGS_URL)
    if proof_store is None:
        return _item("alert_mail_dns", label, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), _SETTINGS_URL)
    try:
        accepted = await config.get("alerting.mail_dns_risk_accepted")
        days = int(await _number(config, "alerting.readiness_dns_proof_days"))
        proof = await proof_store.latest(bank_id, "mail_dns")
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_mail_dns", label, _SETTINGS_URL, exc)
    if accepted is True or str(accepted).strip().lower() in ("true", "1", "yes"):
        return _item("alert_mail_dns", label, "PASS", get_message("UI_GOLIVE_ALERT_DNS_ACCEPTED", domain=domain), _SETTINGS_URL)
    if proof is None:
        return _item("alert_mail_dns", label, "FAIL", get_message("UI_GOLIVE_ALERT_DNS_NONE"), _SETTINGS_URL)
    checked = proof.detail.get("domain") or domain
    if proof.detail.get("error"):
        return _item("alert_mail_dns", label, "FAIL", get_message("UI_GOLIVE_ALERT_DNS_FAILED", domain=checked), _SETTINGS_URL)
    if not proof.ok:
        missing = [name for name, found in (("SPF", proof.detail.get("spf")), ("DMARC", proof.detail.get("dmarc"))) if not found]
        missing += [get_message("UI_GOLIVE_ALERT_DNS_DKIM_MISSING", selector=sel) for sel, found in (proof.detail.get("dkim") or {}).items() if not found]
        return _item("alert_mail_dns", label, "FAIL", get_message("UI_GOLIVE_ALERT_DNS_MISSING", domain=checked, missing=", ".join(missing)), _SETTINGS_URL)
    age_days = (now - proof.ran_at).days
    if age_days > days:
        return _item("alert_mail_dns", label, "WARN", get_message("UI_GOLIVE_ALERT_DNS_OLD", domain=checked, days=age_days), _SETTINGS_URL)
    selectors = len(proof.detail.get("dkim") or {})
    dkim = get_message("UI_GOLIVE_ALERT_DNS_DKIM_PART", count=selectors) if selectors else ""
    return _item("alert_mail_dns", label, "PASS", get_message("UI_GOLIVE_ALERT_DNS_OK", domain=checked, dkim=dkim, when=proof.ran_at.strftime("%d %b %Y"), who=proof.ran_by), _SETTINGS_URL)


_SIM_SEVERITIES = ("P0", "P1", "P2")
_SIM_KEYS = {"P0": "UI_GOLIVE_ALERT_SIM_SEV_P0", "P1": "UI_GOLIVE_ALERT_SIM_SEV_P1", "P2": "UI_GOLIVE_ALERT_SIM_SEV_P2"}


async def _simulated(bank_id: str, policy_store: Any, proof_store: Any) -> ReadinessCheck:
    label, url = "UI_GOLIVE_ALERT_SIM_LABEL", _ROUTING_URL
    if proof_store is None:
        return _item("alert_simulated", label, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), url)
    try:
        found = await proof_store.latest_many(bank_id, [f"simulation_{s}" for s in _SIM_SEVERITIES])
        record = await policy_store.active_record(bank_id, "BANK", None) if hasattr(policy_store, "active_record") else None
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_simulated", label, url, exc)
    words = lambda sevs: ", ".join(get_message(_SIM_KEYS[s]) for s in sevs)  # noqa: E731
    missing = [s for s in _SIM_SEVERITIES if f"simulation_{s}" not in found]
    if missing:
        return _item("alert_simulated", label, "FAIL", get_message("UI_GOLIVE_ALERT_SIM_NONE", severities=words(missing)), url)
    nobody = [s for s in _SIM_SEVERITIES if not found[f"simulation_{s}"].ok]
    if nobody:
        return _item("alert_simulated", label, "FAIL", get_message("UI_GOLIVE_ALERT_SIM_NOBODY", severities=words(nobody)), url)
    approved = getattr(record, "approved_at", None)
    stale = [s for s in _SIM_SEVERITIES if approved is not None and found[f"simulation_{s}"].ran_at < approved]
    if stale:
        return _item("alert_simulated", label, "FAIL", get_message("UI_GOLIVE_ALERT_SIM_STALE", severities=words(stale)), url)
    last = max(found[f"simulation_{s}"].ran_at for s in _SIM_SEVERITIES)
    return _item("alert_simulated", label, "PASS", get_message("UI_GOLIVE_ALERT_SIM_OK", severities=words(_SIM_SEVERITIES), when=last.strftime("%d %b %Y, %H:%M UTC")), url)


async def _fire_drill(config: Any, bank_id: str, pool: Any, proof_store: Any, now: datetime) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_FD_LABEL"
    if proof_store is None:
        return _item("alert_fire_drill", label, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), _SETTINGS_URL)
    try:
        target = int(await _number(config, "alerting.fire_drill_ack_minutes"))
        window_days = int(await _number(config, "alerting.readiness_drill_days"))
        proof = await proof_store.latest(bank_id, "fire_drill")
        incident = None
        if proof is not None and proof.detail.get("incident_id"):
            incident = await pool.fetchrow("SELECT acked_at, acked_by FROM platform.alert_incidents WHERE bank_id=$1 AND incident_id=$2", bank_id, proof.detail["incident_id"])
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_fire_drill", label, _SETTINGS_URL, exc)
    if proof is None:
        return _item("alert_fire_drill", label, "FAIL", get_message("UI_GOLIVE_ALERT_FD_NONE"), _SETTINGS_URL)
    elapsed = (now - proof.ran_at).total_seconds() / 60
    acked_at = incident["acked_at"] if incident else None
    if acked_at is None:
        if elapsed < target:
            return _item("alert_fire_drill", label, "WARN", get_message("UI_GOLIVE_ALERT_FD_WAITING", ago=int(elapsed), target=target), _SETTINGS_URL)
        return _item("alert_fire_drill", label, "FAIL", get_message("UI_GOLIVE_ALERT_FD_MISSED", target=target), _SETTINGS_URL)
    minutes = max(0, round((acked_at - proof.ran_at).total_seconds() / 60))
    if minutes > target:
        return _item("alert_fire_drill", label, "FAIL", get_message("UI_GOLIVE_ALERT_FD_LATE", minutes=minutes, target=target), _SETTINGS_URL)
    if (now - proof.ran_at).days > window_days:
        return _item("alert_fire_drill", label, "WARN", get_message("UI_GOLIVE_ALERT_FD_OLD", days=(now - proof.ran_at).days), _SETTINGS_URL)
    return _item("alert_fire_drill", label, "PASS", get_message("UI_GOLIVE_ALERT_FD_OK", who=incident["acked_by"] or "", minutes=minutes, target=target), _SETTINGS_URL)


def _split(raw: Any) -> list[str]:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("[") else raw
    except ValueError:
        parsed = raw
    items = parsed if isinstance(parsed, list) else (str(parsed).split(",") if parsed else [])
    return [str(x).strip() for x in items if str(x).strip()]


async def _contacts(config: Any, bank_id: str, policy_store: Any, contact_store: Any) -> ReadinessCheck:
    label = "UI_GOLIVE_ALERT_CT_LABEL"
    if contact_store is None:
        return _item("alert_contacts", label, "WARN", get_message("UI_GOLIVE_ALERT_UNAVAILABLE"), _CONTACTS_URL)
    try:
        addresses: list[str] = []
        for key in ("alerts.email_recipients", "alerts.whatsapp_recipients"):
            try:
                addresses += _split(await config.get(key))
            except Exception:  # noqa: BLE001
                pass
        policy = await policy_store.get_active(bank_id, "BANK", None)
        if policy is not None:
            for rule in policy.rules:
                for target in list(rule.targets) + [t for step in rule.escalation for t in step.targets]:
                    if target.kind == "external":
                        addresses.append(target.ref)
        unique = list(dict.fromkeys(a.strip().lower() if "@" in a else a.strip() for a in addresses if a.strip()))
        missing = await contact_store.unverified(bank_id, unique) if unique else []
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_contacts", label, _CONTACTS_URL, exc)
    if not unique:
        return _item("alert_contacts", label, "PASS", get_message("UI_GOLIVE_ALERT_CT_NONE"), _CONTACTS_URL)
    if missing:
        masked = ", ".join(mask_email(a) if "@" in a else mask_phone(a) for a in missing[:3]) + (" ..." if len(missing) > 3 else "")
        return _item("alert_contacts", label, "FAIL", get_message("UI_GOLIVE_ALERT_CT_UNVERIFIED", count=len(missing), masked=masked), _CONTACTS_URL)
    return _item("alert_contacts", label, "PASS", get_message("UI_GOLIVE_ALERT_CT_OK", count=len(unique)), _CONTACTS_URL)


async def _silences(bank_id: str, pool: Any, now: datetime) -> ReadinessCheck:
    label, url = "UI_GOLIVE_ALERT_SL_LABEL", "/ops/silences"
    try:
        count = await pool.fetchval("SELECT COUNT(*) FROM platform.alert_silences WHERE bank_id=$1 AND cancelled_at IS NULL AND starts_at <= $2 AND ends_at > $2", bank_id, now)
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_silences", label, url, exc)
    if count:
        return _item("alert_silences", label, "WARN", get_message("UI_GOLIVE_ALERT_SL_ACTIVE", count=count), url)
    return _item("alert_silences", label, "PASS", get_message("UI_GOLIVE_ALERT_SL_NONE"), url)


async def _regulatory(config: Any) -> ReadinessCheck:
    """Amber, never blocking: the windows are entered by the compliance officer, or marked pending."""
    label, url = "UI_GOLIVE_ALERT_REG_LABEL", _SETTINGS_URL
    try:
        raw = await config.get("alerting.regulatory_windows")
        pending = await config.get("alerting.regulatory_windows_pending")
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_regulatory", label, url, exc)
    try:
        windows = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        windows = None
    if windows is None:
        return _item("alert_regulatory", label, "WARN", get_message("UI_GOLIVE_ALERT_REG_INCOMPLETE", count=1), url)
    if not windows:
        key = "UI_GOLIVE_ALERT_REG_PENDING" if pending is True or str(pending).strip().lower() in ("true", "1", "yes") else "UI_GOLIVE_ALERT_REG_NONE"
        return _item("alert_regulatory", label, "WARN", get_message(key), url)
    def complete(w: Any) -> bool:
        try:
            return isinstance(w, dict) and bool(str(w.get("name", "")).strip()) and float(w.get("hours", 0)) > 0
        except (TypeError, ValueError):
            return False
    incomplete = sum(1 for w in windows if not complete(w))
    if incomplete:
        return _item("alert_regulatory", label, "WARN", get_message("UI_GOLIVE_ALERT_REG_INCOMPLETE", count=incomplete), url)
    return _item("alert_regulatory", label, "PASS", get_message("UI_GOLIVE_ALERT_REG_OK", count=len(windows)), url)


async def _risks(bank_id: str, pool: Any) -> ReadinessCheck:
    label, url = "UI_GOLIVE_ALERT_RK_LABEL", "/admin/alert-risks"
    try:
        from shared.alerting.risks import RiskStore
        summary = await RiskStore(pool, review_days=0).summary(bank_id)
    except Exception as exc:  # noqa: BLE001
        return _unavailable("alert_risks", label, url, exc)
    if summary.total == 0:
        return _item("alert_risks", label, "FAIL", get_message("UI_GOLIVE_ALERT_RK_NONE"), url)
    if summary.without_owner:
        return _item("alert_risks", label, "FAIL", get_message("UI_GOLIVE_ALERT_RK_NO_OWNER", count=summary.without_owner, total=summary.total), url)
    if summary.review_overdue:
        return _item("alert_risks", label, "WARN", get_message("UI_GOLIVE_ALERT_RK_OVERDUE", count=summary.review_overdue), url)
    return _item("alert_risks", label, "PASS", get_message("UI_GOLIVE_ALERT_RK_OK", total=summary.total, verified=summary.verified), url)


async def alerting_readiness(*, config: Any, bank_id: str, pool: Any, policy_store: Any, oncall_store: Any, proof_store: Any = None, contact_store: Any = None,
                             now: Optional[datetime] = None) -> list[ReadinessCheck]:
    """The alerting items for the Go-Live screen. `policy_store` and `oncall_store` are the same stores the routing screens use."""
    moment = now or datetime.now(timezone.utc)
    return [await _routing(config, bank_id, policy_store), await _oncall(config, bank_id, oncall_store, moment), await _email(config),
            await _recent_delivery(config, bank_id, pool, moment), await _audit_path(config, bank_id, proof_store, moment), await _mail_dns(config, bank_id, proof_store, moment), await _simulated(bank_id, policy_store, proof_store), await _fire_drill(config, bank_id, pool, proof_store, moment), await _contacts(config, bank_id, policy_store, contact_store), await _silences(bank_id, pool, moment), await _regulatory(config), await _risks(bank_id, pool), await _open_incidents(config, bank_id, pool, moment)]
