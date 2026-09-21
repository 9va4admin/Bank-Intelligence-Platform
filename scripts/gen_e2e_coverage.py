"""Generate docs/e2e-coverage-matrix.md from evidence, not from opinion.

For every workflow and activity registered on the CTS worker it states:
  RAN LIVE      - appears in a Temporal history captured by a real run (docs/evidence/**/*.json)
  NOT RUN LIVE  - registered, but no captured real run shows it executing

Sources of "ran live": the `activities` / `children` lists inside the evidence JSON files, which the
harnesses filled from Temporal workflow history (ActivityTaskCompleted / StartChildWorkflow events).
Nothing here is inferred from unit tests; the pytest suite substitutes fake activities and is
deliberately ignored.

Usage:  python scripts/gen_e2e_coverage.py
"""
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ran_activity = defaultdict(set)     # name -> evidence files
ran_child = defaultdict(set)
LOAD_STUBBED = {"ocr_extract", "detect_alteration", "check_security_features",
                "detect_signatures", "verify_signature", "score_fraud"}

for path in sorted(glob.glob(os.path.join(ROOT, "docs", "evidence", "**", "*.json"), recursive=True)):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(data, dict):
        continue
    is_stub_load = "load_test" in rel
    for rec in data.values():
        if not isinstance(rec, dict):
            continue
        for item in rec.get("activities", []) or []:
            name, status = (item + [None, None])[:2] if isinstance(item, list) else (item, "ok")
            if status == "ok":
                if is_stub_load and name in LOAD_STUBBED:
                    continue                    # stubbed in that run: does not count as real
                ran_activity[name].add(rel)
        for child in rec.get("children", []) or []:
            ran_child[child].add(rel)

from modules.cts.worker import ALL_WORKFLOWS, _registered_activities  # noqa: E402
from modules.cts.worker_activities import BoundCTSActivities  # noqa: E402

workflows = sorted(w.__name__ for w in ALL_WORKFLOWS)
activities = sorted(a.__name__ for a in _registered_activities(BoundCTSActivities(bank_id="matrix")))

# A workflow "ran live" when it is a captured top-level workflow type or a captured child.
top_level = {"ChequeProcessingWorkflow": ["inward_real_run"], "OutwardScanWorkflow": ["outward_real_run"]}
wf_rows = []
for w in workflows:
    ev = sorted(ran_child.get(w, set()))
    for key in top_level.get(w, []):
        ev += [p for p in glob.glob(os.path.join(ROOT, "docs", "evidence", "**", f"{key}*.json"), recursive=True)]
    ev = sorted({os.path.relpath(e, ROOT).replace("\\", "/") if os.path.isabs(e) else e for e in ev})
    wf_rows.append((w, ev))

out = [
    "# ASTRA — E2E coverage matrix (generated)",
    "",
    f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M %Z').strip()} by `scripts/gen_e2e_coverage.py` from the evidence files in `docs/evidence/`._",
    "",
    "**How to read this:** `RAN LIVE` = the name appears in a Temporal history captured from a real run. "
    "`NOT RUN LIVE` = registered on the worker but no captured real run executed it. "
    "Unit tests (which use fake activities) are not counted. Activities stubbed in the AI-stubbed load test "
    "are not counted as real for that file.",
    "",
    "## Workflows",
    "| Workflow | Status | Evidence |",
    "|---|---|---|",
]
for w, ev in wf_rows:
    out.append(f"| `{w}` | {'**RAN LIVE**' if ev else 'NOT RUN LIVE'} | {', '.join(f'`{e.split(chr(47))[-1]}`' for e in ev[:3]) or '—'} |")

live = [a for a in activities if ran_activity.get(a)]
notlive = [a for a in activities if not ran_activity.get(a)]
out += ["", f"## Activities — {len(live)} ran live, {len(notlive)} not run live (of {len(activities)} registered)", "",
        "| Activity | Status | Evidence files |", "|---|---|---|"]
for a in activities:
    ev = sorted(ran_activity.get(a, []))
    out.append(f"| `{a}` | {'**RAN LIVE**' if ev else 'NOT RUN LIVE'} | {', '.join(f'`{e.split(chr(47))[-1]}`' for e in ev[:2]) or '—'} |")

out += ["", "## Workflows/activities registered but never run live — summary", "",
        "Workflows: " + (", ".join(f"`{w}`" for w, ev in wf_rows if not ev) or "none"), "",
        "Activities: " + (", ".join(f"`{a}`" for a in notlive) or "none"), ""]

path = os.path.join(ROOT, "docs", "e2e-coverage-matrix.md")
open(path, "w", encoding="utf-8").write("\n".join(out))
print(f"wrote {path}: workflows {sum(1 for _, e in wf_rows if e)}/{len(wf_rows)} live, activities {len(live)}/{len(activities)} live")
