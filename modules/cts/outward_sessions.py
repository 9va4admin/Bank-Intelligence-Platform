"""Outward clearing-session cut-offs.

A bank submits outward items in one or more daily sessions, each closing at a cut-off time (2:30 pm for the first
bank). The times are bank configuration (cts.outward_session_cutoffs, a list of "HH:MM"; cts.outward_session_timezone),
never constants here. Everything that needs "how long until this has to be done" asks this module, so allocation urgency,
the checker timeout and the filing of staged decisions all agree on the same deadline.

Calendar days only: a bank's holidays and weekends are not modelled yet, so after the last cut-off the next one is
tomorrow's first.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

try:                                             # zoneinfo needs the tz database; fall back to India time without it
    from zoneinfo import ZoneInfo
except Exception:                                # pragma: no cover
    ZoneInfo = None  # type: ignore

DEFAULT_CUTOFFS: list[tuple[int, int]] = [(14, 30)]
_IST = timezone(timedelta(hours=5, minutes=30))


def parse_cutoffs(value: Any) -> list[tuple[int, int]]:
    """Sorted (hour, minute) pairs from a list of "HH:MM" (or its JSON text); bad entries are dropped; never empty."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [value]
    out: set[tuple[int, int]] = set()
    for item in value or []:
        try:
            h, m = str(item).strip().split(":")
            h, m = int(h), int(m)
        except ValueError:
            continue
        if 0 <= h < 24 and 0 <= m < 60:
            out.add((h, m))
    return sorted(out) or list(DEFAULT_CUTOFFS)


def _tz(name: Any):
    if ZoneInfo is not None and name:
        try:
            return ZoneInfo(str(name))
        except Exception:                        # noqa: BLE001 - unknown zone name
            pass
    return _IST


def next_cutoff(now: float, cfg: dict) -> float:
    """Epoch seconds of the first cut-off strictly after `now` (a session that closes exactly now is closed)."""
    tz = _tz(cfg.get("outward_session_timezone", "Asia/Kolkata"))
    cutoffs = parse_cutoffs(cfg.get("outward_session_cutoffs"))
    local = datetime.fromtimestamp(now, tz)
    for day_offset in (0, 1):
        day = local.date() + timedelta(days=day_offset)
        for h, m in cutoffs:
            candidate = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            if candidate.timestamp() > now:
                return candidate.timestamp()
    raise RuntimeError("unreachable: two days always contain a cut-off")      # pragma: no cover


def seconds_to_cutoff(now: float, cfg: dict) -> float:
    return next_cutoff(now, cfg) - now
