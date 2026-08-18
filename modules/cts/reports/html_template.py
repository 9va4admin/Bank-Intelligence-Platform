"""
CTS Outward Session Report — HTML renderer.

Generates a self-contained, print-ready HTML document from SessionReportData.
No external resources — all CSS is inlined (artifact must be stored and viewable
offline). WeasyPrint uses this same HTML to produce the PDF.

Design: monochrome banking document. Two-tone header (dark navy + amber accent).
Instrument table with outcome-coded row badges. Summary stat cards at top.
"""
from __future__ import annotations

from modules.cts.reports.session_report_builder import SessionReportData

_OUTCOME_BADGE = {
    "ACCEPTED":     ("badge-accepted",  "ACCEPTED"),
    "CTS_REJECTED": ("badge-rejected",  "REJECTED"),
    "MISMATCH_HELD":("badge-held",      "HELD"),
}

_PAYEE_BADGE = {
    "PROCEED":          ("ps-ok",       "CLEAR"),
    "NOT_FOUND":        ("ps-warn",     "NOT FOUND"),
    "ACCOUNT_INACTIVE": ("ps-warn",     "INACTIVE"),
    "NAME_MISMATCH":    ("ps-warn",     "NAME MISMATCH"),
}


def _outcome_badge(outcome: str) -> str:
    cls, label = _OUTCOME_BADGE.get(outcome, ("badge-held", outcome))
    return f'<span class="{cls}">{label}</span>'


def _payee_badge(status: str) -> str:
    cls, label = _PAYEE_BADGE.get(status, ("ps-warn", status))
    return f'<span class="{cls}">{label}</span>'


def _compliance_cell(result: str, violations: list[str]) -> str:
    if result == "PASS":
        return '<span class="comp-pass">PASS</span>'
    viols = ", ".join(violations)   # keep underscored names — they are the authoritative field codes
    return f'<span class="comp-fail">FAIL</span><br><small class="viol">{viols}</small>'


def _instrument_rows(report: SessionReportData) -> str:
    rows = []
    for i, row in enumerate(report.instruments, 1):
        alt = ' class="alt-row"' if i % 2 == 0 else ""
        rows.append(f"""
        <tr{alt}>
          <td class="mono">{i}</td>
          <td class="mono">{row.instrument_id}</td>
          <td class="mono">{row.cheque_number}</td>
          <td class="mono">{row.lot_number}</td>
          <td>{row.payee_display}</td>
          <td class="amt">{row.amount_range}</td>
          <td>{_payee_badge(row.payee_status)}</td>
          <td>{_compliance_cell(row.compliance_result, row.compliance_violations)}</td>
          <td>{_outcome_badge(row.outcome)}</td>
          <td class="ts">{row.scanned_at.strftime('%H:%M:%S')}</td>
        </tr>""")
    return "\n".join(rows)


def render_html(report: SessionReportData) -> str:
    stp_rate = (
        round(report.accepted_count / report.instrument_count * 100, 1)
        if report.instrument_count else 0.0
    )
    comp_rate = (
        round(report.compliance_pass_count / report.instrument_count * 100, 1)
        if report.instrument_count else 0.0
    )
    ack = report.npci_ack_ref or "—"
    generated = report.generated_at.strftime("%d %b %Y  %H:%M:%S UTC")
    clearing  = report.clearing_date.strftime("%d %b %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CTS Outward Session Report — {report.session_id}</title>
<style>
  /* ── Reset ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 11px;
    color: #1a1a2e;
    background: #fff;
    padding: 24px 32px;
  }}

  /* ── Header ── */
  .report-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 3px solid #0f3460;
    padding-bottom: 14px;
    margin-bottom: 20px;
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .brand-mark {{
    width: 36px; height: 36px;
    background: #0f3460;
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    color: #e2b04a; font-weight: 900; font-size: 18px;
  }}
  .brand-text h1 {{ font-size: 16px; font-weight: 700; color: #0f3460; }}
  .brand-text p  {{ font-size: 10px; color: #666; letter-spacing: 0.5px; text-transform: uppercase; }}
  .report-meta {{ text-align: right; font-size: 10px; color: #555; line-height: 1.7; }}
  .report-meta strong {{ color: #0f3460; }}

  /* ── Section labels ── */
  .section-label {{
    font-size: 9px; font-weight: 700; letter-spacing: 1.2px;
    text-transform: uppercase; color: #888;
    margin: 18px 0 8px;
  }}

  /* ── Info strip ── */
  .info-strip {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1px;
    background: #e5e5e5;
    border: 1px solid #e5e5e5;
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 16px;
  }}
  .info-cell {{
    background: #f7f8fa;
    padding: 8px 12px;
  }}
  .info-cell .lbl {{ font-size: 9px; color: #999; text-transform: uppercase; letter-spacing: 0.8px; }}
  .info-cell .val {{ font-size: 12px; font-weight: 600; color: #0f3460; margin-top: 2px; }}

  /* ── Stat cards ── */
  .stat-row {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 8px;
    margin-bottom: 20px;
  }}
  .stat-card {{
    border-radius: 6px;
    padding: 10px 12px;
    border: 1px solid #e5e5e5;
  }}
  .stat-card .s-label {{ font-size: 9px; color: #999; text-transform: uppercase; letter-spacing: 0.8px; }}
  .stat-card .s-val   {{ font-size: 22px; font-weight: 700; margin: 4px 0 2px; }}
  .stat-card .s-sub   {{ font-size: 9px; color: #aaa; }}
  .stat-total   {{ background: #f0f4ff; border-color: #c9d6f5; }}
  .stat-total   .s-val {{ color: #0f3460; }}
  .stat-accept  {{ background: #f0faf4; border-color: #b6e4c8; }}
  .stat-accept  .s-val {{ color: #1a7a45; }}
  .stat-reject  {{ background: #fff4f4; border-color: #f4c0c0; }}
  .stat-reject  .s-val {{ color: #b91c1c; }}
  .stat-held    {{ background: #fffbf0; border-color: #f5e0a0; }}
  .stat-held    .s-val {{ color: #92600a; }}
  .stat-comp    {{ background: #f5f0ff; border-color: #d4c0f5; }}
  .stat-comp    .s-val {{ color: #5b21b6; }}
  .stat-rate    {{ background: #f0f8ff; border-color: #b0d8f5; }}
  .stat-rate    .s-val {{ color: #0369a1; }}

  /* ── Instrument table ── */
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 10.5px;
  }}
  thead tr {{
    background: #0f3460;
    color: #fff;
  }}
  thead th {{
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 9.5px;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  tbody tr {{ border-bottom: 1px solid #f0f0f0; }}
  tbody tr.alt-row {{ background: #fafafa; }}
  tbody td {{ padding: 7px 10px; vertical-align: middle; }}
  .mono {{ font-family: 'Courier New', monospace; font-size: 10px; }}
  .amt  {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .ts   {{ color: #888; font-size: 9.5px; }}
  .viol {{ color: #b91c1c; font-size: 9px; }}

  /* ── Badges ── */
  .badge-accepted, .badge-rejected, .badge-held,
  .ps-ok, .ps-warn, .comp-pass, .comp-fail {{
    display: inline-block;
    padding: 2px 7px;
    border-radius: 3px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  .badge-accepted {{ background: #d1fae5; color: #065f46; }}
  .badge-rejected {{ background: #fee2e2; color: #991b1b; }}
  .badge-held     {{ background: #fef3c7; color: #92600a; }}
  .ps-ok          {{ background: #e0f2fe; color: #0369a1; }}
  .ps-warn        {{ background: #fff7ed; color: #9a3412; }}
  .comp-pass      {{ background: #d1fae5; color: #065f46; }}
  .comp-fail      {{ background: #fee2e2; color: #991b1b; }}

  /* ── Footer ── */
  .report-footer {{
    margin-top: 28px;
    border-top: 1px solid #e5e5e5;
    padding-top: 10px;
    display: flex;
    justify-content: space-between;
    font-size: 9px;
    color: #aaa;
  }}
  .footer-seal {{
    font-size: 9px; color: #0f3460;
    font-weight: 600; letter-spacing: 0.5px;
  }}

  /* ── Print ── */
  @media print {{
    body {{ padding: 12px 20px; }}
    .stat-row {{ grid-template-columns: repeat(6, 1fr); }}
    thead tr {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>

<div class="report-header">
  <div class="brand">
    <div class="brand-mark">A</div>
    <div class="brand-text">
      <h1>ASTRA — CTS Outward Session Report</h1>
      <p>Automated Settlement and Transaction Recognition Architecture</p>
    </div>
  </div>
  <div class="report-meta">
    <div><strong>Report ID</strong> &nbsp; {report.report_id}</div>
    <div><strong>Generated</strong> &nbsp; {generated}</div>
    <div><strong>Classification</strong> &nbsp; CONFIDENTIAL — BANKING GRADE</div>
  </div>
</div>

<div class="section-label">Session Details</div>
<div class="info-strip">
  <div class="info-cell"><div class="lbl">Session ID</div><div class="val">{report.session_id}</div></div>
  <div class="info-cell"><div class="lbl">Clearing Date</div><div class="val">{clearing}</div></div>
  <div class="info-cell"><div class="lbl">Session Type</div><div class="val">{report.session_type}</div></div>
  <div class="info-cell"><div class="lbl">NPCI Ack Ref</div><div class="val">{ack}</div></div>
  <div class="info-cell"><div class="lbl">Branch</div><div class="val">{report.branch_name}</div></div>
  <div class="info-cell"><div class="lbl">IFSC</div><div class="val">{report.branch_ifsc}</div></div>
  <div class="info-cell"><div class="lbl">Bank ID</div><div class="val">{report.bank_id}</div></div>
  <div class="info-cell"><div class="lbl">Lots</div><div class="val">{report.lot_count}</div></div>
</div>

<div class="section-label">Session Summary</div>
<div class="stat-row">
  <div class="stat-card stat-total">
    <div class="s-label">Total</div>
    <div class="s-val">{report.instrument_count}</div>
    <div class="s-sub">instruments</div>
  </div>
  <div class="stat-card stat-accept">
    <div class="s-label">Accepted</div>
    <div class="s-val">{report.accepted_count}</div>
    <div class="s-sub">to NGCH</div>
  </div>
  <div class="stat-card stat-reject">
    <div class="s-label">Rejected</div>
    <div class="s-val">{report.rejected_count}</div>
    <div class="s-sub">CTS non-compliant</div>
  </div>
  <div class="stat-card stat-held">
    <div class="s-label">Held</div>
    <div class="s-val">{report.held_count}</div>
    <div class="s-sub">mismatch queue</div>
  </div>
  <div class="stat-card stat-comp">
    <div class="s-label">CTS Pass</div>
    <div class="s-val">{report.compliance_pass_count}</div>
    <div class="s-sub">{comp_rate}% compliance rate</div>
  </div>
  <div class="stat-card stat-rate">
    <div class="s-label">STP Rate</div>
    <div class="s-val">{stp_rate}%</div>
    <div class="s-sub">straight-through</div>
  </div>
</div>

<div class="section-label">Instrument Detail</div>
<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Instrument ID</th>
      <th>Cheque No.</th>
      <th>Lot</th>
      <th>Payee</th>
      <th>Amount</th>
      <th>Payee Status</th>
      <th>CTS-2010</th>
      <th>Outcome</th>
      <th>Time</th>
    </tr>
  </thead>
  <tbody>
    {_instrument_rows(report)}
  </tbody>
</table>

<div class="report-footer">
  <div>
    Report ID: {report.report_id} &nbsp;·&nbsp;
    Session: {report.session_id} &nbsp;·&nbsp;
    Branch: {report.branch_ifsc} &nbsp;·&nbsp;
    Generated: {generated}
  </div>
  <div class="footer-seal">
    ASTRA PLATFORM · STATEMENT OF RECORD · CONFIDENTIAL
  </div>
</div>

</body>
</html>"""
