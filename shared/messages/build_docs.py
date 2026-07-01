"""
Generates docs/CTS_Msg_Taxonomy.html from shared/messages/locales/messages.yaml.

Invoked automatically by shared/messages/build.py after every successful build.
Can also be run standalone:
    python -m shared.messages.build_docs

The HTML is self-contained (no external dependencies) and renders:
  - Summary counts by domain, severity, and surface
  - Full searchable table of all message keys
  - Colour-coded severity badges
  - Variable chips per key
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_DEFAULT_YAML = Path(__file__).parent / "locales" / "messages.yaml"
_DEFAULT_OUTPUT = Path(__file__).parents[2] / "docs" / "CTS_Msg_Taxonomy.html"

SEV_COLOR = {
    "INFO":     ("#d1fae5", "#065f46", "#6ee7b7"),   # bg, text, border
    "WARN":     ("#fef9c3", "#713f12", "#fde047"),
    "ERROR":    ("#fee2e2", "#7f1d1d", "#fca5a5"),
    "CRITICAL": ("#fce7f3", "#831843", "#f9a8d4"),
}
SEV_DEFAULT = ("#f1f5f9", "#1e293b", "#cbd5e1")

SURFACE_COLOR = {
    "UI":           ("#e0f2fe", "#0c4a6e"),
    "AUDIT":        ("#f3e8ff", "#4c1d95"),
    "NOTIFICATION": ("#fef3c7", "#78350f"),
}

DOMAIN_LABELS = {
    "CTS_WF":   "CTS Workflow (Inward)",
    "CTS_OUT":  "CTS Outward Clearing",
    "CTS_COMP": "CTS Compliance / CTS-2010",
    "CTS_NGCH": "CTS NGCH Filing",
    "CTS_SMB":  "CTS Sub-Member Bank",
    "CTS_KS":   "CTS Kill Switch (RBI Mandate)",
    "CBS":      "CBS Connector",
    "VAULT":    "Signature & PPS Vault",
    "AUTH":     "Authentication & RBAC",
    "EJ":       "EJ Intelligence",
    "PLATFORM": "Platform / Infra",
}


def _domain(key: str) -> str:
    for prefix in ("CTS_WF", "CTS_OUT", "CTS_COMP", "CTS_NGCH", "CTS_SMB", "CTS_KS",
                   "VAULT", "AUTH", "CBS", "EJ", "PLATFORM"):
        if key.startswith(prefix):
            return prefix
    return "OTHER"


def _sev_badge(sev: str) -> str:
    bg, fg, border = SEV_COLOR.get(sev, SEV_DEFAULT)
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {border};'
        f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;'
        f'letter-spacing:.04em;white-space:nowrap">{sev}</span>'
    )


def _surface_chips(surfaces: list) -> str:
    parts = []
    for s in surfaces:
        bg, fg = SURFACE_COLOR.get(s, ("#f1f5f9", "#1e293b"))
        parts.append(
            f'<span style="background:{bg};color:{fg};padding:1px 7px;'
            f'border-radius:3px;font-size:11px;margin-right:3px">{s}</span>'
        )
    return "".join(parts)


def _var_chips(variables: list) -> str:
    if not variables:
        return '<span style="color:#94a3b8;font-size:11px">—</span>'
    parts = []
    for v in variables:
        parts.append(
            f'<span style="background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;'
            f'padding:1px 6px;border-radius:3px;font-size:11px;font-family:monospace;'
            f'margin-right:3px">{{{v}}}</span>'
        )
    return "".join(parts)


def build_html(yaml_path: Path = _DEFAULT_YAML, output_path: Path = _DEFAULT_OUTPUT) -> None:
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    # Bucket by domain
    domains: dict[str, list] = {d: [] for d in DOMAIN_LABELS}
    domains["OTHER"] = []
    sev_counts: dict[str, int] = {}
    surface_counts: dict[str, int] = {}

    for key, entry in raw.items():
        if key.startswith("#") or not isinstance(entry, dict):
            continue
        sev = entry.get("severity", "INFO")
        surfaces = entry.get("surface", [])
        variables = entry.get("variables", [])
        en_text = entry.get("en", "")

        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        for s in surfaces:
            surface_counts[s] = surface_counts.get(s, 0) + 1

        domain = _domain(key)
        domains.setdefault(domain, []).append({
            "key": key,
            "sev": sev,
            "surfaces": surfaces,
            "variables": variables,
            "en": en_text,
        })

    total = sum(len(v) for v in domains.values())

    # ── Domain summary rows ──────────────────────────────────────────────
    summary_rows = ""
    for prefix, label in DOMAIN_LABELS.items():
        count = len(domains.get(prefix, []))
        d_sev: dict[str, int] = {}
        for m in domains.get(prefix, []):
            d_sev[m["sev"]] = d_sev.get(m["sev"], 0) + 1
        sev_cells = "".join(
            f'<td style="text-align:center">{d_sev.get(s, "—")}</td>'
            for s in ("INFO", "WARN", "ERROR", "CRITICAL")
        )
        anchor = prefix.lower().replace("_", "-")
        summary_rows += (
            f'<tr>'
            f'<td><a href="#{anchor}" style="color:#6d28d9;text-decoration:none">{label}</a></td>'
            f'<td style="text-align:center;font-weight:600">{count}</td>'
            f'{sev_cells}'
            f'</tr>\n'
        )

    # ── Per-domain detail sections ────────────────────────────────────────
    detail_sections = ""
    for prefix, label in DOMAIN_LABELS.items():
        msgs = domains.get(prefix, [])
        if not msgs:
            continue
        anchor = prefix.lower().replace("_", "-")
        rows = ""
        for m in msgs:
            rows += (
                f'<tr class="msg-row" data-key="{m["key"].lower()}" '
                f'data-sev="{m["sev"]}" data-en="{m["en"].lower()}">'
                f'<td style="font-family:monospace;font-size:12px;white-space:nowrap;'
                f'color:#4c1d95;padding:8px 12px">{m["key"]}</td>'
                f'<td style="padding:8px 4px">{_sev_badge(m["sev"])}</td>'
                f'<td style="padding:8px 4px">{_surface_chips(m["surfaces"])}</td>'
                f'<td style="padding:8px 12px;font-size:13px;color:#1e293b;max-width:440px">'
                f'{m["en"]}</td>'
                f'<td style="padding:8px 12px">{_var_chips(m["variables"])}</td>'
                f'</tr>\n'
            )
        detail_sections += f"""
<section id="{anchor}" style="margin-bottom:48px">
  <h2 style="font-size:17px;font-weight:700;color:#1e293b;margin:0 0 12px;
             border-bottom:2px solid #e0e7ff;padding-bottom:8px">
    {label}
    <span style="font-size:13px;font-weight:400;color:#64748b;margin-left:8px">
      ({len(msgs)} messages)
    </span>
  </h2>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead>
      <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0">
        <th style="text-align:left;padding:8px 12px;color:#475569;font-size:11px;
                   text-transform:uppercase;letter-spacing:.05em">Key</th>
        <th style="text-align:left;padding:8px 4px;color:#475569;font-size:11px;
                   text-transform:uppercase;letter-spacing:.05em">Severity</th>
        <th style="text-align:left;padding:8px 4px;color:#475569;font-size:11px;
                   text-transform:uppercase;letter-spacing:.05em">Surface</th>
        <th style="text-align:left;padding:8px 12px;color:#475569;font-size:11px;
                   text-transform:uppercase;letter-spacing:.05em">English Text</th>
        <th style="text-align:left;padding:8px 12px;color:#475569;font-size:11px;
                   text-transform:uppercase;letter-spacing:.05em">Variables</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</section>
"""

    # ── Severity pill summary ────────────────────────────────────────────
    sev_pills = ""
    for sev in ("INFO", "WARN", "ERROR", "CRITICAL"):
        count = sev_counts.get(sev, 0)
        bg, fg, border = SEV_COLOR.get(sev, SEV_DEFAULT)
        sev_pills += (
            f'<div style="background:{bg};border:1px solid {border};border-radius:8px;'
            f'padding:16px 24px;min-width:110px;text-align:center">'
            f'<div style="font-size:26px;font-weight:800;color:{fg}">{count}</div>'
            f'<div style="font-size:12px;color:{fg};font-weight:600;margin-top:4px">{sev}</div>'
            f'</div>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASTRA Message Taxonomy — CTS_Msg_Taxonomy</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f8fafc;
    color: #1e293b;
    line-height: 1.5;
  }}
  header {{
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
    color: #fff;
    padding: 32px 48px 28px;
  }}
  header h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -.01em; }}
  header p  {{ font-size: 13px; color: #a5b4fc; margin-top: 6px; }}
  .tag {{
    display: inline-block;
    background: rgba(255,255,255,.12);
    color: #c7d2fe;
    border: 1px solid rgba(255,255,255,.2);
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .05em;
    margin-right: 6px;
  }}
  main {{ max-width: 1400px; margin: 0 auto; padding: 40px 48px; }}
  .card {{
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 28px 32px;
    margin-bottom: 32px;
    box-shadow: 0 1px 3px rgba(0,0,0,.04);
  }}
  .card h3 {{
    font-size: 13px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: 18px;
  }}
  table.summary {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.summary th {{
    text-align: left; padding: 8px 12px; color: #475569;
    font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    background: #f8fafc; border-bottom: 2px solid #e2e8f0;
  }}
  table.summary td {{ padding: 9px 12px; border-bottom: 1px solid #f1f5f9; }}
  table.summary tr:last-child td {{ border-bottom: none; }}
  tbody tr.msg-row:nth-child(even) {{ background: #fafafa; }}
  tbody tr.msg-row:hover {{ background: #f0f7ff; }}
  #search-box {{
    width: 100%; padding: 10px 16px;
    border: 1px solid #cbd5e1; border-radius: 8px;
    font-size: 14px; margin-bottom: 8px;
    outline: none;
    transition: border-color .15s;
  }}
  #search-box:focus {{ border-color: #818cf8; box-shadow: 0 0 0 3px rgba(129,140,248,.15); }}
  .filter-bar {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:24px; }}
  .filter-btn {{
    padding: 5px 14px; border-radius: 20px; border: 1px solid #cbd5e1;
    background: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
    transition: all .15s;
  }}
  .filter-btn:hover {{ background: #f0f7ff; border-color: #818cf8; color: #4338ca; }}
  .filter-btn.active {{ background: #4338ca; color: #fff; border-color: #4338ca; }}
  nav.toc {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    margin-bottom: 0;
  }}
  nav.toc a {{
    display: block; padding: 10px 14px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    color: #4338ca; text-decoration: none; font-size: 13px; font-weight: 500;
    transition: all .15s;
  }}
  nav.toc a:hover {{
    background: #ede9fe; border-color: #a78bfa; color: #4c1d95;
  }}
  nav.toc .count {{
    float: right; color: #94a3b8; font-size: 12px; font-weight: 400;
  }}
  .notice {{
    background: #fef9c3; border: 1px solid #fde047; border-radius: 8px;
    padding: 12px 18px; font-size: 13px; color: #713f12; margin-bottom: 28px;
  }}
  .hidden {{ display: none !important; }}
  @media print {{
    .filter-bar, #search-box, nav.toc {{ display: none; }}
    .card {{ box-shadow: none; }}
  }}
</style>
</head>
<body>

<header>
  <p>
    <span class="tag">ASTRA</span>
    <span class="tag">CONFIDENTIAL</span>
    <span class="tag">BANKING GRADE</span>
  </p>
  <h1 style="margin-top:12px">Message Taxonomy</h1>
  <p>
    Single source of truth for all system messages —
    <strong style="color:#c7d2fe">{total} messages</strong>
    across {len(DOMAIN_LABELS)} domains.
    Generated from <code style="color:#a5b4fc">shared/messages/locales/messages.yaml</code>
    on {generated_at}.
  </p>
</header>

<main>

<div class="notice">
  ⚠️ This file is <strong>auto-generated</strong> by
  <code>python -m shared.messages.build</code>.
  Do not edit manually — edit <code>shared/messages/locales/messages.yaml</code>
  and re-run the build.
</div>

<!-- Summary card -->
<div class="card">
  <h3>Coverage Summary</h3>
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:28px">
    {sev_pills}
  </div>
  <table class="summary">
    <thead>
      <tr>
        <th>Domain</th>
        <th style="text-align:center">Total</th>
        <th style="text-align:center">INFO</th>
        <th style="text-align:center">WARN</th>
        <th style="text-align:center">ERROR</th>
        <th style="text-align:center">CRITICAL</th>
      </tr>
    </thead>
    <tbody>
      {summary_rows}
      <tr style="background:#f8fafc;font-weight:700;border-top:2px solid #e2e8f0">
        <td>Total</td>
        <td style="text-align:center">{total}</td>
        {''.join(f'<td style="text-align:center">{sev_counts.get(s, 0)}</td>' for s in ("INFO","WARN","ERROR","CRITICAL"))}
      </tr>
    </tbody>
  </table>
</div>

<!-- TOC card -->
<div class="card">
  <h3>Jump to Domain</h3>
  <nav class="toc">
    {''.join(
        f'<a href="#{p.lower().replace("_","-")}">'
        f'{l}<span class="count">{len(domains.get(p,[]))}</span></a>'
        for p, l in DOMAIN_LABELS.items() if domains.get(p)
    )}
  </nav>
</div>

<!-- Search + filter -->
<input id="search-box" type="search" placeholder="Search by key name, text, or variable…" oninput="filterMessages()">
<div class="filter-bar">
  <button class="filter-btn active" onclick="setSevFilter(this,'ALL')">All Severities</button>
  <button class="filter-btn" onclick="setSevFilter(this,'INFO')">INFO</button>
  <button class="filter-btn" onclick="setSevFilter(this,'WARN')">WARN</button>
  <button class="filter-btn" onclick="setSevFilter(this,'ERROR')">ERROR</button>
  <button class="filter-btn" onclick="setSevFilter(this,'CRITICAL')">CRITICAL</button>
</div>

<!-- Detail sections -->
{detail_sections}

</main>

<footer style="text-align:center;padding:24px;color:#94a3b8;font-size:12px;
               border-top:1px solid #e2e8f0;background:#fff;margin-top:24px">
  ASTRA — Automated Settlement and Transaction Recognition Architecture ·
  Precision Banking. Zero Compromise. ·
  Generated {generated_at}
</footer>

<script>
let _sevFilter = 'ALL';

function setSevFilter(btn, sev) {{
  _sevFilter = sev;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterMessages();
}}

function filterMessages() {{
  const q = document.getElementById('search-box').value.toLowerCase().trim();
  document.querySelectorAll('.msg-row').forEach(row => {{
    const keyMatch  = row.dataset.key.includes(q);
    const enMatch   = row.dataset.en.includes(q);
    const sevMatch  = _sevFilter === 'ALL' || row.dataset.sev === _sevFilter;
    const textMatch = q === '' || keyMatch || enMatch;
    row.classList.toggle('hidden', !(textMatch && sevMatch));
  }});
  // Hide section headers with no visible rows
  document.querySelectorAll('section[id]').forEach(sec => {{
    const visible = Array.from(sec.querySelectorAll('.msg-row'))
                         .some(r => !r.classList.contains('hidden'));
    sec.style.display = visible ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"CTS_Msg_Taxonomy.html written: {output_path}  ({total} messages)")


if __name__ == "__main__":
    yaml_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_YAML
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_OUTPUT
    build_html(yaml_path, output_path)
