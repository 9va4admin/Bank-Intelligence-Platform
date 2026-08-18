"""
PPSVault — Positive Pay System registry per RBI mandate.

What PPS is:
  Before issuing a cheque, the account holder registers the key details with
  their bank (drawee bank) via internet banking / mobile / branch.  At clearing
  time, ASTRA verifies the presented cheque against this registry.

Exactly five fields the RBI mandate requires the drawer to declare:
  account_number, cheque_number, amount, payee_name, cheque_date

  cheque_series_start / cheque_series_end do NOT belong here — those are
  Cheque Leaf Vault concepts.  PPS is always one declaration per specific leaf.

  valid_from / valid_to are not separate fields — validity is always
  cheque_date + 90 days (RBI 3-month rule); computed, never stored.

Two storage tiers:
  Tier 1 (hot):     Redis Cluster — sub-ms lookup during clearing window.
                    Key: pps:{bank_id}:{hmac_sha256(pepper, bank_id:account_number)}:{cheque_number}
                    Value: Redis hash with amount_paise, payee, cheque_date, status, npci_flag.
                    TTL: (cheque_date + 90 days - today) in seconds — auto-expires after validity.

  Tier 2 (durable): YugabyteDB cts.pps_vault_entries — source of truth.
                    Read path: Redis → YugabyteDB → HUMAN_REVIEW on miss.
                    Write path: DB upsert first, then Redis.

History: before every UPDATE or CANCEL, current row is snapshotted to
  cts.pps_vault_entries_history with changed_by, changed_at, change_action.

Vault miss / Redis error / DB error ALWAYS routes to HUMAN_REVIEW.
AUTO_RETURN is never a valid outcome from this vault.
Raw account numbers never appear as Redis keys, DB columns, or logs.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_CHEQUE_VALIDITY_DAYS = 90   # RBI 3-month window


@dataclass(frozen=True)
class PPSResult:
    outcome: str                          # "FOUND" | "HUMAN_REVIEW"
    pps_entry: Optional[dict[str, Any]] = None
    miss_reason: Optional[str] = None     # "PPS_MISS" | "VAULT_ERROR" | None


class PPSVault:
    def __init__(self, bank_id: str, pepper: str, db_pool=None) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._db_pool = db_pool
        self._redis = None
        self._ready = False
        self._cache: dict[str, dict[str, Any]] = {}

    def connect(self, redis_client=None) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            import redis  # type: ignore[import]
            self._redis = redis.Redis()
        self._ready = True

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "PPSVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _account_hash(self, account_number: str) -> str:
        return hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _make_key(self, account_number: str, cheque_number: str) -> str:
        """Redis key: pps:{bank_id}:{hmac}:{cheque_number}"""
        return f"pps:{self._bank_id}:{self._account_hash(account_number)}:{cheque_number}"

    @staticmethod
    def _compute_ttl(cheque_date: date) -> int:
        """TTL in seconds until this PPS entry expires (cheque_date + 90 days)."""
        expires = cheque_date + timedelta(days=_CHEQUE_VALIDITY_DAYS)
        remaining = (expires - date.today()).days
        return max(remaining * 86400, 3600)  # minimum 1 h even if near expiry

    # ------------------------------------------------------------------
    # Primary read path
    # ------------------------------------------------------------------

    async def lookup(self, account_number: str, cheque_number: str) -> PPSResult:
        """
        Priority: process cache → Redis → YugabyteDB → HUMAN_REVIEW.
        Returns a PPSResult with the vault entry dict on FOUND.
        The entry contains: amount_paise, payee, cheque_date, status, npci_flag (optional).
        """
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)

        # 1. Process cache
        if key in self._cache:
            return PPSResult(outcome="FOUND", pps_entry=self._cache[key])

        # 2. Redis
        try:
            raw = self._redis.hgetall(key)
        except Exception as exc:
            log.warning(
                "pps_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=self._bank_id,
                error=str(exc),
            )
            return PPSResult(outcome="HUMAN_REVIEW", miss_reason="VAULT_ERROR")

        if raw:
            entry = _decode(raw)
            if "amount_paise" in entry:
                try:
                    entry["amount"] = int(entry["amount_paise"]) / 100
                except (ValueError, TypeError):
                    pass
            self._cache[key] = entry
            return PPSResult(outcome="FOUND", pps_entry=entry)

        # 3. YugabyteDB fallback
        if self._db_pool is not None:
            try:
                row = await self._load_from_db(
                    self._account_hash(account_number), cheque_number
                )
            except Exception as exc:
                log.warning(
                    "pps_vault.db_error",
                    account_last4=account_number[-4:],
                    bank_id=self._bank_id,
                    error=str(exc),
                )
                return PPSResult(outcome="HUMAN_REVIEW", miss_reason="VAULT_ERROR")

            if row:
                entry = dict(row)
                entry["amount"] = entry.get("amount_paise", 0) / 100
                if entry.get("cheque_date"):
                    entry["cheque_date"] = str(entry["cheque_date"])
                self._cache[key] = entry
                self._backfill_redis(key, entry)
                log.info(
                    "pps_vault.db_hit_redis_backfilled",
                    account_last4=account_number[-4:],
                    bank_id=self._bank_id,
                    cheque_number=cheque_number,
                )
                return PPSResult(outcome="FOUND", pps_entry=entry)

        log.info(
            "pps_vault.miss",
            account_last4=account_number[-4:],
            cheque_number=cheque_number,
            bank_id=self._bank_id,
        )
        return PPSResult(outcome="HUMAN_REVIEW", miss_reason="PPS_MISS")

    # ------------------------------------------------------------------
    # Write path — called by VaultUploadProcessor and CBS SFTP sync
    # ------------------------------------------------------------------

    async def store_pps(
        self,
        account_number: str,
        cheque_number: str,
        cheque_date: date,
        amount_paise: int,
        payee: str,
        registered_by: str,
        action: str = "UPSERT",
        registration_channel: Optional[str] = None,
        cbs_pps_ref: Optional[str] = None,
        npci_flag: Optional[str] = None,
        upload_batch_id: Optional[str] = None,
    ) -> None:
        """
        Write a PPS registration to DB (durable) then Redis (hot).

        amount_paise: amount in paise (₹1 = 100 paise) — stored exact for matching.
        cheque_date: date written on the cheque face.
        payee: plaintext payee name (stored encrypted in DB, plaintext in Redis).
        TTL: computed from cheque_date + 90 days.
        action: UPSERT | INSERT_ONLY | UPDATE_ONLY | CANCEL (= DEACTIVATE)
        """
        self._assert_ready()
        account_hash = self._account_hash(account_number)
        key = self._make_key(account_number, cheque_number)
        expires_at = cheque_date + timedelta(days=_CHEQUE_VALIDITY_DAYS)
        ttl = self._compute_ttl(cheque_date)

        from shared.utils.masking import mask_amount
        amount_rupees = amount_paise / 100
        amount_range = mask_amount(amount_rupees)

        self._cache.pop(key, None)

        if self._db_pool is not None:
            async with self._db_pool.acquire() as conn:
                async with conn.transaction():
                    existing = await conn.fetchrow(
                        """
                        SELECT entry_id, status, amount_paise, cheque_date,
                               expires_at, registration_channel, registered_by
                        FROM cts.pps_vault_entries
                        WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                        """,
                        self._bank_id, account_hash, cheque_number,
                    )
                    if existing and action == "INSERT_ONLY":
                        log.info("pps_vault.insert_skip_existing",
                                 cheque_number=cheque_number, bank_id=self._bank_id)
                        return
                    if not existing and action in ("UPDATE_ONLY", "CANCEL"):
                        log.info("pps_vault.update_skip_missing",
                                 cheque_number=cheque_number, bank_id=self._bank_id)
                        return

                    # Snapshot before any modification
                    if existing and action in ("UPDATE_ONLY", "UPSERT", "CANCEL"):
                        await conn.execute(
                            """
                            INSERT INTO cts.pps_vault_entries_history
                              (entry_id, bank_id, account_hash, cheque_number,
                               cheque_date, amount_paise, amount_range,
                               status, expires_at, registration_channel,
                               registered_by, change_action, changed_by,
                               changed_at, upload_batch_id)
                            SELECT entry_id, bank_id, account_hash, cheque_number,
                                   cheque_date, amount_paise, amount_range,
                                   status, expires_at, registration_channel,
                                   registered_by, $4, $5, now(), $6
                            FROM cts.pps_vault_entries
                            WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                            """,
                            self._bank_id, account_hash, cheque_number,
                            action, registered_by, upload_batch_id,
                        )

                    new_status = "CANCELLED" if action == "CANCEL" else "REGISTERED"

                    # payee_name_enc: store encrypted in DB via pgcrypto
                    # For now stored as plaintext bytes (pgcrypto key integration is
                    # handled at the DB trigger level or by the CBS connector layer)
                    payee_bytes = payee.encode("utf-8") if payee else None

                    await conn.execute(
                        """
                        INSERT INTO cts.pps_vault_entries
                          (bank_id, account_hash, account_last4, cheque_number,
                           cheque_date, amount_paise, amount_range,
                           payee_name_enc, status, expires_at,
                           registration_channel, cbs_pps_ref,
                           registered_by, upload_batch_id,
                           registered_at, last_synced_at, created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                                now(),now(),now())
                        ON CONFLICT (bank_id, account_hash, cheque_number)
                        DO UPDATE SET
                            cheque_date          = EXCLUDED.cheque_date,
                            amount_paise         = EXCLUDED.amount_paise,
                            amount_range         = EXCLUDED.amount_range,
                            payee_name_enc       = EXCLUDED.payee_name_enc,
                            status               = EXCLUDED.status,
                            expires_at           = EXCLUDED.expires_at,
                            registration_channel = EXCLUDED.registration_channel,
                            cbs_pps_ref          = EXCLUDED.cbs_pps_ref,
                            registered_by        = EXCLUDED.registered_by,
                            upload_batch_id      = EXCLUDED.upload_batch_id,
                            last_synced_at       = now()
                        """,
                        self._bank_id, account_hash, account_number[-4:], cheque_number,
                        cheque_date, amount_paise, amount_range,
                        payee_bytes, new_status, expires_at,
                        registration_channel, cbs_pps_ref,
                        registered_by, upload_batch_id,
                    )

        # Redis — plaintext for fast matching; TTL handles expiry automatically
        if action == "CANCEL":
            try:
                self._redis.delete(key)
            except Exception as exc:
                log.warning("pps_vault.redis_delete_failed",
                            cheque_number=cheque_number, error=str(exc))
        else:
            mapping: dict[str, str] = {
                "amount_paise": str(amount_paise),
                "payee": payee,
                "cheque_date": str(cheque_date),
                "status": "REGISTERED",
            }
            if npci_flag:
                mapping["npci_flag"] = npci_flag
            try:
                self._redis.hset(key, mapping=mapping)
                self._redis.expire(key, ttl)
            except Exception as exc:
                log.warning("pps_vault.redis_store_failed",
                            cheque_number=cheque_number, error=str(exc))

        log.info(
            "pps_vault.stored",
            account_last4=account_number[-4:],
            cheque_number=cheque_number,
            cheque_date=str(cheque_date),
            amount_range=amount_range,
            action=action,
            bank_id=self._bank_id,
        )

    # ------------------------------------------------------------------
    # Legacy store() — kept for VaultSyncWorkflow CBS batch sync compat
    # ------------------------------------------------------------------

    async def store(
        self,
        account_number: str,
        cheque_number: str,
        amount: float,
        payee: str,
        ttl_seconds: Optional[int] = None,
        cheque_date: Optional[date] = None,
    ) -> None:
        """
        Legacy single-tier write. Prefer store_pps() for all new code.
        ttl_seconds is ignored if cheque_date is provided (TTL computed from date).
        """
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)
        self._cache.pop(key, None)

        mapping: dict[str, str] = {
            "amount_paise": str(int(amount * 100)),
            "payee": payee,
            "cheque_number": cheque_number,
        }
        if cheque_date:
            mapping["cheque_date"] = str(cheque_date)
            ttl_seconds = self._compute_ttl(cheque_date)

        self._redis.hset(key, mapping=mapping)
        if ttl_seconds:
            self._redis.expire(key, ttl_seconds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_from_db(self, account_hash: str, cheque_number: str):
        async with self._db_pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT amount_paise, amount_range, cheque_date,
                       status, expires_at, registration_channel
                FROM cts.pps_vault_entries
                WHERE bank_id=$1 AND account_hash=$2 AND cheque_number=$3
                  AND status = 'REGISTERED'
                """,
                self._bank_id, account_hash, cheque_number,
            )

    def _backfill_redis(self, key: str, entry: dict) -> None:
        try:
            mapping = {
                "amount_paise": str(entry.get("amount_paise", 0)),
                "payee": "",   # payee_name_enc not decrypted here — payee field will be blank
                "cheque_date": str(entry.get("cheque_date", "")),
                "status": entry.get("status", "REGISTERED"),
            }
            cheque_date_raw = entry.get("cheque_date")
            if cheque_date_raw:
                try:
                    cd = date.fromisoformat(str(cheque_date_raw))
                    ttl = self._compute_ttl(cd)
                    self._redis.hset(key, mapping=mapping)
                    self._redis.expire(key, ttl)
                    return
                except (ValueError, TypeError):
                    pass
            self._redis.hset(key, mapping=mapping)
        except Exception as exc:
            log.warning("pps_vault.redis_backfill_failed", key=key[:50], error=str(exc))


def _decode(raw: dict) -> dict[str, Any]:
    return {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in raw.items()
    }
