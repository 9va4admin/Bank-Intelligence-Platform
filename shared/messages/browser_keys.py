"""Which messages can the web app ask for? Everything else (API errors, audit text, workflow messages) is resolved on the server and reaches
the browser as finished text, so shipping it in the browser bundle only makes the first page load heavier."""
import re
from pathlib import Path

_TOKEN = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
_PREFIX_TEMPLATE = re.compile(r"`([A-Z][A-Z0-9_]*_)\$\{")                      # msg(`CTS_WF_BUCKET_${code}`)
_PREFIX_CONCAT = re.compile(r"""['"]([A-Z][A-Z0-9_]*_)['"]\s*\+""")            # 'CTS_OUT_Q_BUCKET_' + code


def web_message_keys(src_dir: Path, all_keys: set) -> set:
    """Keys named in the web source (by exact name, or by a template/concatenation prefix). Tests and the generated bundles are ignored."""
    found, prefixes = set(), set()
    for path in Path(src_dir).rglob("*"):
        if path.suffix not in (".js", ".jsx") or "locales" in path.parts or ".test." in path.name or "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.update(t for t in _TOKEN.findall(text) if t in all_keys)
        prefixes.update(_PREFIX_TEMPLATE.findall(text))
        prefixes.update(_PREFIX_CONCAT.findall(text))
    for prefix in prefixes:
        found.update(k for k in all_keys if k.startswith(prefix))
    return found
