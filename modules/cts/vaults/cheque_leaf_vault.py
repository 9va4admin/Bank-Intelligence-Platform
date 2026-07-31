"""
ChequeLeafVault — Redis-backed vault for issued cheque leaf status.

Key format: chq:{bank_id}:{hmac_sha256(pepper, bank_id:account_number)}:{cheque_number}
Raw account numbers never appear as Redis keys.

Lookup outcomes:
  FOUND      — key present; caller inspects .status for routing
  NOT_FOUND  — key absent; caller routes to HUMAN_REVIEW
  ERROR      — Redis unavailable; caller routes to HUMAN_REVIEW with degraded=True

Vault miss ALWAYS routes to HUMAN_REVIEW — never auto-approve.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class ChequeLeafVaultResult:
    outcome: str                    # "FOUND" | "NOT_FOUND" | "ERROR"
    status: Optional[str] = None    # "ACTIVE"|"LOST"|"STOLEN"|"CANCELLED"|"USED" — set on FOUND
    degraded: bool = False          # True on Redis/infra error


class ChequeLeafVault:
    def __init__(self, bank_id: str, pepper: str) -> None:
        self._bank_id = bank_id
        self._pepper = pepper
        self._redis = None
        self._ready = False

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
                "ChequeLeafVault.connect() has not been called. "
                "Call it during service startup before querying the vault."
            )

    def _make_key(self, account_number: str, cheque_number: str) -> str:
        digest = hmac.new(
            self._pepper.encode(),
            f"{self._bank_id}:{account_number}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"chq:{self._bank_id}:{digest}:{cheque_number}"

    async def lookup(self, account_number: str, cheque_number: str) -> ChequeLeafVaultResult:
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)

        try:
            raw = self._redis.hgetall(key)
        except Exception as exc:
            log.warning(
                "cheque_leaf_vault.redis_error",
                account_last4=account_number[-4:],
                bank_id=self._bank_id,
                error=str(exc),
            )
            return ChequeLeafVaultResult(outcome="ERROR", degraded=True)

        if not raw:
            log.info(
                "cheque_leaf_vault.miss",
                account_last4=account_number[-4:],
                cheque_number=cheque_number,
                bank_id=self._bank_id,
            )
            return ChequeLeafVaultResult(outcome="NOT_FOUND")

        entry = {
            k.decode() if isinstance(k, bytes) else k: (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw.items()
        }
        status = entry.get("status", "UNKNOWN")

        log.info(
            "cheque_leaf_vault.hit",
            account_last4=account_number[-4:],
            cheque_number=cheque_number,
            bank_id=self._bank_id,
            status=status,
        )
        return ChequeLeafVaultResult(outcome="FOUND", status=status)

    async def store(
        self,
        account_number: str,
        cheque_number: str,
        status: str,
        issued_date: Optional[str] = None,
        series_end: Optional[str] = None,
    ) -> None:
        self._assert_ready()
        key = self._make_key(account_number, cheque_number)
        mapping: dict[str, str] = {"status": status}
        if issued_date:
            mapping["issued_date"] = issued_date
        if series_end:
            mapping["series_end"] = series_end
        self._redis.hset(key, mapping=mapping)

    def _pipeline_store(
        self,
        pipe,
        account_number: str,
        cheque_number: str,
        status: str,
        issued_date: Optional[str] = None,
        series_end: Optional[str] = None,
    ) -> None:
        key = self._make_key(account_number, cheque_number)
        mapping: dict[str, str] = {"status": status}
        if issued_date:
            mapping["issued_date"] = issued_date
        if series_end:
            mapping["series_end"] = series_end
        pipe.hset(key, mapping=mapping)
