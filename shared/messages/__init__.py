from shared.messages.registry import MessageRegistry, MessageEntry, UnknownMessageKey, MissingVariable
from pathlib import Path

_default_registry: MessageRegistry | None = None


def _registry() -> MessageRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = MessageRegistry(
            locales_dir=Path(__file__).parent / "locales"
        )
    return _default_registry


def get_message(key: str, locale: str = "en", **variables: str) -> str:
    """Return the formatted message string for key in the given locale."""
    return _registry().get(key, locale=locale, **variables)


def get_entry(key: str, locale: str = "en") -> "MessageEntry":
    """Return the full MessageEntry with metadata."""
    return _registry().get_entry(key, locale=locale)


__all__ = [
    "get_message",
    "get_entry",
    "MessageRegistry",
    "MessageEntry",
    "UnknownMessageKey",
    "MissingVariable",
]
