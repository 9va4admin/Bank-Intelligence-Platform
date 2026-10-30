"""
K8sSecretBackend — reads secrets from Kubernetes Secret mounted files.

K8s mounts each Secret key as a flat file under the volume mount path.
Key "redis.cts.url" → /var/run/secrets/astra/redis.cts.url
(dots in K8s Secret key names are valid and preserved as-is in the filename).

Suitable for: smallest UCBs/SFBs with no HashiCorp Vault, where etcd
encryption at rest provides the equivalent security property.

Rotation: the kubelet refreshes mounted Secret files within the sync period
(default ~1 minute) without pod restart — same operational model as Vault
dynamic secrets at longer TTL.
"""
from pathlib import Path

import structlog

from shared.config.exceptions import VaultUnavailableError
from shared.config.secret_backends.base import SecretBackend
from shared.messages import get_message

log = structlog.get_logger()

_DEFAULT_MOUNT_PATH = "/var/run/secrets/astra"


class K8sSecretBackend(SecretBackend):
    def __init__(self, mount_path: str = _DEFAULT_MOUNT_PATH) -> None:
        self._mount_path = Path(mount_path)

    async def initialise(self, bank_id: str) -> None:
        if not self._mount_path.is_dir():
            raise RuntimeError(
                get_message("PLATFORM_K8S_SECRET_MOUNT_PATH_NOT", mount_path=self._mount_path, mount_path2=self._mount_path)
            )
        log.info(
            "config.secrets.k8s_backend_active",
            bank_id=bank_id,
            mount_path=str(self._mount_path),
        )

    async def get(self, key: str) -> str:
        # K8s flat mount: "redis.cts.url" → <mount_path>/redis.cts.url
        file_path = self._mount_path / key
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raise VaultUnavailableError(
                get_message("PLATFORM_SECRET_NOT_FOUND_AT_ENSURE", key_value=key, file_path=file_path, key_value2=key, mount_path=self._mount_path)
            ) from None
        except OSError as exc:
            raise VaultUnavailableError(
                get_message("PLATFORM_FAILED_TO_READ_SECRET_FROM", key_value=key, file_path=file_path, exc=exc)
            ) from exc
