"""Abstract base class for ASTRA secret backends."""
from abc import ABC, abstractmethod


class SecretBackend(ABC):
    @abstractmethod
    async def initialise(self, bank_id: str) -> None:
        """Called once at startup. Raises RuntimeError or VaultUnavailableError if not ready."""

    @abstractmethod
    async def get(self, key: str) -> str:
        """
        Fetch a secret by key.

        Raises VaultUnavailableError when the key is not found or the backend
        is unreachable. Never returns a default — callers must handle the error.
        """

    async def shutdown(self) -> None:
        """Override for backends that hold open connections."""
