"""
SignatureVault — Redis-backed store for cheque signature specimens.

Key format: sig:{bank_id}:{hmac_sha256(bank_id:account_number)}
Raw account numbers never appear as Redis keys or in local cache keys.

Vault miss / Redis error ALWAYS routes to HUMAN_REVIEW.
AUTO_RETURN is never a valid outcome from this vault.
"""
import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class VaultResult:
    outcome: str               # "FOUND" | "HUMAN_REVIEW"
    specimens: list[bytes]
    miss_reason: Optional[str] = None   # "VAULT_MISS" | "VAULT_ERROR" | None


class SignatureVault:
    def __init__(self, bank_id: str, pepper: str) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._redis = None
        self._ready = False
        self._cache: dict[str, list[bytes]] = {}

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
        return f"sig:{self._bank_id}:{digest}"

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "SignatureVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    async def get_signatures(self, account_number: str, bank_id: str) -> VaultResult:
        self._assert_ready()
        key = self._make_key(account_number)

        if key in self._cache:
            return VaultResult(outcome="FOUND", specimens=self._cache[key])

        try:
            raw = self._redis.lrange(key, 0, -1)
        except Exception as exc:
            log.warning(
                "signature_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=bank_id,
                error=str(exc),
            )
            return VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_ERROR")

        if not raw:
            log.info(
                "signature_vault.miss",
                account_last4=account_number[-4:],
                bank_id=bank_id,
            )
            return VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_MISS")

        self._cache[key] = raw
        return VaultResult(outcome="FOUND", specimens=raw)

    async def store_signatures(self, account_number: str, specimens: list[bytes]) -> None:
        self._assert_ready()
        key = self._make_key(account_number)

        self._cache.pop(key, None)

        self._redis.delete(key)
        for specimen in specimens:
            self._redis.rpush(key, specimen)
