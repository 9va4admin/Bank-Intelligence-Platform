"""asyncpg binds a DATE parameter from a `date` object only. ~15 API queries bind `$N::date` with an ISO
string (found live: GET /outward/lots returned [] because the query raised and was swallowed).
The lenient codec accepts a valid ISO date string OR a date, and still rejects garbage."""
import os
from datetime import date, datetime

import pytest

from shared.db.codecs import encode_date, register_lenient_codecs


def test_encoder_accepts_date_and_iso_string_and_datetime():
    assert encode_date(date(2026, 9, 21)) == "2026-09-21"
    assert encode_date("2026-09-21") == "2026-09-21"
    assert encode_date(datetime(2026, 9, 21, 12, 30)) == "2026-09-21"


@pytest.mark.parametrize("bad", ["21/09/2026", "not-a-date", "", "2026-13-40", 12345, None])
def test_encoder_rejects_garbage(bad):
    with pytest.raises((ValueError, TypeError)):
        encode_date(bad)


@pytest.mark.skipif(not os.environ.get("ASTRA_MIGRATION_TEST_ADMIN_DSN"), reason="needs the dev database")
@pytest.mark.asyncio
async def test_real_database_binds_a_string_and_returns_a_date():
    import asyncpg
    pool = await asyncpg.create_pool(os.environ["ASTRA_MIGRATION_TEST_ADMIN_DSN"], min_size=1, max_size=1,
                                     init=register_lenient_codecs)
    try:
        assert await pool.fetchval("select $1::date", "2026-09-21") == date(2026, 9, 21)     # str bound
        assert await pool.fetchval("select $1::date", date(2026, 9, 21)) == date(2026, 9, 21)  # date bound
        assert isinstance(await pool.fetchval("select current_date"), date)                   # reads unchanged
        with pytest.raises(Exception):
            await pool.fetchval("select $1::date", "garbage")
    finally:
        await pool.close()
