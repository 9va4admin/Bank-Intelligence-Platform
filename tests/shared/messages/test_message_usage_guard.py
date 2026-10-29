"""Guard: wording lives in shared/messages/locales/messages.yaml and nowhere else.

Three things are enforced:
  1. every message key that code asks for (get_message / get_entry in Python, msg in the web app) exists in the taxonomy;
  2. modules that have been moved onto the taxonomy stay moved: no literal error text in their API responses and no literal
     text on their screen. Add a module to GUARDED_* once it has been converted.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
YAML_KEYS = set(re.findall(r"^([A-Z][A-Z0-9_]+):\s*$", (ROOT / "shared/messages/locales/messages.yaml").read_text(encoding="utf-8"), re.M))

GUARDED_ROUTERS = ["apps/api/routers/cts_custody.py"]
GUARDED_SCREENS = ["apps/web/src/modules/cts/pages/CTSCustody.jsx"]


def _tracked(*suffixes):
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    return [f for f in out if f.endswith(suffixes) and "/tests/" not in f and ".test." not in f and not f.startswith("tests/")]


def test_every_key_the_python_code_asks_for_exists():
    missing = []
    for f in _tracked(".py"):
        text = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(?:get_message|get_entry)\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']", text):
            if m.group(1) not in YAML_KEYS:
                missing.append((f, m.group(1)))
    assert missing == []


def test_every_key_the_web_app_asks_for_exists():
    missing = []
    for f in _tracked(".js", ".jsx"):
        if not f.startswith("apps/web/"):
            continue
        text = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\bmsg\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']", text):
            if m.group(1) not in YAML_KEYS:
                missing.append((f, m.group(1)))
    assert missing == []


def test_converted_api_modules_have_no_literal_error_text():
    offenders = []
    for f in GUARDED_ROUTERS:
        for n, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"detail\s*=\s*f?[\"']", line):
                offenders.append(f"{f}:{n}")
    assert offenders == []


def test_converted_screens_have_no_literal_text():
    offenders = []
    attr = re.compile(r"\b(placeholder|aria-label|title|alt)=\"[^\"]*[A-Za-z]{3,}")
    node = re.compile(r">\s*([A-Za-z][^<>{}\n]*[A-Za-z.])\s*<")
    for f in _tracked(".jsx"):
        if f not in GUARDED_SCREENS:
            continue
        for n, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0]
            if attr.search(code) or node.search(code):
                offenders.append(f"{f}:{n}: {line.strip()[:80]}")
    assert offenders == []
