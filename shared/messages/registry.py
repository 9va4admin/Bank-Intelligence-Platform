"""
MessageRegistry — single YAML file, Redis-backed, local in-memory cache.

Data flow:
  build() call:  messages.yaml → validate → Redis HSET → JSON files (for browser)
  app startup:   Redis HGETALL → local dict (zero-disk reads after that)
  cache miss:    reload from Redis (e.g. after Redis refresh event)
  Redis absent:  falls back to YAML → local dict (test / cold start)

Redis layout:
  astra:messages:locales      SET of locale strings (e.g. {"en", "hi"})
  astra:messages:{locale}     HASH  key → JSON entry string

JSON entry (en):  {"text":"...","severity":"INFO","surface":["UI"],"variables":["x"]}
JSON entry (hi):  {"text":"","severity":"INFO","surface":["UI"],"variables":["x"]}
                  (severity/surface/variables always mirrored from en for runtime use)

Single YAML format (messages.yaml):
  KEY_NAME:
    severity: INFO
    surface: [UI, AUDIT]
    variables: [var1, var2]
    en: "English text {var1}."
    hi: ""
"""

import json
import re
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = structlog.get_logger()

_TEMPLATE_VAR = re.compile(r"\{(\w+)\}")
_VALID_SEVERITIES = {"INFO", "WARN", "ERROR", "CRITICAL"}
_VALID_SURFACES = {"UI", "AUDIT", "NOTIFICATION"}

REDIS_LOCALES_KEY = "astra:messages:locales"
REDIS_MSG_PREFIX = "astra:messages:"


class UnknownMessageKey(KeyError):
    pass


class MissingVariable(KeyError):
    pass


@dataclass(frozen=True)
class MessageEntry:
    key: str
    text: str
    severity: str
    surface: list[str]
    variables: list[str]
    locale: str

    def format(self, **variables: str) -> str:
        required = set(_TEMPLATE_VAR.findall(self.text))
        provided = set(variables.keys())
        missing = required - provided
        if missing:
            raise MissingVariable(
                f"Message '{self.key}' requires variables {sorted(missing)} "
                f"but they were not provided."
            )
        if self.text == "":
            return ""
        return self.text.format(**{k: v for k, v in variables.items() if k in required})


class MessageRegistry:
    """
    Single-file YAML → Redis → local dict.

    Pass redis_client=None to operate in local-only mode (tests, cold start).
    Call refresh() to reload from YAML and push to Redis.
    """

    def __init__(
        self,
        messages_file: Path | None = None,
        redis_client: Any = None,
    ) -> None:
        self._file = Path(messages_file or Path(__file__).parent / "locales" / "messages.yaml")
        self._redis = redis_client
        self._cache: dict[str, dict[str, MessageEntry]] = {}
        self._load()

    # ── Loading ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._redis and self._load_from_redis():
            return
        self._load_from_yaml()

    def _load_from_redis(self) -> bool:
        """Return True if Redis had data and cache was populated."""
        try:
            locales = self._redis.smembers(REDIS_LOCALES_KEY)
            if not locales:
                return False
            locales = {loc.decode() if isinstance(loc, bytes) else loc for loc in locales}
            for locale in locales:
                raw = self._redis.hgetall(f"{REDIS_MSG_PREFIX}{locale}")
                if not raw:
                    continue
                self._cache[locale] = {}
                for raw_key, raw_val in raw.items():
                    k = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                    v = raw_val.decode() if isinstance(raw_val, bytes) else raw_val
                    d = json.loads(v)
                    self._cache[locale][k] = MessageEntry(
                        key=k,
                        text=d["text"],
                        severity=d["severity"],
                        surface=d["surface"],
                        variables=d["variables"],
                        locale=locale,
                    )
            log.info("messages.loaded_from_redis",
                     locales=list(self._cache.keys()),
                     en_count=len(self._cache.get("en", {})))
            return bool(self._cache)
        except Exception as exc:
            log.warning("messages.redis_load_failed", error=str(exc))
            return False

    def _load_from_yaml(self) -> None:
        if not self._file.exists():
            log.warning("messages.file_missing", path=str(self._file))
            return

        raw: dict[str, Any] = yaml.safe_load(self._file.read_text()) or {}
        en_entries: dict[str, dict] = {}

        # First pass — collect en metadata for all keys
        for key, entry in raw.items():
            en_entries[key] = {
                "severity": entry.get("severity", "INFO"),
                "surface": list(entry.get("surface", [])),
                "variables": list(entry.get("variables", [])),
            }

        # Discover locales (all lowercase single-word fields that aren't metadata)
        _meta = {"severity", "surface", "variables"}
        sample = next(iter(raw.values()), {}) if raw else {}
        locales = sorted(k for k in sample if k not in _meta)

        for locale in locales:
            self._cache[locale] = {}
            for key, entry in raw.items():
                meta = en_entries[key]
                self._cache[locale][key] = MessageEntry(
                    key=key,
                    text=str(entry.get(locale, "")),
                    severity=meta["severity"],
                    surface=meta["surface"],
                    variables=meta["variables"],
                    locale=locale,
                )

        log.info("messages.loaded_from_yaml",
                 locales=locales,
                 en_count=len(self._cache.get("en", {})))

    def _write_to_redis(self) -> None:
        """Push current cache to Redis. Called by build()."""
        try:
            locales = list(self._cache.keys())
            pipe = self._redis.pipeline()
            pipe.delete(REDIS_LOCALES_KEY)
            pipe.sadd(REDIS_LOCALES_KEY, *locales)
            for locale, entries in self._cache.items():
                redis_key = f"{REDIS_MSG_PREFIX}{locale}"
                pipe.delete(redis_key)
                for key, entry in entries.items():
                    pipe.hset(redis_key, key, json.dumps({
                        "text": entry.text,
                        "severity": entry.severity,
                        "surface": entry.surface,
                        "variables": entry.variables,
                    }))
            pipe.execute()
            log.info("messages.written_to_redis",
                     locales=locales,
                     en_count=len(self._cache.get("en", {})))
        except Exception as exc:
            log.error("messages.redis_write_failed", error=str(exc))
            raise

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload from YAML and push to Redis. Call after editing messages.yaml."""
        self._load_from_yaml()
        if self._redis:
            self._write_to_redis()

    def get(self, key: str, locale: str = "en", **variables: str) -> str:
        """Return formatted message string. Falls back to en if locale/key absent."""
        en_entries = self._cache.get("en", {})
        if key not in en_entries:
            raise UnknownMessageKey(key)

        target = locale if (locale in self._cache and key in self._cache[locale]) else "en"
        entry = self._cache[target][key]

        if target != "en" and entry.text == "":
            return ""

        return entry.format(**variables)

    def get_entry(self, key: str, locale: str = "en") -> MessageEntry:
        """Return MessageEntry (always returns en entry for metadata)."""
        if key not in self._cache.get("en", {}):
            raise UnknownMessageKey(key)
        return self._cache["en"][key]

    def keys(self, locale: str = "en") -> list[str]:
        return list(self._cache.get(locale, {}).keys())

    def locales(self) -> list[str]:
        return list(self._cache.keys())

    # ── Build ──────────────────────────────────────────────────────────────────

    def build(self, output_dir: Path, redis_client: Any = None) -> None:
        """
        Validate, push to Redis, and write messages.{locale}.json for the browser.
        redis_client overrides the instance client (useful when build CLI supplies its own).
        """
        if redis_client:
            self._redis = redis_client

        if self._redis:
            self._write_to_redis()

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        en_entries = self._cache.get("en", {})
        for locale, entries in self._cache.items():
            payload: dict[str, Any] = {}
            for key, entry in entries.items():
                en = en_entries.get(key)
                payload[key] = {
                    "text": entry.text,
                    "severity": en.severity if en else "",
                    "surface": en.surface if en else [],
                    "variables": en.variables if en else [],
                }
            out = output_dir / f"messages.{locale}.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            log.info("messages.json_written", locale=locale, path=str(out), count=len(payload))

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return list of error strings. Empty = clean."""
        errors: list[str] = []
        en_entries = self._cache.get("en", {})

        for key, entry in en_entries.items():
            if entry.text.strip() == "":
                errors.append(f"[en] '{key}': text is blank")

            used = set(_TEMPLATE_VAR.findall(entry.text))
            declared = set(entry.variables)
            if used - declared:
                errors.append(f"[en] '{key}': variables used but not declared: {sorted(used - declared)}")
            if declared - used:
                errors.append(f"[en] '{key}': variables declared but not used: {sorted(declared - used)}")

            if entry.severity not in _VALID_SEVERITIES:
                errors.append(f"[en] '{key}': invalid severity '{entry.severity}'")

            bad_surfaces = set(entry.surface) - _VALID_SURFACES
            if bad_surfaces:
                errors.append(f"[en] '{key}': invalid surface values: {sorted(bad_surfaces)}")

        for locale, entries in self._cache.items():
            if locale == "en":
                continue
            missing = set(en_entries.keys()) - set(entries.keys())
            for key in sorted(missing):
                errors.append(f"[{locale}] '{key}': missing from {locale} stub")

        return errors
