"""
PPSVault — Redis-backed Positive Pay System registry.

Key format: pps:{bank_id}:{hmac_sha256(bank_id:account_number)}:{cheque_series_start}
Raw account numbers never appear as Redis keys.

Vault miss / Redis error ALWAYS routes to HUMAN_REVIEW.
AUTO_RETURN is never a valid outcome from this vault.
"""
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Optional

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class PPSResult:
    outcome: str                      # "FOUND" | "HUMAN_REVIEW"
    pps_entry: Optional[dict[str, Any]] = None
    miss_reason: Optional[str] = None  # "PPS_MISS" | "VAULT_ERROR" | None


class PPSVault:
    def __init__(self, bank_id: str, pepper: str) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
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

    def _make_key(self, account_number: str, cheque_series_start: str) -> str:
        digest = hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"pps:{self._bank_id}:{digest}:{cheque_series_start}"

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "PPSVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    async def lookup(self, account_number: str, bank_id: str, cheque_series_start: str) -> PPSResult:
        self._assert_ready()
        key = self._make_key(account_number, cheque_series_start)

        if key in self._cache:
            return PPSResult(outcome="FOUND", pps_entry=self._cache[key])

        try:
            raw = self._redis.hgetall(key)
        except Exception as exc:
            log.warning(
                "pps_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            return PPSResult(outcome="HUMAN_REVIEW", pps_entry=None, miss_reason="VAULT_ERROR")

        if not raw:
            log.info(
                "pps_vault.miss",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                cheque_series=cheque_series_start,
            )
            return PPSResult(outcome="HUMAN_REVIEW", pps_entry=None, miss_reason="PPS_MISS")

        entry = {
            k.decode() if isinstance(k, bytes) else k: (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw.items()
        }
        if "amount" in entry:
            try:
                entry["amount"] = float(entry["amount"])
            except (ValueError, TypeError):
                pass

        self._cache[key] = entry
        return PPSResult(outcome="FOUND", pps_entry=entry)

    async def store(
        self,
        account_number: str,
        cheque_series_start: str,
        amount: float,
        payee: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        self._assert_ready()
        key = self._make_key(account_number, cheque_series_start)

        self._cache.pop(key, None)

        self._redis.hset(key, mapping={
            "amount": str(amount),
            "payee": payee,
            "cheque_number": cheque_series_start,
        })
        if ttl_seconds:
            self._redis.expire(key, ttl_seconds)
