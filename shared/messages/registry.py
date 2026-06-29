"""
MessageRegistry — loads YAML locale files and serves formatted messages.

Directory layout expected:
  locales/
    en/
      domain_a.yaml
      domain_b.yaml
    hi/
      domain_a.yaml   (stub — text may be empty string)

Each YAML entry:
  MY_KEY:
    text: "Hello {name}, your cheque {instrument_id} was processed."
    severity: INFO        # INFO | WARN | ERROR | CRITICAL
    surface: [UI, AUDIT]  # UI | AUDIT | NOTIFICATION
    variables: [name, instrument_id]
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
        declared = set(self.variables)
        provided = set(variables.keys())
        required = set(_TEMPLATE_VAR.findall(self.text))

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
    Loads all YAML files under locales_dir and provides look-up, formatting,
    build (→ JSON), and validation.
    """

    def __init__(self, locales_dir: Path | None = None) -> None:
        self._locales_dir = locales_dir or (Path(__file__).parent / "locales")
        self._data: dict[str, dict[str, MessageEntry]] = {}
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        locales_dir = Path(self._locales_dir)
        if not locales_dir.exists():
            log.warning("messages.locales_dir_missing", path=str(locales_dir))
            return

        for locale_dir in sorted(locales_dir.iterdir()):
            if not locale_dir.is_dir():
                continue
            locale = locale_dir.name
            self._data[locale] = {}
            for yaml_file in sorted(locale_dir.glob("*.yaml")):
                self._load_file(yaml_file, locale)

        log.info(
            "messages.loaded",
            locales=list(self._data.keys()),
            en_count=len(self._data.get("en", {})),
        )

    def _load_file(self, path: Path, locale: str) -> None:
        raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        for key, entry in raw.items():
            if locale == "en":
                self._data[locale][key] = MessageEntry(
                    key=key,
                    text=entry.get("text", ""),
                    severity=entry.get("severity", "INFO"),
                    surface=list(entry.get("surface", [])),
                    variables=list(entry.get("variables", [])),
                    locale=locale,
                )
            else:
                # Non-en files only carry text (may be empty stub)
                self._data[locale][key] = MessageEntry(
                    key=key,
                    text=entry.get("text", ""),
                    severity="",
                    surface=[],
                    variables=[],
                    locale=locale,
                )

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, key: str, locale: str = "en", **variables: str) -> str:
        """Return the formatted message string.

        Falls back to 'en' if the locale is not loaded or the key is absent.
        """
        if key not in self._data.get("en", {}):
            raise UnknownMessageKey(key)

        target_locale = locale if locale in self._data and key in self._data[locale] else "en"
        entry = self._data[target_locale][key]

        # For stubs where en metadata is needed for variable validation
        en_entry = self._data["en"][key]

        if target_locale != "en":
            # Use en entry for variable validation but return stub text
            if entry.text == "":
                return ""
            # Non-empty translated text: use it with variable formatting
            return entry.text.format(**{k: variables[k] for k in _TEMPLATE_VAR.findall(entry.text) if k in variables})

        return en_entry.format(**variables)

    def get_entry(self, key: str, locale: str = "en") -> MessageEntry:
        """Return the full MessageEntry. Always returns en entry for metadata."""
        if key not in self._data.get("en", {}):
            raise UnknownMessageKey(key)
        return self._data["en"][key]

    def keys(self, locale: str = "en") -> list[str]:
        return list(self._data.get(locale, {}).keys())

    # ── Build ─────────────────────────────────────────────────────────────────

    def build(self, output_dir: Path) -> None:
        """Write messages.{locale}.json for every loaded locale."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        en_entries = self._data.get("en", {})

        for locale, entries in self._data.items():
            payload: dict[str, Any] = {}
            for key, entry in entries.items():
                if locale == "en":
                    payload[key] = {
                        "text": entry.text,
                        "severity": entry.severity,
                        "surface": entry.surface,
                        "variables": entry.variables,
                    }
                else:
                    # Merge stub text with en metadata for runtime use
                    en = en_entries.get(key)
                    payload[key] = {
                        "text": entry.text,
                        "severity": en.severity if en else "",
                        "surface": en.surface if en else [],
                        "variables": en.variables if en else [],
                    }

            out = output_dir / f"messages.{locale}.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            log.info("messages.build_written", locale=locale, path=str(out), count=len(payload))

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of error strings. Empty list = all clean."""
        errors: list[str] = []
        en_entries = self._data.get("en", {})

        for key, entry in en_entries.items():
            # Blank en text is always an error
            if entry.text.strip() == "":
                errors.append(f"[en] '{key}': text is blank — en locale must always have text")

            # Variables declared but not used
            used = set(_TEMPLATE_VAR.findall(entry.text))
            declared = set(entry.variables)
            undeclared = used - declared
            if undeclared:
                errors.append(
                    f"[en] '{key}': variables used in text but not declared: {sorted(undeclared)}"
                )
            unused_declared = declared - used
            if unused_declared:
                errors.append(
                    f"[en] '{key}': variables declared but not used in text: {sorted(unused_declared)}"
                )

        # Non-en stubs must have all en keys
        for locale, entries in self._data.items():
            if locale == "en":
                continue
            missing_keys = set(en_entries.keys()) - set(entries.keys())
            for key in sorted(missing_keys):
                errors.append(
                    f"[{locale}] '{key}': key exists in en but missing from {locale} stub"
                )

        return errors
