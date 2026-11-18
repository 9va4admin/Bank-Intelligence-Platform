"""Count or sample Redis keys by pattern, whether the client is the async one (scan_iter is an async generator) or a plain one (an iterator)."""
from __future__ import annotations

from typing import Any, Optional

SCAN_BATCH = 1000


async def _each(redis: Any, pattern: str, batch: int):
    it = redis.scan_iter(match=pattern, count=batch)
    if hasattr(it, "__aiter__"):
        async for key in it:
            yield key
    else:
        for key in it:
            yield key


async def count_keys(redis: Any, pattern: str, *, batch: int = SCAN_BATCH) -> int:
    """How many keys match. A failing scan raises, so the caller can say the check failed."""
    return sum([1 async for _ in _each(redis, pattern, batch)])


async def first_key(redis: Any, pattern: str, *, batch: int = 1) -> Optional[Any]:
    """One matching key, or None when there is none."""
    async for key in _each(redis, pattern, batch):
        return key
    return None
