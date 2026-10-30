"""Lenient asyncpg DATE codec.

asyncpg binds a DATE parameter only from a `date` object. API queries pass ISO strings (`$N::date`), which
raised inside swallowed try/except blocks and returned empty results. This codec accepts a date, datetime or a
valid ISO-8601 date string, and still rejects anything else. Reads are unchanged (DATE -> `date`).
"""
from datetime import date, datetime
from shared.messages import get_message


def encode_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()   # ValueError on garbage
    raise TypeError(get_message("PLATFORM_CANNOT_ENCODE_AS_DATE", name__=type(value).__name__))


async def register_lenient_codecs(conn) -> None:
    """asyncpg pool `init=` hook."""
    await conn.set_type_codec(
        "date", schema="pg_catalog", format="text",
        encoder=encode_date, decoder=date.fromisoformat,
    )
