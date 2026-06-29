"""
Module-level singleton.

In production, call init(redis_client=...) once at service startup.
The registry loads from Redis on first call; subsequent get_message() calls
read from the local in-memory dict — zero Redis round-trips at read time.

In tests (or cold-start without Redis), the registry falls back to messages.yaml.
"""
from pathlib import Path
from typing import Any

from shared.messages.registry import MessageRegistry, MessageEntry, UnknownMessageKey, MissingVariable

_registry: MessageRegistry | None = None


def init(redis_client: Any = None) -> MessageRegistry:
    """
    Initialise the module singleton. Call once at service startup.
    Pass a connected Redis client to enable Redis-backed loading.
    """
    global _registry
    _registry = MessageRegistry(redis_client=redis_client)
    return _registry


def _get() -> MessageRegistry:
    global _registry
    if _registry is None:
        _registry = MessageRegistry()
    return _registry


def get_message(key: str, locale: str = "en", **variables: str) -> str:
    """Return the formatted message string for key in the given locale."""
    return _get().get(key, locale=locale, **variables)


def get_entry(key: str, locale: str = "en") -> "MessageEntry":
    """Return the full MessageEntry with metadata."""
    return _get().get_entry(key, locale=locale)


__all__ = [
    "init",
    "get_message",
    "get_entry",
    "MessageRegistry",
    "MessageEntry",
    "UnknownMessageKey",
    "MissingVariable",
]
