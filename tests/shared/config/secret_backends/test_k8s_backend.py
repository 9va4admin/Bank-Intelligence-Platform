"""
Tests for K8sSecretBackend — reads secrets from Kubernetes Secret mounted files.

RED: run before the implementation exists to confirm failures.
"""
import os
import tempfile
from pathlib import Path

import pytest

from shared.config.exceptions import VaultUnavailableError


class TestK8sBackendGet:
    @pytest.fixture
    def secret_dir(self, tmp_path: Path) -> Path:
        """Temporary directory simulating a K8s Secret volume mount."""
        (tmp_path / "immudb.username").write_text("immudb", encoding="utf-8")
        (tmp_path / "redis.cts.url").write_text("redis://localhost:6379\n", encoding="utf-8")
        (tmp_path / "db.cts.password").write_text("  s3cret  \n", encoding="utf-8")
        return tmp_path

    @pytest.mark.asyncio
    async def test_get_reads_flat_file(self, secret_dir: Path):
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(secret_dir))
        await backend.initialise("test-bank")
        result = await backend.get("immudb.username")
        assert result == "immudb"

    @pytest.mark.asyncio
    async def test_get_key_is_filename_not_path(self, secret_dir: Path):
        """Dots in key are PRESERVED as dots in filename (K8s Secret flat mount)."""
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(secret_dir))
        await backend.initialise("test-bank")
        result = await backend.get("redis.cts.url")
        assert result == "redis://localhost:6379"  # trailing \n stripped

    @pytest.mark.asyncio
    async def test_get_strips_whitespace(self, secret_dir: Path):
        """File contents are strip()ped — standard K8s convention."""
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(secret_dir))
        await backend.initialise("test-bank")
        result = await backend.get("db.cts.password")
        assert result == "s3cret"

    @pytest.mark.asyncio
    async def test_get_raises_when_file_not_found(self, secret_dir: Path):
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(secret_dir))
        await backend.initialise("test-bank")
        with pytest.raises(VaultUnavailableError, match="ngch.api_key"):
            await backend.get("ngch.api_key")

    @pytest.mark.asyncio
    async def test_get_never_returns_default_on_missing(self, secret_dir: Path):
        """Critical: no silent default — same contract as Vault."""
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(secret_dir))
        await backend.initialise("test-bank")
        with pytest.raises(VaultUnavailableError):
            await backend.get("completely.missing.key")


class TestK8sBackendInitialise:
    @pytest.mark.asyncio
    async def test_initialise_succeeds_when_mount_path_exists(self, tmp_path: Path):
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path=str(tmp_path))
        await backend.initialise("test-bank")  # must not raise

    @pytest.mark.asyncio
    async def test_initialise_raises_when_mount_path_missing(self):
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend(mount_path="/nonexistent/path/astra-secrets")
        with pytest.raises(RuntimeError, match="K8s secret mount path not found"):
            await backend.initialise("test-bank")

    @pytest.mark.asyncio
    async def test_default_mount_path(self):
        """Default mount path is /var/run/secrets/astra (K8s convention)."""
        from shared.config.secret_backends.k8s_backend import K8sSecretBackend
        backend = K8sSecretBackend()
        # Don't call initialise() (path doesn't exist locally) —
        # just check the default path is set correctly.
        assert backend._mount_path.as_posix().endswith("var/run/secrets/astra")
