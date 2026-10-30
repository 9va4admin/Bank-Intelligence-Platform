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
from shared.messages import get_message

log = structlog.get_logger()


class EnvSecretBackend(SecretBackend):
    async def initialise(self, bank_id: str) -> None:
        env = os.environ.get("ASTRA_ENV", "development")
        allow_in_prod = os.environ.get("ASTRA_ALLOW_ENV_SECRETS", "").lower() == "true"
        if env == "production" and not allow_in_prod:
            raise RuntimeError(
                get_message("PLATFORM_ASTRA_SECRETS_BACKEND_ENV_IS")
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
                get_message("PLATFORM_SECRET_NOT_FOUND_SET_ENV", key_value=key, env_var=env_var)
            )
        return value
