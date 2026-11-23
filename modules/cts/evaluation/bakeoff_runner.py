"""The runner side of the OCR bake-off (docs/research/ocr-bakeoff-plan.md): ask one model, served on the bank's own network, to read every crop in a manifest.

Rules it enforces:
  - the model endpoint must be on the bank's own network (loopback, private ranges, or an explicitly allowed host): real cheque images never go to a cloud service;
  - every model gets the same question (three fixed wordings per field), temperature 0, a fixed output length;
  - one failed call, a missing crop or an unreadable answer is recorded and the run goes on; nothing is silently dropped.
Thresholds come from the bank's settings (`resolve_settings`), never from literals here.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Sequence
from urllib.parse import urlparse

import httpx
import structlog

from modules.cts.evaluation.ocr_bakeoff import Reading, Truth
from shared.messages import get_message

log = structlog.get_logger()

_INTERNAL_SUFFIXES = (".internal", ".local", ".lan")


class EndpointNotAllowed(ValueError):
    """The model endpoint is not on the bank's own network."""


class ManifestError(ValueError):
    """The manifest is malformed."""


# -------------------------------------------------------------------------- the endpoint

def ensure_on_prem_endpoint(url: str, *, allowed_hosts: Sequence[str] = ()) -> str:
    """Return the endpoint URL without a trailing slash, or refuse it. Allowed: http or https to localhost, an address in a loopback, private or link-local range, a name under
    .internal, .local or .lan, or a host named in `allowed_hosts`. A name is never looked up in DNS: a lookalike such as localhost.evil.com is simply not allowed."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise EndpointNotAllowed(get_message("CTS_NOT_AN_HTTP_S_URL"))
    host = parsed.hostname.lower()
    if host in {h.lower() for h in allowed_hosts} or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise EndpointNotAllowed(get_message("CTS_IS_NOT_A_LOCAL_OR", host=host)) from None
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return url.rstrip("/")
    raise EndpointNotAllowed(get_message("CTS_IS_NOT_A_LOCAL_OR", host=host))


# -------------------------------------------------------------------------- the question

_JSON_TAIL = 'Answer with JSON only, exactly like {"value": "...", "confidence": 0.0}. Use null as the value if you cannot read it.'
_FIELD_NOUN = {"payee": get_message("CTS_THE_PAYEE_NAME_WRITTEN_AFTER"), "amount_words": get_message("CTS_THE_AMOUNT_WRITTEN_IN_WORDS_2"), "amount_figures": get_message("CTS_THE_AMOUNT_WRITTEN_IN_FIGURES"),
               "date": get_message("CTS_THE_DATE"), "micr_band": get_message("CTS_THE_MICR_NUMBER_LINE_AT")}
_VARIANTS = {
    1: "This is a crop of an Indian bank cheque. Read {noun}. Copy it exactly as written, in its own script, letter by letter; do not guess or complete unclear letters. " + _JSON_TAIL,
    2: "You are given an image of one field from a bank cheque. Transcribe {noun}. Keep the original script and spelling; if a letter is unclear, answer null rather than inventing it. " + _JSON_TAIL,
    3: "Look at the image and write down {noun} exactly as it appears, without translating or correcting it. " + _JSON_TAIL,
}


def build_prompt(field: str, variant: int) -> str:
    if field not in _FIELD_NOUN:
        raise ValueError(get_message("CTS_UNKNOWN_FIELD", field=field))
    if variant not in _VARIANTS:
        raise ValueError(get_message("CTS_UNKNOWN_PROMPT_VARIANT", variant=variant))
    return _VARIANTS[variant].replace("{noun}", _FIELD_NOUN[field])           # not str.format: the wording contains JSON braces


def _first_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def _find_value(node: Any) -> Any:
    if isinstance(node, dict):
        if "value" in node:
            return node["value"]
        for child in node.values():
            found = _find_value(child)
            if found is not None:
                return found
    return None


def parse_model_value(content: Optional[str]) -> Optional[str]:
    """The value the model answered, or None when there is none (no JSON, a null, an empty string, broken JSON)."""
    if not content:
        return None
    snippet = _first_json_object(content)
    if snippet is None:
        return None
    try:
        data = json.loads(snippet)
    except ValueError:
        return None
    value = _find_value(data)
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.casefold() != "null" else None


# -------------------------------------------------------------------------- the reader

@dataclass(frozen=True)
class ReadResult:
    text: Optional[str]
    failed: bool
    latency_ms: Optional[float]


class OpenAICompatReader:
    """Asks a model served through an OpenAI-compatible chat endpoint (vLLM and similar) on the bank's own network."""

    def __init__(self, endpoint: str, *, api_model: str, timeout: float, max_tokens: int, client: Optional[httpx.AsyncClient] = None, allowed_hosts: Sequence[str] = ()) -> None:
        self._endpoint = ensure_on_prem_endpoint(endpoint, allowed_hosts=allowed_hosts)
        self._model, self._timeout, self._max_tokens = api_model, timeout, max_tokens
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def read(self, image: bytes, field: str, variant: int) -> ReadResult:
        started = time.perf_counter()
        body = {
            "model": self._model, "temperature": 0, "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": build_prompt(field, variant)},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}},
            ]}],
        }
        try:
            response = await self._client.post(f"{self._endpoint}/chat/completions", json=body, timeout=self._timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning("bakeoff.read_failed", model=self._model, field=field, error_type=type(exc).__name__)
            return ReadResult(None, True, (time.perf_counter() - started) * 1000)
        return ReadResult(parse_model_value(content), False, (time.perf_counter() - started) * 1000)

    async def aclose(self) -> None:
        await self._client.aclose()


# -------------------------------------------------------------------------- manifest and run

_REQUIRED = ("item_id", "field", "crop", "text", "script", "handwritten", "quality")


def load_manifest(path: Path | str) -> tuple[list[Truth], dict[tuple[str, str], str]]:
    """Truth entries and the crop file of each (item, field). The crops and the truth stay in a git-ignored folder: they are real customer data."""
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ManifestError(get_message("CTS_THE_MANIFEST_IS_NOT_VALID")) from exc
    if not isinstance(rows, list):
        raise ManifestError(get_message("CTS_THE_MANIFEST_MUST_BE_A"))
    truths: list[Truth] = []
    crops: dict[tuple[str, str], str] = {}
    for row in rows:
        missing = [k for k in _REQUIRED if not isinstance(row, dict) or k not in row]
        if missing:
            raise ManifestError(get_message("CTS_AN_ENTRY_IS_MISSING", value=', '.join(missing)))
        key = (row["item_id"], row["field"])
        if key in crops:
            raise ManifestError(get_message("CTS_DUPLICATE_ENTRY_FOR", key_value=key[0], key_value2=key[1]))
        crops[key] = row["crop"]
        truths.append(Truth(item_id=row["item_id"], field=row["field"], text=row["text"], script=row["script"], handwritten=bool(row["handwritten"]), quality=row["quality"],
                            scoreable=bool(row.get("scoreable", True))))
    return truths, crops


async def run_model(truths: Sequence[Truth], crops: dict[tuple[str, str], str], images_dir: Path | str, reader: OpenAICompatReader, *, model_name: str, variant: int) -> list[Reading]:
    """One reading per manifest entry, in order. A missing crop file or a failed call becomes a failed reading; the run always finishes."""
    readings: list[Reading] = []
    base = Path(images_dir)
    for t in truths:
        crop = base / crops[(t.item_id, t.field)]
        try:
            image = crop.read_bytes()
        except OSError:
            readings.append(Reading(t.item_id, t.field, model_name, None, failed=True))
            continue
        result = await reader.read(image, t.field, variant)
        readings.append(Reading(t.item_id, t.field, model_name, result.text, failed=result.failed, latency_ms=result.latency_ms))
    return readings


# -------------------------------------------------------------------------- settings

@dataclass(frozen=True)
class Settings:
    guard_multiple: int
    guard_min_chars: int
    min_similarity: float
    resamples: int
    seed: int
    wrong_shown_target: float
    timeout: float
    max_tokens: int
    alpha: float


_SETTING_KEYS = {"guard_multiple": ("cts.bakeoff_length_guard_multiple", int), "guard_min_chars": ("cts.bakeoff_length_guard_min_chars", int),
                 "min_similarity": ("cts.payee_reread_min_similarity", float), "resamples": ("cts.bakeoff_bootstrap_resamples", int), "seed": ("cts.bakeoff_seed", int),
                 "wrong_shown_target": ("cts.bakeoff_wrong_shown_target", float), "timeout": ("cts.bakeoff_request_timeout_seconds", float), "max_tokens": ("cts.bakeoff_max_output_tokens", int), "alpha": ("cts.bakeoff_alpha", float)}


async def resolve_settings(getter: Callable[[str], Awaitable[Any]], overrides: dict[str, Any]) -> Settings:
    """Each value from the bank's settings through `getter`, unless a command-line override is given. A setting that does not exist raises: nothing is guessed."""
    values: dict[str, Any] = {}
    for name, (key, cast) in _SETTING_KEYS.items():
        values[name] = cast(overrides[name]) if overrides.get(name) is not None else cast(await getter(key))
    return Settings(**values)
