"""The routing rules engine (docs/design/alerting-1b-plan.md): who is told about an incident, on which channels, and when it escalates.

Pure code (no database, no clock of its own): the incident's facts, the policies at each level and the time go in; the routing comes out. The same function
serves the live send path and the "who would be told for this incident" simulator, so they can never disagree.

How the levels combine: BANK always applies; PU only to an incident of that PU; SMB only to an incident of that SMB. At each level the first rule that matches
wins. Targets accumulate across levels (a person named twice gets the union of their channels). A lower level can add people, channels and escalation steps but
never remove what a higher level requires; on a conflict (timing of the same escalation step, quiet-hold) the higher level wins.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from fnmatch import fnmatchcase
from typing import Literal, Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

CHANNELS = ("email", "whatsapp", "bell", "sms", "webhook", "syslog")
PERSON_KINDS = ("user", "role", "external", "oncall")           # a group alone does not make a person accountable
LEVELS = ("BANK", "PU", "SMB")
HOLDABLE = ("P2", "P3")


class TargetSpec(BaseModel):
    kind: Literal["user", "role", "group", "external", "oncall"]
    ref: str
    channels: list[str] = Field(default_factory=list)


class EscalationStep(BaseModel):
    level: int
    after_minutes: int
    targets: list[TargetSpec] = Field(default_factory=list)


class Rule(BaseModel):
    id: str
    severities: list[str] = Field(default_factory=list)          # empty = any
    components: list[str] = Field(default_factory=list)          # names or patterns; empty = any
    teams: list[str] = Field(default_factory=list)               # owning team; empty = any
    hours: Literal["always", "business", "off_hours"] = "always"
    targets: list[TargetSpec] = Field(default_factory=list)
    escalation: list[EscalationStep] = Field(default_factory=list)
    repeat_minutes: Optional[int] = None
    quiet_hold: bool = False


class Policy(BaseModel):
    rules: list[Rule] = Field(default_factory=list)
    scope_id: Optional[str] = None                               # the PU or SMB this policy is for; None = every one


class BusinessHours(BaseModel):
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])      # Monday = 0
    start: str = "09:30"
    end: str = "18:00"


class Calendar(BaseModel):
    timezone: str = "UTC"
    business: BusinessHours = Field(default_factory=BusinessHours)
    holidays: list[str] = Field(default_factory=list)            # ISO dates in the bank's timezone


class IncidentFacts(BaseModel):
    severity: str
    component: str = ""
    owning_team: str = ""
    pu_id: Optional[str] = None
    smb_id: Optional[str] = None


class ResolvedTarget(BaseModel):
    kind: str
    ref: str
    channels: list[str]


class ResolvedStep(BaseModel):
    level: int
    after_minutes: int
    targets: list[ResolvedTarget]


class Matched(BaseModel):
    level: str
    rule_id: str


class Routing(BaseModel):
    model_config = ConfigDict(frozen=False)
    steps: list[ResolvedStep] = Field(default_factory=list)
    matched: list[Matched] = Field(default_factory=list)
    repeat_minutes: Optional[int] = None
    held: bool = False
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- schedule

def _local(now: datetime, calendar: Calendar) -> datetime:
    try:
        tz = ZoneInfo(calendar.timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        tz = timezone.utc
    return now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)


def _clock(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def is_business_time(now: datetime, calendar: Calendar) -> bool:
    local = _local(now, calendar)
    if local.date().isoformat() in calendar.holidays or local.weekday() not in calendar.business.days:
        return False
    return _clock(calendar.business.start) <= local.time().replace(second=0, microsecond=0) < _clock(calendar.business.end)


def next_business_start(now: datetime, calendar: Calendar, *, horizon_days: int = 14) -> Optional[datetime]:
    """When working hours next begin: now if they are on, else the next opening (holidays and non-working days skipped). None if they never open within `horizon_days`."""
    local = _local(now, calendar)
    if is_business_time(local, calendar):
        return local
    opening = _clock(calendar.business.start)
    for offset in range(horizon_days + 1):
        day = (local + timedelta(days=offset)).replace(hour=opening.hour, minute=opening.minute, second=0, microsecond=0)
        if day > local and is_business_time(day, calendar):
            return day
    return None


# ---------------------------------------------------------------- matching

def _rule_matches(rule: Rule, facts: IncidentFacts, calendar: Calendar, now: datetime) -> bool:
    if rule.severities and facts.severity not in rule.severities:
        return False
    if rule.components and not any(fnmatchcase(facts.component, pattern) for pattern in rule.components):
        return False
    if rule.teams and facts.owning_team not in rule.teams:
        return False
    if rule.hours == "business":
        return is_business_time(now, calendar)
    if rule.hours == "off_hours":
        return not is_business_time(now, calendar)
    return True


def _policies_at(level: str, policies: dict, facts: IncidentFacts) -> list[Policy]:
    found = policies.get(level) or []
    found = found if isinstance(found, list) else [found]
    scope = {"BANK": None, "PU": facts.pu_id, "SMB": facts.smb_id}[level]
    if level != "BANK" and scope is None:
        return []
    return [p for p in found if level == "BANK" or p.scope_id in (None, scope)]


def _first_match(level: str, policies: dict, facts: IncidentFacts, calendar: Calendar, now: datetime) -> Optional[Rule]:
    for policy in _policies_at(level, policies, facts):
        for rule in policy.rules:
            if _rule_matches(rule, facts, calendar, now):
                return rule
    return None


# ---------------------------------------------------------------- resolution

def _add(into: dict, targets: list[TargetSpec]) -> None:
    for spec in targets:
        merged = into.setdefault((spec.kind, spec.ref), [])
        for channel in spec.channels:
            if channel not in merged:
                merged.append(channel)


def resolve_routing(facts: IncidentFacts, policies: dict, calendar: Calendar, now: datetime) -> Routing:
    out = Routing()
    immediate: dict = {}
    timing: dict[int, int] = {}
    later: dict[int, dict] = {}
    repeats: list[int] = []
    bank_rule: Optional[Rule] = None
    for level in LEVELS:
        rule = _first_match(level, policies, facts, calendar, now)
        if rule is None:
            continue
        out.matched.append(Matched(level=level, rule_id=rule.id))
        if level == "BANK":
            bank_rule = rule
        _add(immediate, rule.targets)
        for step in rule.escalation:
            timing.setdefault(step.level, step.after_minutes)            # the first (highest) level to define a step sets its timing
            _add(later.setdefault(step.level, {}), step.targets)
        if rule.repeat_minutes is not None:
            repeats.append(rule.repeat_minutes)

    if not out.matched:
        out.warnings.append("no_rule_matched")
        return out
    if bank_rule is None:
        out.warnings.append("bank_rule_missing")

    out.steps.append(ResolvedStep(level=0, after_minutes=0, targets=[ResolvedTarget(kind=k, ref=r, channels=c) for (k, r), c in immediate.items()]))
    for level_no in sorted(later):
        out.steps.append(ResolvedStep(level=level_no, after_minutes=timing[level_no],
                                      targets=[ResolvedTarget(kind=k, ref=r, channels=c) for (k, r), c in later[level_no].items()]))
    out.repeat_minutes = min(repeats) if repeats else None
    out.held = bool(bank_rule and bank_rule.quiet_hold and facts.severity in HOLDABLE and not is_business_time(now, calendar))
    return out


# ---------------------------------------------------------------- validation

def _covers(rule: Rule, severity: str) -> bool:
    return not rule.severities or severity in rule.severities


def validate_policy(policy: Policy, *, level: str) -> list[str]:
    """Reasons a policy must be refused when saved (empty = acceptable). Only the bank level is held to covering P0."""
    errors: list[str] = []

    def add(code: str) -> None:
        if code not in errors:
            errors.append(code)
    seen: set[str] = set()
    for rule in policy.rules:
        if rule.id in seen:
            add("duplicate_rule_id")
        seen.add(rule.id)
        for spec in list(rule.targets) + [t for step in rule.escalation for t in step.targets]:
            if any(channel not in CHANNELS for channel in spec.channels):
                add("unknown_channel")
        if (rule.repeat_minutes is not None and rule.repeat_minutes < 0) or any(step.after_minutes < 0 for step in rule.escalation):
            add("negative_minutes")
        steps = rule.escalation
        if any(b.after_minutes <= a.after_minutes for a, b in zip(steps, steps[1:])) or [s.level for s in steps] != list(range(1, len(steps) + 1)):
            add("escalation_not_increasing")
        if rule.quiet_hold and (_covers(rule, "P0") or _covers(rule, "P1")):
            add("quiet_hold_not_allowed")
        if steps and _covers(rule, "P0") and not any(t.kind in PERSON_KINDS for t in steps[-1].targets):
            add("escalation_must_end_with_a_person")
    if level == "BANK":
        backstop = next((r for r in policy.rules if _covers(r, "P0") and not r.components and not r.teams and r.hours == "always"), None)
        if backstop is None:
            add("p0_not_covered")
        else:
            if not backstop.targets:
                add("p0_needs_a_target")
            elif len({c for t in backstop.targets for c in t.channels}) < 2:
                add("p0_needs_two_channels")
    return errors
