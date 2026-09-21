"""Response models declared timestamp/date fields as plain `str`, but a real database returns
datetime/date objects, so every such endpoint failed serialisation with a 500 against real
YugabyteDB (found by the first real API run: GET /v1/branches). Mock rows use strings, which is
why unit tests never noticed. IsoTimestamp coerces datetime/date -> ISO string, str passes through."""
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pytest
from pydantic import BaseModel

from apps.api.schemas.types import IsoTimestamp, OptIsoTimestamp


class _M(BaseModel):
    at: IsoTimestamp
    maybe: OptIsoTimestamp = None


def test_datetime_becomes_iso_string():
    m = _M(at=datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc))
    assert m.at == "2026-09-21T12:30:00+00:00"


def test_date_becomes_iso_string():
    assert _M(at=date(2026, 9, 21)).at == "2026-09-21"


def test_string_passes_through_unchanged():
    assert _M(at="2026-08-03T06:00:00Z").at == "2026-08-03T06:00:00Z"


def test_optional_none_and_datetime():
    assert _M(at="x").maybe is None
    assert _M(at="x", maybe=datetime(2026, 1, 2, 3, 4, 5)).maybe == "2026-01-02T03:04:05"


_RAW = re.compile(r"^\s+\w+_(?:at|date)\s*:\s*(?:Optional\[str\]|str)\b", re.M)


def test_no_router_response_model_declares_a_raw_str_timestamp():
    offenders = {}
    for f in Path("apps/api/routers").glob("*.py"):
        hits = _RAW.findall(f.read_text(encoding="utf-8"))
        if hits:
            offenders[f.name] = len(hits)
    assert not offenders, f"raw `_at`/`_date: str` fields (use IsoTimestamp): {offenders}"
