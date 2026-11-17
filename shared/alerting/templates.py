"""The alert message: what an on-call person reads (docs/design/alerting-blueprint.md, section 7).

All wording comes from the message registry; links, timezone and limits from configuration. Everything dynamic is cleaned (control characters
removed, length bounded) and HTML-escaped, so an error string can never inject a header or markup into a mail.

Settings (Layer 3): alerting.ui_base_url, alerting.incident_path, alerting.runbook_base_url, alerting.runbook_map (JSON event -> runbook page),
alerting.timezone, alerting.message_max_chars, alerting.subject_max_chars.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shared.alerting.incidents import is_resolution
from shared.messages import UnknownMessageKey, get_message

DEFAULT_TIMEZONE = "UTC"
DEFAULT_MESSAGE_MAX_CHARS = 500
DEFAULT_SUBJECT_MAX_CHARS = 100
DEFAULT_INCIDENT_PATH = "/ops/incidents/{incident_id}"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WHITESPACE = re.compile(r"[\r\n\t ]+")
_SEVERITY_COLOURS = {"P0": "#b91c1c", "P1": "#c2410c", "P2": "#a16207", "P3": "#15803d", "RESOLVED": "#15803d"}     # presentation, not wording


@dataclass(frozen=True)
class TemplateSettings:
    ui_base_url: str = ""
    incident_path: str = DEFAULT_INCIDENT_PATH
    runbook_base_url: str = ""
    timezone: str = DEFAULT_TIMEZONE
    message_max_chars: int = DEFAULT_MESSAGE_MAX_CHARS
    subject_max_chars: int = DEFAULT_SUBJECT_MAX_CHARS
    runbook_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertContent:
    bank_id: str
    severity: str
    component: str
    event_type: str
    message: str
    incident_id: str = ""
    occurred_at: float = 0.0
    down_for: str = ""


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


async def _get(config_service: Any, key: str) -> Any:
    try:
        return await config_service.get(key)
    except Exception:
        return None


async def load_template_settings(config_service: Any) -> TemplateSettings:
    def text(value: Any, default: str = "") -> str:
        return value.strip() if isinstance(value, str) and value.strip() else default

    def number(value: Any, default: int) -> int:
        try:
            n = int(value)
            return n if n > 0 else default
        except (TypeError, ValueError):
            return default
    runbook_map: Any = await _get(config_service, "alerting.runbook_map")
    if isinstance(runbook_map, str):
        try:
            runbook_map = json.loads(runbook_map)
        except ValueError:
            runbook_map = None
    return TemplateSettings(
        ui_base_url=text(await _get(config_service, "alerting.ui_base_url")).rstrip("/"),
        incident_path=text(await _get(config_service, "alerting.incident_path"), DEFAULT_INCIDENT_PATH),
        runbook_base_url=text(await _get(config_service, "alerting.runbook_base_url")).rstrip("/"),
        timezone=text(await _get(config_service, "alerting.timezone"), DEFAULT_TIMEZONE),
        message_max_chars=number(await _get(config_service, "alerting.message_max_chars"), DEFAULT_MESSAGE_MAX_CHARS),
        subject_max_chars=number(await _get(config_service, "alerting.subject_max_chars"), DEFAULT_SUBJECT_MAX_CHARS),
        runbook_map={str(k): str(v) for k, v in runbook_map.items()} if isinstance(runbook_map, dict) else {},
    )


def _clean(value: str, limit: int) -> str:
    """One line of printable text, bounded."""
    return _WHITESPACE.sub(" ", _CONTROL.sub("", value or "")).strip()[:limit]


def _severity_key(content: AlertContent) -> str:
    return "RESOLVED" if is_resolution(content.event_type) else (content.severity if content.severity in ("P0", "P1", "P2", "P3") else "P2")


def _impact(content: AlertContent) -> str:
    key = (f"ALERT_IMPACT_COMPONENT_{content.component.upper()}" if content.event_type.startswith("COMPONENT_")
           else f"ALERT_IMPACT_EVENT_{content.event_type}")
    try:
        return get_message(key)
    except UnknownMessageKey:
        return get_message("ALERT_IMPACT_GENERIC")


def _when(content: AlertContent, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        tz = timezone.utc
    moment = datetime.fromtimestamp(content.occurred_at, tz)
    utc = datetime.fromtimestamp(content.occurred_at, timezone.utc)
    return get_message("ALERT_MAIL_WHEN_VALUE", local_time=moment.strftime("%Y-%m-%d %H:%M:%S"), local_zone=moment.tzname() or tz_name,
                       utc_time=utc.strftime("%Y-%m-%d %H:%M:%S"))


def _links(content: AlertContent, settings: TemplateSettings) -> tuple[str, str]:
    incident = ""
    if settings.ui_base_url and content.incident_id:
        incident = settings.ui_base_url + settings.incident_path.format(incident_id=content.incident_id)
    runbook = ""
    slug = settings.runbook_map.get(content.event_type)
    if settings.runbook_base_url and slug:
        runbook = f"{settings.runbook_base_url}/{slug}"
    return incident, runbook


def render_email(content: AlertContent, settings: TemplateSettings) -> RenderedEmail:
    sev = _severity_key(content)
    resolved = sev == "RESOLVED"
    component = _clean(content.component, 60)
    message = _clean(content.message, settings.message_max_chars)
    summary = message[:min(settings.message_max_chars, settings.subject_max_chars)]
    bank = _clean(content.bank_id, 60)
    subject = (get_message("ALERT_MAIL_SUBJECT_RESOLVED", bank_id=bank, component=component, summary=summary) if resolved
               else get_message("ALERT_MAIL_SUBJECT", severity=_clean(content.severity, 4), bank_id=bank, component=component, summary=summary))
    headline = get_message("ALERT_MAIL_HEADLINE_RESOLVED" if resolved else "ALERT_MAIL_HEADLINE", bank_id=bank)
    severity_label = get_message(f"ALERT_MAIL_SEVERITY_{sev}")
    impact = _impact(content)
    when = _when(content, settings.timezone)
    incident_link, runbook_link = _links(content, settings)

    rows: list[tuple[str, str]] = []
    if content.incident_id:
        rows.append((get_message("ALERT_MAIL_LABEL_INCIDENT"), _clean(content.incident_id, 80)))
    rows += [(get_message("ALERT_MAIL_LABEL_SEVERITY"), f"{_clean(content.severity, 4)} - {severity_label}"),
             (get_message("ALERT_MAIL_LABEL_COMPONENT"), component), (get_message("ALERT_MAIL_LABEL_WHEN"), when)]
    if content.down_for:
        rows.append((get_message("ALERT_MAIL_LABEL_DOWN_FOR"), _clean(content.down_for, 40)))
    rows.append((get_message("ALERT_MAIL_LABEL_IMPACT"), impact))
    links: list[tuple[str, str]] = []
    if runbook_link:
        links.append((get_message("ALERT_MAIL_LABEL_RUNBOOK"), runbook_link))
    if incident_link:
        links.append((get_message("ALERT_MAIL_LABEL_INCIDENT_LINK"), incident_link))
    ack = "" if resolved else get_message("ALERT_MAIL_ACK_HINT")
    footer = get_message("ALERT_MAIL_FOOTER", bank_id=bank)

    text_lines = [headline, severity_label, ""]
    text_lines += [f"{label}: {value}" for label, value in rows]
    text_lines += ["", message, ""]
    text_lines += [f"{label}: {url}" for label, url in links]
    if ack:
        text_lines += ["", ack]
    text_lines += ["", "--", footer]
    text = "\n".join(text_lines)

    e = html.escape
    colour = _SEVERITY_COLOURS[sev]
    row_html = "".join(f'<tr><td style="padding:4px 12px 4px 0;color:#555;white-space:nowrap">{e(label)}</td><td style="padding:4px 0">{e(value)}</td></tr>'
                       for label, value in rows)
    link_html = "".join(f'<p style="margin:6px 0">{e(label)}: <a href="{e(url, quote=True)}">{e(url)}</a></p>' for label, url in links)
    body_html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#111;max-width:640px">'
        f'<div style="background:{colour};color:#fff;padding:10px 14px;border-radius:4px"><strong>{e(headline)}</strong><br>{e(severity_label)}</div>'
        f'<table style="margin:14px 0;border-collapse:collapse">{row_html}</table>'
        f'<p style="margin:10px 0">{e(message)}</p>{link_html}'
        + (f'<p style="margin:10px 0;color:#444">{e(ack)}</p>' if ack else "")
        + f'<hr style="border:0;border-top:1px solid #ddd"><p style="color:#777;font-size:12px">{e(footer)}</p></div>')
    return RenderedEmail(subject=subject, text=text, html=body_html)


def render_short(content: AlertContent, settings: TemplateSettings) -> tuple[str, str]:
    """Title and body for the in-app bell and for text messages."""
    resolved = is_resolution(content.event_type)
    component = _clean(content.component, 60)
    title = (get_message("ALERT_SHORT_TITLE_RESOLVED", component=component) if resolved
             else get_message("ALERT_SHORT_TITLE", severity=_clean(content.severity, 4), component=component))
    return title, _clean(content.message, settings.message_max_chars)
