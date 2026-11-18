"""The user directory: who has signed in and with which role, whatever the identity source (platform.user_directory).

Written by the authentication service on every successful sign-in. Role-based lookups (the alert bell) read it, because users who sign in through the
bank's identity provider have no locally managed account row.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


async def record_sign_in(pool: Any, bank_id: str, user_id: str, role: str) -> None:
    """Upsert the user: first sign-in creates the row; later ones refresh the role and last_seen. Never raises: signing in must not fail because of it."""
    try:
        await pool.execute(
            "INSERT INTO platform.user_directory (bank_id, user_id, role) VALUES ($1,$2,$3) "
            "ON CONFLICT (bank_id, user_id) DO UPDATE SET role = EXCLUDED.role, last_seen = NOW(), is_active = TRUE",
            bank_id, user_id, role)
    except Exception as exc:  # noqa: BLE001
        log.warning("user_directory.record_failed", bank_id=bank_id, error=type(exc).__name__)
