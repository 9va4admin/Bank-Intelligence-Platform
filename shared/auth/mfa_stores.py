"""TOTP secret storage implementations for TOTPMFAService.

Production: VaultTOTPSecretStore — KV v2 write at enrollment, read at verify.
Dev/test:   InMemoryTOTPSecretStore — in-process dict (never persisted).

Both implement the TOTPSecretStore protocol from shared.auth.mfa.
"""
from __future__ import annotations

import os
from typing import Optional

import structlog

log = structlog.get_logger()


class InMemoryTOTPSecretStore:
    """In-process TOTP secret store — dev, CI, and fallback when Vault unreachable.

    Secrets survive only for the lifetime of the process. Use only when
    no Vault is available and MFA enrollment persistence is not required
    (dev mode, unit tests). A loud startup warning is emitted when used as
    a production fallback so that ops cannot miss it.
    """

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def put(self, user_id: str, secret: str) -> None:
        self._d[user_id] = secret

    async def get(self, user_id: str) -> Optional[str]:
        return self._d.get(user_id)

    async def delete(self, user_id: str) -> None:
        self._d.pop(user_id, None)


class VaultTOTPSecretStore:
    """Vault KV v2 TOTP secret store.

    Stores per-user TOTP secrets at path:
        astra/{bank_id}/mfa/{user_id}

    Preferred construction: pass the shared hvac client from
    config_service.get_vault_client() so the pod only creates one Vault
    connection. Lazy-init fallback (reading VAULT_ADDR / VAULT_TOKEN from
    env) is retained for test/dev scenarios where config_service is not yet
    initialised.
    """

    def __init__(self, bank_id: str, vault_client=None) -> None:
        self._bank_id = bank_id
        self._vault = vault_client  # pre-injected from config_service when available

    def _ensure_client(self):
        if self._vault is None:
            import hvac
            vault_addr = os.environ.get("VAULT_ADDR", "")
            vault_token = os.environ.get("VAULT_TOKEN", "")
            if not vault_addr or not vault_token:
                raise RuntimeError(
                    "VAULT_ADDR / VAULT_TOKEN not set — Vault agent sidecar not running. "
                    "Pass vault_client=config_service.get_vault_client() to avoid this. "
                    "For dev/CI use ASTRA_SECRETS_BACKEND=env and the in-memory fallback."
                )
            self._vault = hvac.Client(url=vault_addr, token=vault_token)
        return self._vault

    def _path(self, user_id: str) -> str:
        return f"astra/{self._bank_id}/mfa/{user_id}"

    async def put(self, user_id: str, secret: str) -> None:
        vault = self._ensure_client()
        vault.secrets.kv.v2.create_or_update_secret(
            path=self._path(user_id),
            secret={"value": secret},
        )
        log.info("vault.totp.put", bank_id=self._bank_id, user_id=user_id)

    async def get(self, user_id: str) -> Optional[str]:
        try:
            vault = self._ensure_client()
            response = vault.secrets.kv.v2.read_secret_version(
                path=self._path(user_id),
                raise_on_deleted_version=True,
            )
            return response["data"]["data"]["value"]
        except Exception:
            return None

    async def delete(self, user_id: str) -> None:
        try:
            vault = self._ensure_client()
            vault.secrets.kv.v2.delete_latest_version_of_secret(
                path=self._path(user_id),
            )
            log.info("vault.totp.delete", bank_id=self._bank_id, user_id=user_id)
        except Exception as exc:
            log.warning(
                "vault.totp.delete_failed",
                bank_id=self._bank_id,
                user_id=user_id,
                error=str(exc),
            )
