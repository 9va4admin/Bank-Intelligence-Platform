"""There are no clearing zones (CLAUDE.md 2.12): a bank files to one NGCH grid and its branches map to processing units.

Fails the build if backend code, Helm values or the message taxonomy bring the idea back. Migration history is exempt (it records
what once existed); cheque-image regions ("zones" of the cheque face) and infrastructure availability zones are different things.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ["apps/api", "apps/eeh", "apps/audit_service", "modules", "shared", "infra/helm", "infra/argocd"]
SKIP_PARTS = {"__pycache__", "node_modules", "tests", "versions", "chaos", "chaos-mesh"}
SKIP_FILES = {"messages.yaml", "messages.json", "service_messages.py"}
FORBIDDEN = re.compile(r"clearing[_ ]zones?|clearing_zone|\bzone_id\b|rpc[_/]zones|ClearingZone", re.I)


def _files():
    for base in SCAN:
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".yaml", ".yml", ".tpl", ".json", ".rego"} and not (SKIP_PARTS & set(p.parts)) and p.name not in SKIP_FILES:
                yield p


def test_no_clearing_zone_vocabulary_in_backend_or_deployment_files():
    hits = []
    for p in _files():
        for i, line in enumerate(p.read_text(encoding="utf8", errors="ignore").splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:90]}")
    assert hits == []


def test_message_taxonomy_has_no_clearing_zone_wording():
    import yaml
    messages = yaml.safe_load((ROOT / "shared/messages/locales/messages.yaml").read_text(encoding="utf8"))
    hits = [k for k, v in messages.items() if re.search(r"clearing[_ ]zones?|\bzones?\b:", str(v.get("en", "")), re.I) and "PROPER_ZONE" not in k and not k.startswith("UI_CONTACTSECTION_")]  # an NPCI return reason; the landing page is exempt
    assert hits == []
