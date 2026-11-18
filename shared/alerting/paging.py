"""Keyset paging for the alert lists: an opaque cursor carrying the last row's (timestamp, id), so pages stay stable while new rows arrive."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from shared.messages import get_message


@dataclass(frozen=True)
class Page:
    items: list[dict] = field(default_factory=list)
    next_cursor: Optional[str] = None


def encode_cursor(moment: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"t": moment.isoformat(), "id": row_id}).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Raises ValueError for anything that is not a cursor this module produced."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(data["t"]), str(data["id"])
    except Exception as exc:  # noqa: BLE001
        raise ValueError(get_message("ALERT_PAGING_INVALID_CURSOR")) from exc


def page_of(rows: list[Any], limit: int, time_key: str, id_key: str) -> Page:
    """`rows` was fetched with limit + 1: the extra row only says there is another page."""
    more = len(rows) > limit
    rows = rows[:limit]
    items = [dict(r) for r in rows]
    return Page(items=items, next_cursor=encode_cursor(rows[-1][time_key], rows[-1][id_key]) if more and rows else None)
