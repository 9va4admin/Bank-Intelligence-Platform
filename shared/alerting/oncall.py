"""On call: who is on duty right now, and how an "on call" target in a routing result becomes real people (docs/design/alerting-1b-plan.md).

A rota is a set of recurring weekly shifts (days, start, end; an overnight shift belongs to the day it starts), each with the people on it and how they rotate
(everyone together, one per week, one per day), plus an optional fallback for any time no shift covers. An override (a swap, a cover) replaces the rota for its period.
Pure code: the clock and the holiday calendar are passed in. Times are judged in the bank's timezone.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from shared.alerting.routing_policy import Calendar, ResolvedStep, ResolvedTarget, Routing, _clock, _local

ROTATIONS = ("none", "weekly", "daily")
HOLIDAY_MODES = ("include", "exclude", "only")


class Shift(BaseModel):
    days: list[int]                                   # the day a shift STARTS on; Monday = 0
    start: str
    end: str
    users: list[str] = Field(default_factory=list)
    rotation: str = "none"                            # none: everyone listed together | weekly | daily: one person at a time, in turn
    holidays: str = "include"                         # include | exclude (not on holidays) | only (on holidays only)


class Fallback(BaseModel):
    users: list[str] = Field(default_factory=list)


class Rota(BaseModel):
    shifts: list[Shift] = Field(default_factory=list)
    fallback: Optional[Fallback] = None


class OnCall(BaseModel):
    users: list[str] = Field(default_factory=list)
    source: Literal["override", "shift", "fallback", "none"] = "none"


# ---------------------------------------------------------------- who is on call

def _active_overrides(overrides: list, now: datetime) -> list[str]:
    people: list[str] = []
    for ov in overrides:
        get = ov.get if isinstance(ov, dict) else lambda k, _ov=ov: getattr(_ov, k)
        if get("starts_at") <= now < get("ends_at") and get("user_id") not in people:
            people.append(get("user_id"))
    return people


def _shift_day(shift: Shift, local: datetime) -> Optional[date]:
    """The date this shift started on, if it is running at `local`; otherwise None."""
    start, end, t = _clock(shift.start), _clock(shift.end), local.time().replace(second=0, microsecond=0)
    if start < end:
        return local.date() if local.weekday() in shift.days and start <= t < end else None
    if t >= start and local.weekday() in shift.days:                       # an overnight shift, in its first (evening) part
        return local.date()
    yesterday = local.date() - timedelta(days=1)
    if t < end and yesterday.weekday() in shift.days:                      # ... or in its second (morning) part: it started yesterday
        return yesterday
    return None


def _people(shift: Shift, started: date) -> list[str]:
    if shift.rotation == "weekly" and shift.users:
        return [shift.users[((started.toordinal() - 1) // 7) % len(shift.users)]]
    if shift.rotation == "daily" and shift.users:
        return [shift.users[started.toordinal() % len(shift.users)]]
    return list(shift.users)


def who_is_on_call(rota: Rota, overrides: list, now: datetime, calendar: Calendar) -> OnCall:
    local = _local(now, calendar)
    covering = _active_overrides(overrides, now)
    if covering:
        return OnCall(users=covering, source="override")
    people: list[str] = []
    for shift in rota.shifts:
        started = _shift_day(shift, local)
        if started is None:
            continue
        is_holiday = started.isoformat() in calendar.holidays
        if (shift.holidays == "exclude" and is_holiday) or (shift.holidays == "only" and not is_holiday):
            continue
        for person in _people(shift, started):
            if person not in people:
                people.append(person)
    if people:
        return OnCall(users=people, source="shift")
    if rota.fallback and rota.fallback.users:
        return OnCall(users=list(rota.fallback.users), source="fallback")
    return OnCall()


def find_gaps(rota: Rota, overrides: list, calendar: Calendar, *, start: datetime, days: int, step_minutes: int) -> list[tuple[datetime, datetime]]:
    """Stretches in the next `days` days when nobody (not even the fallback) is on call, merged. Sampled every `step_minutes`."""
    step = timedelta(minutes=max(1, step_minutes))
    gaps: list[tuple[datetime, datetime]] = []
    t, end = start, start + timedelta(days=days)
    open_since: Optional[datetime] = None
    while t < end:
        empty = not who_is_on_call(rota, overrides, t, calendar).users
        if empty and open_since is None:
            open_since = t
        if not empty and open_since is not None:
            gaps.append((open_since, t))
            open_since = None
        t += step
    if open_since is not None:
        gaps.append((open_since, t))
    return gaps


# ---------------------------------------------------------------- expanding routing

def _merge(into: list[ResolvedTarget], kind: str, ref: str, channels: list[str]) -> None:
    for existing in into:
        if (existing.kind, existing.ref) == (kind, ref):
            existing.channels.extend(c for c in channels if c not in existing.channels)
            return
    into.append(ResolvedTarget(kind=kind, ref=ref, channels=list(channels)))


def expand_oncall_targets(routing: Routing, on_call: dict[str, OnCall]) -> Routing:
    """Replace every `oncall` target by the people currently on call, keeping its channels. A rota nobody is on (or an unknown one) is dropped with a warning."""
    out = routing.model_copy(deep=True)
    for step in out.steps:
        rebuilt: list[ResolvedTarget] = []
        for target in step.targets:
            if target.kind != "oncall":
                _merge(rebuilt, target.kind, target.ref, target.channels)
                continue
            people = on_call[target.ref].users if target.ref in on_call else []
            if not people:
                warning = f"oncall_unfilled:{target.ref}"
                if warning not in out.warnings:
                    out.warnings.append(warning)
                continue
            for person in people:
                _merge(rebuilt, "user", person, target.channels)
        step.targets = rebuilt
    return out


# ---------------------------------------------------------------- validation

def _valid_time(text: str) -> bool:
    try:
        _clock(text)
        return True
    except (ValueError, AttributeError):
        return False


def validate_rota(rota: Rota) -> list[str]:
    errors: list[str] = []

    def add(code: str) -> None:
        if code not in errors:
            errors.append(code)
    for shift in rota.shifts:
        if not (_valid_time(shift.start) and _valid_time(shift.end)) or shift.start == shift.end:
            add("bad_time")
        if not shift.days or any(d < 0 or d > 6 for d in shift.days):
            add("bad_day")
        if not shift.users:
            add("shift_needs_people")
        if shift.rotation not in ROTATIONS:
            add("unknown_rotation")
        if shift.holidays not in HOLIDAY_MODES:
            add("unknown_holidays")
    if not rota.shifts and not (rota.fallback and rota.fallback.users):
        add("rota_has_no_one")
    return errors
