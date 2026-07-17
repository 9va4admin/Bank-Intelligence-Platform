"""
EnvSecretBackend — reads secrets from ASTRA_SECRET_* environment variables.

Key mapping: "redis.cts.url" → env var ASTRA_SECRET_REDIS_CTS_URL

ONLY for dev/CI. Refuses to start in ASTRA_ENV=production unless
ASTRA_ALLOW_ENV_SECRETS=true is explicitly set (requires bank IT admin sign-off
and is explicitly NOT recommended for any bank holding customer data).
"""
import os

import structlog

from shared.config.exceptions import VaultUnavailableError
from shared.config.secret_backends.base import SecretBackend

log = structlog.get_logger()


class EnvSecretBackend(SecretBackend):
    async def initialise(self, bank_id: str) -> None:
        env = os.environ.get("ASTRA_ENV", "development")
        allow_in_prod = os.environ.get("ASTRA_ALLOW_ENV_SECRETS", "").lower() == "true"
        if env == "production" and not allow_in_prod:
            raise RuntimeError(
                "ASTRA_SECRETS_BACKEND=env is not allowed in ASTRA_ENV=production. "
                "Set ASTRA_ALLOW_ENV_SECRETS=true to override (bank IT admin sign-off required). "
                "For production, use ASTRA_SECRETS_BACKEND=vault or ASTRA_SECRETS_BACKEND=k8s_secrets."
            )
        log.warning(
            "config.secrets.env_backend_active",
            bank_id=bank_id,
            astra_env=env,
            msg="Reading secrets from environment variables — not for production use",
        )

    async def get(self, key: str) -> str:
        env_var = "ASTRA_SECRET_" + key.upper().replace(".", "_")
        value = os.environ.get(env_var)
        if value is None:
            raise VaultUnavailableError(
                f"Secret '{key}' not found. "
                f"Set env var '{env_var}' in your .env file or docker-compose environment."
            )
        return value
