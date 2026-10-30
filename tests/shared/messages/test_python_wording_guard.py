"""Guard: no wording typed into Python code. Error texts, response messages, titles and raised-error sentences live in
shared/messages/locales/messages.yaml and are asked for with get_message("KEY", name=value).

This runs the converter in check mode (scripts/i18n_convert_py.py --include-workflows): it reports the wording it would still move.
To fix a failure:  python scripts/i18n_convert_py.py --write   then   python -m shared.messages.build
(In a Temporal workflow file import get_message inside `with workflow.unsafe.imports_passed_through():`.)"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_no_literal_wording_left_in_python_code():
    done = subprocess.run([sys.executable, "scripts/i18n_convert_py.py", "--include-workflows"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    summary = json.loads(next(line for line in done.stdout.splitlines() if line.startswith("{")))
    assert summary.get("sites", 0) == 0, f"{summary.get('sites')} pieces of wording are still typed into Python code: run the converter"
    assert summary.get("failed", 0) == 0


def test_standalone_services_do_not_depend_on_the_shared_package():
    """sig_detector ships on its own: their container image / edge install holds only their own files, so importing shared.messages
    stops them starting (an automatic conversion once did exactly that). Their wording stays in their own code."""
    offenders = []
    for app in ("sig_detector", "ai_server", "ej_ingestion"):
        for path in (ROOT / "apps" / app).rglob("*.py"):
            if re.search(r"^\s*(from|import)\s+shared\.messages", path.read_text(encoding="utf-8", errors="ignore"), re.M):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
