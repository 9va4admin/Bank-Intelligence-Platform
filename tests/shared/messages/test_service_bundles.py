"""Services that ship on their own (sig_detector) cannot import the repo's `shared` package, so each carries a small message bundle
generated from the main taxonomy: messages.json (only the messages that service uses) and service_messages.py (a tiny loader)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from shared.messages.service_bundle import SERVICES, LOADER_SOURCE, service_keys, write_service_bundles

ROOT = Path(__file__).resolve().parents[3]
KEY_CALL = re.compile(r"get_message\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']")


def test_the_loader_works_with_nothing_else_installed(tmp_path):
    (tmp_path / "service_messages.py").write_text(LOADER_SOURCE, encoding="utf-8")
    (tmp_path / "messages.json").write_text(json.dumps({"en": {"A": "Hello {who}", "B": "Only English"}, "hi": {"A": "नमस्ते {who}"}}), encoding="utf-8")
    code = ("import sys; sys.path.insert(0, '.'); from service_messages import get_message; "
            "print(get_message('A', who='Ravi'), '|', get_message('A', 'hi', who='Ravi'), '|', get_message('B', 'hi'), '|', get_message('NOPE'))")
    out = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert out.stdout.strip() == "Hello Ravi | नमस्ते Ravi | Only English | NOPE", out.stderr


def test_a_missing_variable_never_crashes_the_service(tmp_path):
    (tmp_path / "service_messages.py").write_text(LOADER_SOURCE, encoding="utf-8")
    (tmp_path / "messages.json").write_text(json.dumps({"en": {"A": "Hello {who}"}}), encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); from service_messages import get_message; print(get_message('A'))"],
                         cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert out.stdout.strip() == "Hello {who}"


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_every_message_a_service_asks_for_is_in_its_bundle(service):
    directory = ROOT / service
    bundle = json.loads((directory / "messages.json").read_text(encoding="utf-8"))
    asked = service_keys(directory)
    assert asked, f"{service} uses no messages"
    assert asked <= set(bundle["en"]), sorted(asked - set(bundle["en"]))
    assert (directory / "service_messages.py").read_text(encoding="utf-8") == LOADER_SOURCE


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_a_service_does_not_import_the_shared_package(service):
    for path in (ROOT / service).rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Other `shared` imports in this service are optional (inside try/except, repo added to the path by the service itself); the message
        # package must never be imported, because the container does not hold it.
        assert not re.search(r"^\s*(from|import)\s+shared\.messages\b", text, re.M), str(path)


def test_writing_the_bundles_is_repeatable(tmp_path):
    from shared.messages.registry import MessageRegistry
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "main.py").write_text('x = get_message("UI_X", n=1)', encoding="utf-8")
    yaml = tmp_path / "messages.yaml"
    yaml.write_text('UI_X:\n  severity: INFO\n  surface: [UI]\n  variables: [n]\n  en: "Count {n}"\n  hi: ""\n', encoding="utf-8")
    registry = MessageRegistry(messages_file=yaml)
    write_service_bundles(tmp_path, registry, {"svc": "service_messages"})
    assert json.loads((tmp_path / "svc" / "messages.json").read_text(encoding="utf-8")) == {"en": {"UI_X": "Count {n}"}, "hi": {}}
