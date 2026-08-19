"""
Auto-generate docs/CTS_Pipeline_Checks.html from the canonical pipeline registry.

Usage:
    python -m modules.cts.pipeline.build

Reads INWARD_STEPS and OUTWARD_STEPS from registry.py.
Writes docs/CTS_Pipeline_Checks.html.

Adding a new pipeline check:
  1. Add a PipelineStep to registry.py
  2. Run this script
  3. Commit both registry.py + docs/CTS_Pipeline_Checks.html together
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

from modules.cts.pipeline.registry import (
    INWARD_STEPS, OUTWARD_STEPS, REGISTRY_VERSION, PipelineStep,
)


def _badge(step: PipelineStep) -> str:
    if step.is_ai:
        return '<span class="badge badge-ai">AI</span>'
    if step.is_conditional:
        return '<span class="badge badge-cond">Conditional</span>'
    return '<span class="badge badge-std">Always</span>'


def _step_row(step: PipelineStep) -> str:
    outcomes_html = ", ".join(
        f'<code class="outcome">{html.escape(o)}</code>' for o in step.failure_outcomes
    ) if step.failure_outcomes else '<span class="muted">—</span>'

    condition_html = (
        f'<span class="condition-note">{html.escape(step.condition_note)}</span>'
        if step.is_conditional and step.condition_note
        else ""
    )

    return f"""
    <tr>
      <td class="seq">{step.seq}</td>
      <td class="step-id"><code>{html.escape(step.step_id)}</code></td>
      <td>{html.escape(step.name)}{f"<br>{condition_html}" if condition_html else ""}</td>
      <td class="tech">{html.escape(step.technology)}</td>
      <td class="source"><code>{html.escape(step.source_file)}</code></td>
      <td>{_badge(step)}</td>
      <td class="outcomes">{outcomes_html}</td>
    </tr>"""


def _pipeline_section(title: str, steps: list[PipelineStep], anchor: str) -> str:
    rows = "\n".join(_step_row(s) for s in steps)
    return f"""
  <section id="{anchor}">
    <h2>{html.escape(title)}</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Step ID</th>
            <th>Name / Condition</th>
            <th>Technology</th>
            <th>Source File</th>
            <th>Type</th>
            <th>Failure Outcomes</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </section>"""


def build_html() -> str:
    inward_section = _pipeline_section(
        f"Inward Pipeline — Drawee Bank (ChequeProcessingWorkflow · {len(INWARD_STEPS)} checks)",
        INWARD_STEPS,
        "inward",
    )
    outward_section = _pipeline_section(
        f"Outward Pipeline — Presentee Bank (OutwardScanWorkflow · {len(OUTWARD_STEPS)} checks)",
        OUTWARD_STEPS,
        "outward",
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CTS Pipeline Checks</title>
<style>
:root {{
  --bg: #f8fafc; --surface: #fff; --border: #e2e8f0;
  --text: #1e293b; --muted: #64748b; --code-bg: #f1f5f9;
  --ai: #6d28d9; --ai-bg: #ede9fe; --cond: #b45309; --cond-bg: #fef3c7;
  --std: #047857; --std-bg: #d1fae5;
  --outcome-bg: #fef2f2; --outcome: #991b1b;
  --heading: #0f172a;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --code-bg: #0f172a;
    --ai: #a78bfa; --ai-bg: #2e1065; --cond: #fcd34d; --cond-bg: #78350f;
    --std: #6ee7b7; --std-bg: #064e3b;
    --outcome-bg: #450a0a; --outcome: #fca5a5;
    --heading: #f1f5f9;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #0f172a; --surface: #1e293b; --border: #334155;
  --text: #e2e8f0; --muted: #94a3b8; --code-bg: #0f172a;
  --ai: #a78bfa; --ai-bg: #2e1065; --cond: #fcd34d; --cond-bg: #78350f;
  --std: #6ee7b7; --std-bg: #064e3b;
  --outcome-bg: #450a0a; --outcome: #fca5a5;
  --heading: #f1f5f9;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       font-size: 14px; background: var(--bg); color: var(--text); line-height: 1.5; }}
header {{ padding: 24px 32px; border-bottom: 1px solid var(--border);
         background: var(--surface); }}
header h1 {{ font-size: 20px; font-weight: 700; color: var(--heading); }}
header p {{ font-size: 13px; color: var(--muted); margin-top: 4px; }}
.toc {{ padding: 16px 32px; background: var(--surface);
       border-bottom: 1px solid var(--border); display: flex; gap: 24px; }}
.toc a {{ color: var(--ai); text-decoration: none; font-size: 13px; }}
.toc a:hover {{ text-decoration: underline; }}
main {{ padding: 32px; max-width: 1400px; }}
section {{ margin-bottom: 48px; }}
h2 {{ font-size: 16px; font-weight: 600; color: var(--heading);
     margin-bottom: 16px; padding-bottom: 8px;
     border-bottom: 2px solid var(--border); }}
.table-wrap {{ overflow-x: auto; border: 1px solid var(--border);
              border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--surface); }}
thead tr {{ background: var(--code-bg); }}
th {{ padding: 10px 12px; text-align: left; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
    border-bottom: 1px solid var(--border); white-space: nowrap; }}
td {{ padding: 10px 12px; border-bottom: 1px solid var(--border);
    vertical-align: top; }}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: var(--code-bg); }}
.seq {{ color: var(--muted); font-variant-numeric: tabular-nums;
       font-size: 12px; width: 36px; }}
.step-id code {{ font-size: 12px; background: var(--code-bg);
               padding: 2px 6px; border-radius: 4px;
               border: 1px solid var(--border); white-space: nowrap; }}
.tech {{ font-size: 12px; color: var(--muted); }}
.source code {{ font-size: 11px; color: var(--muted); }}
.condition-note {{ font-size: 11px; color: var(--cond); display: block; margin-top: 2px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px;
         font-size: 10px; font-weight: 600; letter-spacing: .4px;
         text-transform: uppercase; white-space: nowrap; }}
.badge-ai {{ background: var(--ai-bg); color: var(--ai); }}
.badge-cond {{ background: var(--cond-bg); color: var(--cond); }}
.badge-std {{ background: var(--std-bg); color: var(--std); }}
.outcomes {{ white-space: nowrap; }}
code.outcome {{ font-size: 11px; background: var(--outcome-bg);
              color: var(--outcome); padding: 1px 5px; border-radius: 4px; }}
.muted {{ color: var(--muted); }}
footer {{ padding: 16px 32px; border-top: 1px solid var(--border);
         background: var(--surface); font-size: 12px; color: var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>CTS Pipeline Checks</h1>
  <p>Auto-generated from <code>modules/cts/pipeline/registry.py</code>
     · Registry version: <strong>{REGISTRY_VERSION}</strong>
     · {len(INWARD_STEPS)} inward checks · {len(OUTWARD_STEPS)} outward checks</p>
</header>
<nav class="toc">
  <a href="#inward">Inward Pipeline</a>
  <a href="#outward">Outward Pipeline</a>
</nav>
<main>
  {inward_section}
  {outward_section}
</main>
<footer>
  Generated by <code>python -m modules.cts.pipeline.build</code> · Do not edit directly.
</footer>
</body>
</html>"""


def main() -> None:
    out_path = Path(__file__).parents[3] / "docs" / "CTS_Pipeline_Checks.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = build_html()
    out_path.write_text(content, encoding="utf-8")
    print(f"Written: {out_path}  ({len(content):,} bytes)")
    print(f"  Inward steps:  {len(INWARD_STEPS)}")
    print(f"  Outward steps: {len(OUTWARD_STEPS)}")
    print(f"  Registry version: {REGISTRY_VERSION}")


if __name__ == "__main__":
    main()
