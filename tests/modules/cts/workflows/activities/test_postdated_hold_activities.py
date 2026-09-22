"""Tests for modules/cts/workflows/activities/postdated_hold_activities.py.

Regression 1 (found live, real run 2026-09-22): `store_postdated_hold` and
`mark_hold_cancelled` both called `config_service.get("db.cts.dsn")` without
awaiting it — `config_service.get` is a coroutine function, so `dsn` was a
`coroutine` object, not a string. `asyncpg.connect(dsn)` then failed deep
inside asyncpg's DSN parsing with `'coroutine' object has no attribute
'decode'`, confirmed live: `store_postdated_hold.db_error ... error="'coroutine'
object has no attribute 'decode'"`.

Regression 2 (found live, same day, fixing regression 1 surfaced it): with the
coroutine bug fixed, `config_service.get_secret(...)` immediately raised
`RuntimeError: config_service.initialise() has not been awaited` — this
module's `config_service` is the raw module-level singleton, and (like several
other activities in this codebase — see outward_scan_activities.py,
persist_outward_instrument.py) nothing guarantees `.initialise()` ran in this
activity's execution context before first use. Fixed with the same defensive
guard those activities already use: `if not config_service._ready: await
config_service.initialise()`.

Regression 3 (found live, fixing regression 2 surfaced it): with both of the above fixed,
`conn.execute(...)` then failed with `invalid input for query argument $3: '2026-09-27'
('str' object has no attribute 'toordinal')` — asyncpg's default DATE codec only binds from a
real `date` object, not an ISO string, and this module passes `release_date` through as the
plain string it already is on the dict input. The exact same failure mode is already solved
elsewhere in this codebase (`shared/db/codecs.py`'s `register_lenient_codecs`, e.g. commit
`d423d46` and `persist_outward_instrument.py`) — just never applied to this module. Fixed by
calling `register_lenient_codecs(conn)` right after connecting, in both activities.

Regression 4 (found live, fixing regression 3 surfaced it): with the DATE codec fixed, the
*next* live call failed the same way for the `$4::timestamptz` argument: `invalid input for
query argument $4: '...' (expected a datetime.date or datetime.datetime instance, got 'str')`.
`register_lenient_codecs` only registers a codec for the DATE type, not TIMESTAMPTZ, so
`held_at` / `cancelled_at` still reached asyncpg as plain ISO strings. Fixed locally in this
module (not by widening the shared codec, to keep the blast radius contained to what was
actually tested here) via `_parse_timestamptz()`, applied to both fields.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from modules.cts.workflows.activities.postdated_hold_activities import (
    mark_hold_cancelled,
    store_postdated_hold,
)

_REAL_DSN = "postgresql://yugabyte:yugabyte@localhost:15433/yugabyte"


def _mock_config_service(ready: bool = True):
    cfg = AsyncMock()
    cfg._ready = ready
    cfg.initialise = AsyncMock()
    cfg.get_secret = AsyncMock(return_value=_REAL_DSN)
    return cfg


class TestStorePostdatedHold:
    @pytest.mark.asyncio
    async def test_connects_with_the_actual_dsn_string_not_a_coroutine(self):
        """The bug, directly: asyncpg.connect must receive a real string. Before the
        fix, it received an un-awaited coroutine object instead."""
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch(
            "shared.config.config_service.config_service", cfg
        ), patch("asyncpg.connect", AsyncMock(return_value=mock_conn)) as mock_connect:
            await store_postdated_hold({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "release_date": "2026-10-01",
                "held_at": "2026-09-22T10:00:00Z",
            })

        assert mock_connect.await_count == 1
        called_dsn = mock_connect.await_args.args[0]
        assert isinstance(called_dsn, str), (
            f"asyncpg.connect was called with {type(called_dsn)!r} instead of a str — "
            "config_service.get_secret(...) was not awaited"
        )
        assert called_dsn == _REAL_DSN

    @pytest.mark.asyncio
    async def test_executes_insert_with_expected_fields(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ):
            await store_postdated_hold({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "release_date": "2026-10-01",
                "held_at": "2026-09-22T10:00:00Z",
            })

        mock_conn.execute.assert_awaited_once()
        args = mock_conn.execute.await_args.args
        assert "INSERT INTO cts.postdated_holds" in args[0]
        assert args[1:4] == ("IW-kbl-000001", "kbl", "2026-10-01")
        # held_at must reach asyncpg as a real datetime (regression 4), not the raw ISO string
        assert args[4] == datetime.fromisoformat("2026-09-22T10:00:00Z")
        mock_conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialises_config_service_when_not_ready(self):
        """Regression 2: previously this activity assumed config_service was already
        initialised by the worker's own startup and crashed with RuntimeError the moment
        that assumption didn't hold in this execution context."""
        mock_conn = AsyncMock()
        cfg = _mock_config_service(ready=False)

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ):
            await store_postdated_hold({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "release_date": "2026-10-01",
                "held_at": "2026-09-22T10:00:00Z",
            })

        cfg.initialise.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_reinitialise_config_service_when_already_ready(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service(ready=True)

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ):
            await store_postdated_hold({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "release_date": "2026-10-01",
                "held_at": "2026-09-22T10:00:00Z",
            })

        cfg.initialise.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_registers_lenient_date_codec_so_iso_date_strings_bind(self):
        """Regression 3: without this, a real DB call fails with
        "invalid input for query argument $3: ... ('str' object has no attribute
        'toordinal')" because release_date is passed through as a plain ISO string."""
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ), patch(
            "shared.db.codecs.register_lenient_codecs", AsyncMock()
        ) as mock_register:
            await store_postdated_hold({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "release_date": "2026-10-01",
                "held_at": "2026-09-22T10:00:00Z",
            })

        mock_register.assert_awaited_once_with(mock_conn)

    @pytest.mark.asyncio
    async def test_db_error_is_logged_and_reraised(self):
        cfg = _mock_config_service()
        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(side_effect=RuntimeError("db down"))
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await store_postdated_hold({
                    "instrument_id": "IW-kbl-000001",
                    "bank_id": "kbl",
                    "release_date": "2026-10-01",
                    "held_at": "2026-09-22T10:00:00Z",
                })


class TestMarkHoldCancelled:
    @pytest.mark.asyncio
    async def test_connects_with_the_actual_dsn_string_not_a_coroutine(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch(
            "shared.config.config_service.config_service", cfg
        ), patch("asyncpg.connect", AsyncMock(return_value=mock_conn)) as mock_connect:
            await mark_hold_cancelled({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "cancel_reason": "branch manager override",
                "cancelled_at": "2026-09-22T11:00:00Z",
            })

        assert mock_connect.await_count == 1
        called_dsn = mock_connect.await_args.args[0]
        assert isinstance(called_dsn, str)
        assert called_dsn == _REAL_DSN

    @pytest.mark.asyncio
    async def test_executes_update_with_expected_fields(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ):
            await mark_hold_cancelled({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "cancel_reason": "branch manager override",
                "cancelled_at": "2026-09-22T11:00:00Z",
            })

        mock_conn.execute.assert_awaited_once()
        args = mock_conn.execute.await_args.args
        assert "UPDATE cts.postdated_holds" in args[0]
        assert args[1:4] == ("IW-kbl-000001", "kbl", "branch manager override")
        # cancelled_at must reach asyncpg as a real datetime (regression 4), not the raw ISO string
        assert args[4] == datetime.fromisoformat("2026-09-22T11:00:00Z")
        mock_conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialises_config_service_when_not_ready(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service(ready=False)

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ):
            await mark_hold_cancelled({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "cancel_reason": "branch manager override",
                "cancelled_at": "2026-09-22T11:00:00Z",
            })

        cfg.initialise.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registers_lenient_date_codec(self):
        mock_conn = AsyncMock()
        cfg = _mock_config_service()

        with patch("shared.config.config_service.config_service", cfg), patch(
            "asyncpg.connect", AsyncMock(return_value=mock_conn)
        ), patch(
            "shared.db.codecs.register_lenient_codecs", AsyncMock()
        ) as mock_register:
            await mark_hold_cancelled({
                "instrument_id": "IW-kbl-000001",
                "bank_id": "kbl",
                "cancel_reason": "branch manager override",
                "cancelled_at": "2026-09-22T11:00:00Z",
            })

        mock_register.assert_awaited_once_with(mock_conn)
