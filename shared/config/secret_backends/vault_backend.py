"""
VaultSecretBackend — reads secrets from HashiCorp Vault KV v2.

Key path mapping: "db.cts.password" → secret/astra/{bank_id}/db/cts/password

Production-default backend for mid/large banks. The Vault agent sidecar
injects VAULT_ADDR and VAULT_TOKEN into the pod; applications never handle
Vault authentication directly.
"""
import os

import hvac
import structlog

from shared.config.exceptions import VaultUnavailableError
from shared.config.secret_backends.base import SecretBackend

log = structlog.get_logger()


class VaultSecretBackend(SecretBackend):
    def __init__(self) -> None:
        self._vault: hvac.Client | None = None
        self._bank_id: str = ""

    async def initialise(self, bank_id: str) -> None:
        vault_addr = os.environ.get("VAULT_ADDR", "")
        vault_token = os.environ.get("VAULT_TOKEN", "")
        if not vault_addr or not vault_token:
            raise RuntimeError(
                "VAULT_ADDR / VAULT_TOKEN not set — Vault agent sidecar not running. "
                "For local dev/CI use ASTRA_SECRETS_BACKEND=env; "
                "for K8s smallest-tier use ASTRA_SECRETS_BACKEND=k8s_secrets."
            )
        self._bank_id = bank_id
        self._vault = hvac.Client(url=vault_addr, token=vault_token)
        if not self._vault.is_authenticated():
            raise VaultUnavailableError(f"Vault auth failed at {vault_addr}")

    async def get(self, key: str) -> str:
        vault_path = f"secret/astra/{self._bank_id}/{key.replace('.', '/')}"
        try:
            response = self._vault.secrets.kv.v2.read_secret_version(
                path=vault_path, raise_on_deleted_version=True
            )
            return response["data"]["data"]["value"]
        except Exception as exc:
            log.error("config.vault.fetch_failed", key=key, error=str(exc))
            raise VaultUnavailableError(f"Vault fetch failed for key '{key}': {exc}") from exc
