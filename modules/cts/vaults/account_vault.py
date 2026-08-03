"""
AccountVault — two-tier store for account operational profiles.

Stores branch contact details synced from CBS (branch_manager_email,
branch_contact_email, etc.) so Hold notifications can be dispatched
without a live CBS call during the IET window.

Tier 1 (hot):    Redis Cluster  — sub-millisecond lookup.
                 Key:   acct:{bank_id}:{hmac_sha256(bank_id:account_number)}
                 Value: Redis hash of profile fields.

Tier 2 (durable): YugabyteDB cts.account_vault
                 Source of truth. Survives Redis restart.
                 VaultSyncWorkflow warms Redis from here.

Read path:
  1. In-memory process cache (invalidated on write)
  2. Redis  → decode hash → return AccountVaultProfile
  3. YugabyteDB → backfill Redis → return
  4. Miss everywhere → HUMAN_REVIEW (NEVER AUTO_RETURN)

Write path (store_profile):
  1. Upsert to YugabyteDB (durable first)
  2. Hmset to Redis
  3. Invalidate local cache

Key format: acct:{bank_id}:{hmac_sha256(bank_id:account_number)}
Raw account numbers NEVER appear as Redis keys or in the local cache.

Vault miss / Redis error / DB error ALWAYS routes to HUMAN_REVIEW.
AUTO_RETURN is never a valid outcome from this vault.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class AccountVaultProfile:
    account_number_last4: str
    account_type: str
    branch_code: str
    branch_name: str
    branch_ifsc: str
    branch_manager_email: str
    branch_contact_email: str
    branch_contact_phone: str
    last_synced_at: str


@dataclass(frozen=True)
class AccountVaultResult:
    outcome: str                              # "FOUND" | "HUMAN_REVIEW"
    profile: Optional[AccountVaultProfile] = None
    miss_reason: Optional[str] = None         # "VAULT_MISS" | "VAULT_ERROR" | None


def _profile_from_dict(raw: dict[str, Any]) -> AccountVaultProfile:
    normalised = {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in raw.items()
    }

    def _s(key: str) -> str:
        return str(normalised.get(key, ""))

    return AccountVaultProfile(
        account_number_last4=_s("account_number_last4"),
        account_type=_s("account_type"),
        branch_code=_s("branch_code"),
        branch_name=_s("branch_name"),
        branch_ifsc=_s("branch_ifsc"),
        branch_manager_email=_s("branch_manager_email"),
        branch_contact_email=_s("branch_contact_email"),
        branch_contact_phone=_s("branch_contact_phone"),
        last_synced_at=_s("last_synced_at"),
    )


class AccountVault:
    def __init__(self, bank_id: str, pepper: str, db_pool=None) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._redis = None
        self._db_pool = db_pool
        self._ready = False
        self._cache: dict[str, dict[str, Any]] = {}

    def connect(self, redis_client=None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis  # type: ignore[import]
            self._redis = redis.Redis()
        self._ready = True

    def _make_key(self, account_number: str) -> str:
        digest = hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"acct:{self._bank_id}:{digest}"

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "AccountVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def lookup(self, account_number: str, bank_id: str) -> AccountVaultResult:
        self._assert_ready()
        key = self._make_key(account_number)

        # 1. Process-local cache
        if key in self._cache:
            return AccountVaultResult(
                outcome="FOUND",
                profile=_profile_from_dict(self._cache[key]),
            )

        # 2. Redis
        try:
            raw = self._redis.hgetall(key)
        except Exception as exc:
            log.warning(
                "account_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            return AccountVaultResult(outcome="HUMAN_REVIEW", miss_reason="VAULT_ERROR")

        if raw:
            self._cache[key] = raw
            return AccountVaultResult(
                outcome="FOUND",
                profile=_profile_from_dict(raw),
            )

        # 3. YugabyteDB fallback
        if self._db_pool is not None:
            try:
                row = await self._load_from_db(key)
            except Exception as exc:
                log.warning(
                    "account_vault.db_error",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                    error=str(exc),
                )
                return AccountVaultResult(outcome="HUMAN_REVIEW", miss_reason="VAULT_ERROR")

            if row:
                self._backfill_redis(key, dict(row))
                self._cache[key] = dict(row)
                log.info(
                    "account_vault.db_hit_redis_backfilled",
                    account_last4=account_number[-4:],
                    bank_id=bank_id,
                )
                return AccountVaultResult(
                    outcome="FOUND",
                    profile=_profile_from_dict(dict(row)),
                )

        log.info(
            "account_vault.miss",
            account_last4=account_number[-4:],
            bank_id=bank_id,
        )
        return AccountVaultResult(outcome="HUMAN_REVIEW", miss_reason="VAULT_MISS")

    async def _load_from_db(self, key: str) -> Optional[dict]:
        account_hash = key.split(":")[-1]
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT account_number_last4, account_type,
                       branch_code, branch_name, branch_ifsc,
                       branch_manager_email, branch_contact_email,
                       branch_contact_phone, last_synced_at
                FROM cts.account_vault
                WHERE bank_id = $1 AND account_hash = $2
                """,
                self._bank_id,
                account_hash,
            )
        return dict(row) if row else None

    def _backfill_redis(self, key: str, profile: dict[str, Any]) -> None:
        try:
            pipe = self._redis.pipeline()
            pipe.hset(key, mapping={k: str(v) for k, v in profile.items()})
            pipe.execute()
        except Exception as exc:
            log.warning("account_vault.redis_backfill_failed", key=key[:30], error=str(exc))

    # ------------------------------------------------------------------
    # Bulk branch contact update (admin-triggered or periodic refresh)
    # ------------------------------------------------------------------

    async def update_branch_contacts(
        self,
        branch_code: str,
        contact: Any,
    ) -> int:
        """
        Update branch contact fields for ALL accounts at this branch_code.

        Queries YugabyteDB for all account_hashes at the branch, then
        updates the contact fields in both Redis and DB. Local cache is
        invalidated for each affected key.

        Returns the count of accounts updated. Returns 0 if no DB pool is
        configured (read-only mode) or if no accounts are at this branch.

        Raises if the DB SELECT fails — caller should handle and degrade.
        """
        self._assert_ready()

        if self._db_pool is None:
            log.warning(
                "account_vault.update_branch_contacts_no_db",
                branch_code=branch_code,
                bank_id=self._bank_id,
            )
            return 0

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT account_hash
                FROM cts.account_vault
                WHERE bank_id = $1 AND branch_code = $2
                """,
                self._bank_id,
                branch_code,
            )

        if not rows:
            return 0

        contact_fields = {
            "branch_name": contact.branch_name,
            "branch_ifsc": contact.branch_ifsc,
            "branch_manager_email": contact.branch_manager_email,
            "branch_contact_email": contact.branch_contact_email,
            "branch_contact_phone": contact.branch_contact_phone,
            "last_synced_at": contact.last_updated_in_cbs,
        }

        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cts.account_vault
                SET branch_name          = $3,
                    branch_ifsc          = $4,
                    branch_manager_email = $5,
                    branch_contact_email = $6,
                    branch_contact_phone = $7,
                    last_synced_at       = $8,
                    vault_version        = vault_version + 1
                WHERE bank_id = $1 AND branch_code = $2
                """,
                self._bank_id,
                branch_code,
                contact.branch_name,
                contact.branch_ifsc,
                contact.branch_manager_email,
                contact.branch_contact_email,
                contact.branch_contact_phone,
                contact.last_updated_in_cbs,
            )

        pipe = self._redis.pipeline()
        for row in rows:
            account_hash = row["account_hash"]
            key = f"acct:{self._bank_id}:{account_hash}"
            self._cache.pop(key, None)
            pipe.hset(key, mapping={k: str(v) for k, v in contact_fields.items()})
        pipe.execute()

        count = len(rows)
        log.info(
            "account_vault.branch_contacts_updated",
            bank_id=self._bank_id,
            branch_code=branch_code,
            accounts_updated=count,
        )
        return count

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def store_profile(
        self,
        account_number: str,
        profile: dict[str, Any],
        source: str = "CBS",
    ) -> None:
        self._assert_ready()
        key = self._make_key(account_number)
        account_hash = key.split(":")[-1]

        self._cache.pop(key, None)

        # 1. YugabyteDB upsert (durable first)
        if self._db_pool is not None:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO cts.account_vault (
                        bank_id, account_hash, account_number_last4,
                        account_type, branch_code, branch_name, branch_ifsc,
                        branch_manager_email, branch_contact_email,
                        branch_contact_phone, last_synced_at, sync_source
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (bank_id, account_hash)
                    DO UPDATE SET
                        account_type         = EXCLUDED.account_type,
                        branch_code          = EXCLUDED.branch_code,
                        branch_name          = EXCLUDED.branch_name,
                        branch_ifsc          = EXCLUDED.branch_ifsc,
                        branch_manager_email = EXCLUDED.branch_manager_email,
                        branch_contact_email = EXCLUDED.branch_contact_email,
                        branch_contact_phone = EXCLUDED.branch_contact_phone,
                        last_synced_at       = EXCLUDED.last_synced_at,
                        sync_source          = EXCLUDED.sync_source,
                        vault_version        = cts.account_vault.vault_version + 1
                    """,
                    self._bank_id,
                    account_hash,
                    profile.get("account_number_last4", account_number[-4:]),
                    profile.get("account_type", "UNKNOWN"),
                    profile.get("branch_code", ""),
                    profile.get("branch_name", ""),
                    profile.get("branch_ifsc", ""),
                    profile.get("branch_manager_email", ""),
                    profile.get("branch_contact_email", ""),
                    profile.get("branch_contact_phone", ""),
                    profile.get("last_synced_at", datetime.now(timezone.utc).isoformat()),
                    source,
                )

        # 2. Redis write
        try:
            pipe = self._redis.pipeline()
            pipe.hset(key, mapping={k: str(v) for k, v in profile.items()})
            pipe.execute()
        except Exception as exc:
            log.warning(
                "account_vault.redis_store_failed",
                account_last4=account_number[-4:],
                bank_id=self._bank_id,
                error=str(exc),
            )
