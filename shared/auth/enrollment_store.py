"""YugabyteDBAccountEnrollmentStore — AccountEnrollmentStore backed by asyncpg.

Reads/writes the totp_enrolled flag on platform.local_auth_accounts.
The column is added by infra/migrations/platform/versions/20260717_add_totp_enrolled.py.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


class YugabyteDBAccountEnrollmentStore:
    """Implements the AccountEnrollmentStore protocol from shared.auth.auth_service.

    Uses the same db_pool_cts asyncpg pool that YugabyteDBLocalAuthConnector uses
    — both access platform.local_auth_accounts within the same pgbouncer-cts pool.
    """

    def __init__(self, db_pool: Any) -> None:
        self._pool = db_pool

    async def is_totp_enrolled(self, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT totp_enrolled FROM platform.local_auth_accounts WHERE user_id = $1",
                user_id,
            )
        return bool(val) if val is not None else False

    async def set_totp_enrolled(self, user_id: str, enrolled: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE platform.local_auth_accounts SET totp_enrolled = $2 WHERE user_id = $1",
                user_id,
                enrolled,
            )
        log.info("auth.enrollment.set_totp", user_id=user_id, enrolled=enrolled)
