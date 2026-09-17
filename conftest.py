"""Root conftest.py — ASTRA CTS Processing Digest generator.

After every test run, produces a timestamped HTML digest in test-reports/.
Each cheque instrument that a test processes and registers appears in the
digest with its full pipeline trace:
  OCR → Alteration → CTS-2010 → Stop Payment → PPS Vault →
  Signature → Fraud Scoring → CBS Balance → Acct Status → Decision

Usage in a test:
    async def test_stp_confirm(register_instrument):
        result = await wf.run_with_mocks(inp, mocks)
        register_instrument(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            workflow_type="INWARD",        # or "OUTWARD"
            decision=result.decision,
            rationale=result.rationale,
            steps=[
                {"name": "Alteration",    "outcome": "CLEAR"},
                {"name": "CTS-2010",      "outcome": "PASS",  "violations": []},
                {"name": "Stop Payment",  "outcome": "CLEAN"},
                {"name": "PPS Vault",     "outcome": "HIT"},
                {"name": "Signature",     "outcome": "MATCH", "score": 0.95},
                {"name": "Fraud",         "outcome": "LOW",   "score": 0.12,
                 "shap": {"amount": 0.08, "account_age": -0.03}},
                {"name": "CBS Balance",   "outcome": "OK"},
                {"name": "Acct Status",   "outcome": "ACTIVE"},
                {"name": "Decision",      "outcome": "STP_CONFIRM"},
            ],
            amount_range="₹[1L-5L]",      # from masking util — never raw amount
            duration_ms=342,
        )
        assert result.decision == "STP_CONFIRM"

Digest location: test-reports/digest-YYYYMMDD-HHMMSS.html
Latest copy:     test-reports/latest.html
"""
from __future__ import annotations

import html as _html
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest


# ─────────────────────────────────────────────────────────────────────────────
#  Session-scoped state
# ─────────────────────────────────────────────────────────────────────────────

class _DigestState:
    def __init__(self) -> None:
        self.started_at: float = time.time()
        self.started_dt: datetime = datetime.now(tz=timezone.utc)
        self.instruments: list[dict] = []   # registered by tests
        self.test_results: list[dict] = []  # pass/fail stats


_state = _DigestState()


# ─────────────────────────────────────────────────────────────────────────────
#  Pytest hooks
# ─────────────────────────────────────────────────────────────────────────────

def pytest_sessionstart(session):
    _state.started_at = time.time()
    _state.started_dt = datetime.now(tz=timezone.utc)


def pytest_runtest_logreport(report):
    if report.when not in ("call",):
        if not (report.when in ("setup", "teardown") and report.failed):
            return
    longrepr: Optional[str] = None
    if report.failed:
        try:
            longrepr = str(report.longrepr)
        except Exception:
            longrepr = "<repr unavailable>"
    _state.test_results.append({
        "nodeid": report.nodeid,
        "outcome": report.outcome,
        "duration": getattr(report, "duration", 0.0) or 0.0,
        "longrepr": longrepr,
    })


def pytest_sessionfinish(session, exitstatus):
    _write_digest(exitstatus)


# ─────────────────────────────────────────────────────────────────────────────
#  Fixture: register_instrument
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def register_instrument():
    """Session fixture — call once per instrument inside any test to add it to the digest.

    Args:
        instrument_id: unique instrument identifier
        bank_id: bank code (e.g. 'federal-bank')
        workflow_type: 'INWARD' | 'OUTWARD'
        decision: final decision string from ChequeWorkflowResult or OutwardScanResult
        rationale: rationale string
        steps: list of pipeline step dicts — each has at minimum 'name' and 'outcome';
               optional fields: 'score' (float), 'violations' (list[str]),
               'shap' (dict[str, float]), 'detail' (str)
        amount_range: masked amount string from masking util (e.g. '₹[1L-5L]')
        duration_ms: total processing time in milliseconds (optional)
        test_name: calling test name (auto-populated when not provided)
    """
    def _register(
        *,
        instrument_id: str,
        bank_id: str,
        workflow_type: str = "INWARD",
        decision: str,
        rationale: str = "",
        steps: list[dict] | None = None,
        amount: float = 0.0,
        amount_range: str = "—",
        duration_ms: int = 0,
        test_name: str = "",
        image_data: str = "",
        ocr_model: str = "GOT-OCR2.0",
        ocr_payee: str = "",
        signature_data: str = "",
    ) -> None:
        _state.instruments.append({
            "instrument_id": instrument_id,
            "bank_id": bank_id,
            "workflow_type": workflow_type,
            "decision": decision,
            "rationale": rationale,
            "steps": steps or [],
            "amount": amount,
            "amount_range": amount_range,
            "duration_ms": duration_ms,
            "test_name": test_name,
            "image_data": image_data,
            "ocr_model": ocr_model,
            "ocr_payee": ocr_payee,
            "signature_data": signature_data,
            "registered_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    return _register


# ─────────────────────────────────────────────────────────────────────────────
#  Digest renderer
# ─────────────────────────────────────────────────────────────────────────────

def _git_meta() -> tuple[str, str]:
    def _run(args):
        try:
            return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True).strip()
        except Exception:
            return "—"
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]), \
           _run(["git", "rev-parse", "--short", "HEAD"])


def _fmt_dur(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


_STEP_ICON = {
    # Registry step_id → icon (canonical, used by new StepResult-based steps)
    "iet_watchdog":       "⏱",
    "duplicate_check":    "♻",
    "ocr_extract":        "⬡",
    "kill_switch_1":      "🔴",
    "alteration_detect":  "🔍",
    "security_features":  "📋",
    "stop_payment":       "🚫",
    "ifsc_validate":      "🏷",
    "pps_lookup":         "🔑",
    "sig_detect":         "✍",
    "sig_verify":         "✍",
    "fraud_score":        "🎯",
    "cheque_series":      "🔢",
    "cbs_balance":        "🏦",
    "account_status":     "👤",
    "kill_switch_2":      "🔴",
    "synthesise_decision":"⚖",
    "stp_mode_routing":   "🔀",
    "persist_decision":   "💾",
    "ngch_file":          "📤",
    "audit_write":        "📝",
    "human_review_spawn": "👁",
    "smb_ledger":         "📒",
    "feedback_emit":      "📡",
    # Outward step_ids
    "date_validate":      "📅",
    "post_dated_hold":    "📆",
    "cheque_dedup":       "♻",
    "rear_ocr":           "🖼",
    "payee_validate":     "💳",
    "ngch_cross_check":   "🔗",
    "cts2010_compliance": "📋",
    "vision_crosscheck":  "👁",
    "mismatch_spawn":     "⚠",
    "branch_monitor":     "📊",
    # Legacy name-based keys (backward compat for hand-crafted test steps)
    "OCR":          "⬡",
    "Alteration":   "🔍",
    "CTS-2010":     "📋",
    "Stop Payment": "🚫",
    "PPS Vault":    "🔑",
    "Signature":    "✍",
    "Fraud":        "🎯",
    "CBS Balance":  "🏦",
    "Acct Status":  "👤",
    "Decision":     "⚖",
    "Date Check":   "📅",
    "Dedup":        "♻",
    "UV Security":  "🔬",
    "IFSC":         "🏷",
    "Payee":        "💳",
}

_DECISION_LABEL = {
    "STP_CONFIRM":   ("STP CONFIRM",   "dec-confirm"),
    "STP_RETURN":    ("STP RETURN",    "dec-return"),
    "HUMAN_REVIEW":  ("HUMAN REVIEW",  "dec-review"),
    "ACCEPTED":      ("ACCEPTED",      "dec-confirm"),
    "CTS_REJECTED":  ("REJECTED",      "dec-return"),
    "POST_DATED_HELD": ("HELD — POST DATED", "dec-held"),
    "DUPLICATE_CHEQUE": ("DUPLICATE",  "dec-return"),
    "MISMATCH_HELD": ("MISMATCH HELD", "dec-held"),
}

_OUTCOME_CLASS = {
    "CLEAR": "step-ok",  "PASS": "step-ok",  "CLEAN": "step-ok",
    "HIT":   "step-ok",  "MATCH": "step-ok", "OK": "step-ok",
    "ACTIVE": "step-ok", "LOW": "step-ok",   "STP_CONFIRM": "step-ok",
    "ACCEPTED": "step-ok",
    "MISS": "step-warn", "FUZZY": "step-warn", "MEDIUM": "step-warn",
    "STALE": "step-fail", "MISMATCH": "step-fail", "HIGH": "step-fail",
    "FAIL": "step-fail",  "FROZEN": "step-fail",  "STOPPED": "step-fail",
    "STP_RETURN": "step-fail", "CTS_REJECTED": "step-fail",
    "HUMAN_REVIEW": "step-warn",
    "POST_DATED_HELD": "step-held", "DUPLICATE": "step-fail",
    "MISMATCH_HELD": "step-held",
    "DEGRADED": "step-warn", "SKIP": "step-muted",
}


def _step_row(step: dict) -> str:
    # Support both registry-based step_id and legacy name-keyed steps
    step_id = step.get("step_id", "")
    name = step.get("name", "")
    if step_id and not name:
        # Look up display name from registry
        try:
            from modules.cts.pipeline.registry import get_step
            pipeline_hint = step.get("pipeline", "INWARD")
            reg_step = get_step(step_id, pipeline_hint) or get_step(step_id, "OUTWARD")
            name = reg_step.name if reg_step else step_id
        except Exception:
            name = step_id
    outcome = step.get("outcome", "")
    score = step.get("score")
    violations = step.get("violations") or []
    shap = step.get("shap") or {}
    detail = step.get("detail") or step.get("reason", "")
    icon = _STEP_ICON.get(step_id) or _STEP_ICON.get(name, "·")
    css = _OUTCOME_CLASS.get(outcome, "step-muted")

    extras = []
    if score is not None:
        extras.append(f'<span class="step-score">score {score:.3f}</span>')
    if violations:
        vstr = ", ".join(_html.escape(v) for v in violations[:3])
        extras.append(f'<span class="step-violation">{vstr}</span>')
    if shap:
        shap_parts = " ".join(
            f'<span class="shap-{"pos" if v >= 0 else "neg"}">'
            f'{_html.escape(k)} {"+" if v >= 0 else ""}{v:+.2f}</span>'
            for k, v in list(shap.items())[:4]
        )
        extras.append(f'<span class="step-shap">SHAP: {shap_parts}</span>')
    if detail:
        extras.append(f'<span class="step-detail">{_html.escape(str(detail))}</span>')

    extras_html = " ".join(extras)
    return f"""
    <tr class="step-row {css}">
      <td class="step-icon">{icon}</td>
      <td class="step-name">{_html.escape(name)}</td>
      <td class="step-outcome">{_html.escape(outcome)}</td>
      <td class="step-extras">{extras_html}</td>
    </tr>"""


def _instrument_card(inst: dict, idx: int) -> str:
    iid       = _html.escape(inst.get("instrument_id", "—"))
    bid       = _html.escape(inst.get("bank_id", "—"))
    wtype     = _html.escape(inst.get("workflow_type", "INWARD"))
    raw_dec   = inst.get("decision", "")
    rationale = _html.escape(inst.get("rationale", ""))
    dur       = inst.get("duration_ms", 0)
    tname     = _html.escape(inst.get("test_name", ""))
    ocr_model = _html.escape(inst.get("ocr_model", "GOT-OCR2.0"))
    steps     = inst.get("steps", [])

    label, dec_class = _DECISION_LABEL.get(raw_dec, (_html.escape(raw_dec), "dec-unknown"))
    wf_badge_cls = "badge-inward" if wtype == "INWARD" else "badge-outward"
    dur_str = f"{dur:,} ms" if dur else "—"

    # Sort steps by registry seq when step_id is present; fall back to list order
    try:
        from modules.cts.pipeline.registry import steps_for
        _seq_map = {s.step_id: s.seq for s in steps_for(wtype)}
        steps = sorted(steps, key=lambda s: _seq_map.get(s.get("step_id", ""), 999))
    except Exception:
        pass

    step_rows = "".join(_step_row(s) for s in steps)

    # top SHAP from first step that has shap
    shap_html = ""
    for s in steps:
        if s.get("shap"):
            pairs = " &nbsp; ".join(
                f'<span class="shap-k">{_html.escape(k)}</span>'
                f'<span class="shap-v shap-{"pos" if v >= 0 else "neg"}">{v:+.2f}</span>'
                for k, v in list(s["shap"].items())[:4]
            )
            shap_html = f'<div class="shap-row">{pairs}</div>'
            break

    rationale_html = f'<div class="rationale">{rationale}</div>' if rationale else ""
    tname_html = f'<div class="inst-testname">{tname}</div>' if tname else ""

    image_data     = inst.get("image_data", "")
    signature_data = inst.get("signature_data", "")
    ocr_payee      = _html.escape(inst.get("ocr_payee", "") or "")
    raw_amount     = inst.get("amount", 0.0)

    _chq_html = (
        f'<div class="card-chq">'
        f'<div class="media-lbl">Cheque &nbsp;<span class="media-hint">(mouse over → full size)</span></div>'
        f'<img class="thumb" src="{image_data}" loading="lazy" alt="{iid}" '
        f'onmouseover="window._showCheque(this.src)" title="Mouse over to enlarge">'
        f'</div>'
    ) if image_data else ""

    _sig_html = (
        f'<div class="card-sig">'
        f'<div class="media-lbl">Signature crop &nbsp;<span class="media-hint">(cropped from cheque · mouse over)</span></div>'
        f'<img class="sig-thumb" src="{signature_data}" loading="lazy" alt="sig-{iid}" '
        f'onmouseover="window._showCheque(this.src)" title="Mouse over to enlarge">'
        f'</div>'
    ) if signature_data else ""

    media_html = (
        f'<div class="card-media">{_chq_html}{_sig_html}</div>'
    ) if (image_data or signature_data) else ""

    ocr_payee_row = (
        f'<tr><td class="fl">Payee (OCR)</td>'
        f'<td class="mono small ocr-payee">{ocr_payee}</td></tr>'
    ) if ocr_payee else ""

    def _fmt_inr(n: float) -> str:
        s = str(int(n))
        if len(s) <= 3:
            return f"₹{s}/-"
        last3, rest = s[-3:], s[:-3]
        parts = [last3]
        while rest:
            parts.append(rest[-2:])
            rest = rest[:-2]
        return "₹" + ",".join(reversed(parts)) + "/-"

    amt_display = _fmt_inr(raw_amount) if raw_amount else _html.escape(inst.get("amount_range", "—"))

    return f"""
<section class="card" id="inst-{idx}">
  <div class="card-hdr">
    <div class="card-id">
      <span class="idx">#{idx:02d}</span>
      <div>
        <div class="chq-label">{iid} &nbsp;&middot;&nbsp; <span class="badge {wf_badge_cls}">{wtype}</span></div>
        <div class="chq-sub">{bid} &nbsp;&middot;&nbsp; {amt_display}</div>
      </div>
    </div>
    <span class="decision-badge {dec_class}">{label}</span>
  </div>
  {media_html}
  <div class="digest-grid">
    <div class="dc">
      <div class="eyebrow">Instrument</div>
      <table class="ft">
        <tr><td class="fl">ID</td><td class="mono small">{iid}</td></tr>
        <tr><td class="fl">Bank</td><td>{bid}</td></tr>
        <tr><td class="fl">Workflow</td><td>{wtype}</td></tr>
        <tr><td class="fl">Amount</td><td class="amount">{amt_display}</td></tr>
        <tr><td class="fl">OCR Model</td><td class="mono small ocr-model">{ocr_model}</td></tr>
        {ocr_payee_row}
        <tr><td class="fl">Duration</td><td class="mono">{dur_str}</td></tr>
        <tr><td class="fl">Test</td><td class="small muted">{tname}</td></tr>
      </table>
    </div>
    <div class="dc">
      <div class="eyebrow">Pipeline Steps</div>
      {"<p class='no-steps'>No steps registered</p>" if not step_rows else f'<table class="step-table"><tbody>{step_rows}</tbody></table>'}
    </div>
    <div class="dc">
      <div class="eyebrow">Decision</div>
      <div class="dec-badge-lg {dec_class}">{label}</div>
      {rationale_html}
      {shap_html}
      {tname_html}
    </div>
  </div>
</section>"""


def _write_digest(exitstatus: int) -> None:
    elapsed = time.time() - _state.started_at
    results = _state.test_results
    instruments = _state.instruments

    passed  = sum(1 for r in results if r["outcome"] == "passed")
    failed  = sum(1 for r in results if r["outcome"] == "failed")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    errors  = sum(1 for r in results if r["outcome"] == "error")
    n_total = len(results)

    overall_ok = exitstatus == 0 and failed == 0 and errors == 0
    branch, sha = _git_meta()
    ts     = _state.started_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    ts_file = _state.started_dt.strftime("%Y%m%d-%H%M%S")
    py_ver = f"Python {sys.version.split()[0]}"

    # Instrument cards HTML
    n_instruments = len(instruments)
    n_confirmed  = sum(1 for i in instruments if i.get("decision") in ("STP_CONFIRM", "ACCEPTED"))
    n_returned   = sum(1 for i in instruments if i.get("decision") in ("STP_RETURN", "CTS_REJECTED"))
    n_review     = sum(1 for i in instruments if i.get("decision") == "HUMAN_REVIEW")
    n_held       = sum(1 for i in instruments if i.get("decision") in ("POST_DATED_HELD", "MISMATCH_HELD"))

    inst_cards_html = "".join(
        _instrument_card(inst, i) for i, inst in enumerate(instruments)
    ) if instruments else '<p class="no-instruments">No instruments registered in this run. Call the <code>register_instrument</code> fixture from your CTS tests to populate this section.</p>'

    # Test summary module breakdown
    module_stats: dict[str, dict] = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0, "error": 0})
    for r in results:
        mod = r["nodeid"].split("::")[0].removeprefix("tests/").removeprefix("tests\\")
        module_stats[mod][r["outcome"]] += 1

    mod_rows = ""
    for mod, s in sorted(module_stats.items(), key=lambda x: -x[1]["failed"]):
        rc = "row-fail" if (s["failed"] or s["error"]) else ("row-skip" if not s["passed"] else "")
        mod_rows += f"""<tr class="{rc}">
          <td class="mod-path">{_html.escape(mod)}</td>
          <td class="num ok">{s['passed'] or '—'}</td>
          <td class="num fail">{(s['failed']+s['error']) or '—'}</td>
          <td class="num warn">{s['skipped'] or '—'}</td>
        </tr>"""

    # Failures
    failures_html = ""
    fail_results = [r for r in results if r["outcome"] in ("failed", "error")]
    for r in fail_results[:100]:
        parts = r["nodeid"].split("::", 1)
        fp = _html.escape(parts[0]) if parts else ""
        tp = _html.escape(parts[1]) if len(parts) > 1 else ""
        lr = _html.escape((r["longrepr"] or "")[:2000])
        failures_html += f"""
      <details class="failure-item">
        <summary><span class="fi-file">{fp}</span><span class="fi-sep">::</span><span class="fi-test">{tp}</span></summary>
        <pre class="fi-trace">{lr}</pre>
      </details>"""

    html_out = _HTML_TEMPLATE.format(
        ts=ts, branch=_html.escape(branch), sha=_html.escape(sha),
        py_ver=_html.escape(py_ver),
        status_class="status-ok" if overall_ok else "status-fail",
        status_label="ALL PASSED" if overall_ok else "FAILURES DETECTED",
        passed=f"{passed:,}", failed=f"{failed:,}",
        skipped=f"{skipped:,}", errors=f"{errors:,}", n_total=f"{n_total:,}",
        elapsed=_fmt_dur(elapsed),
        n_instruments=n_instruments,
        n_confirmed=n_confirmed, n_returned=n_returned,
        n_review=n_review, n_held=n_held,
        inst_cards=inst_cards_html,
        mod_rows=mod_rows,
        failures_section="" if not fail_results else f"""
<div class="section">
  <div class="section-hdr">Test Failures ({len(fail_results)})</div>
  {failures_html}
</div>""",
    )

    report_dir = Path("test-reports")
    report_dir.mkdir(exist_ok=True)
    digest_path = report_dir / f"digest-{ts_file}.html"
    digest_path.write_text(html_out, encoding="utf-8")
    (report_dir / "latest.html").write_text(html_out, encoding="utf-8")

    print(f"\n  Digest -> {digest_path.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
#  HTML template
# ─────────────────────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASTRA CTS — Test Digest · {ts}</title>
<style>
:root{{
  --bg:#0A0E16;--surf:#111827;--raised:#1A2234;--bdr:#1F2D44;
  --tx:#C8D4E4;--mut:#5B7294;--faint:#1C2840;
  --ok:#22C55E;--warn:#F59E0B;--err:#EF4444;--blue:#60A5FA;--acc:#3B82F6;--mock:#8B5CF6;
  --mono:'SF Mono','Consolas','Courier New',monospace;
  --sans:system-ui,-apple-system,'Segoe UI',sans-serif;
}}
@media(prefers-color-scheme:light){{:root{{
  --bg:#EEF2F7;--surf:#FFFFFF;--raised:#F1F5F9;--bdr:#CBD5E1;
  --tx:#0F172A;--mut:#64748B;--faint:#E2E8F0;
  --ok:#16A34A;--warn:#D97706;--err:#DC2626;--blue:#2563EB;--acc:#2563EB;--mock:#7C3AED;
}}}}
:root[data-theme=dark]{{
  --bg:#0A0E16;--surf:#111827;--raised:#1A2234;--bdr:#1F2D44;
  --tx:#C8D4E4;--mut:#5B7294;--faint:#1C2840;
  --ok:#22C55E;--warn:#F59E0B;--err:#EF4444;--blue:#60A5FA;--acc:#3B82F6;--mock:#8B5CF6;
}}
:root[data-theme=light]{{
  --bg:#EEF2F7;--surf:#FFFFFF;--raised:#F1F5F9;--bdr:#CBD5E1;
  --tx:#0F172A;--mut:#64748B;--faint:#E2E8F0;
  --ok:#16A34A;--warn:#D97706;--err:#DC2626;--blue:#2563EB;--acc:#2563EB;--mock:#7C3AED;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--sans);font-size:13px;line-height:1.5;background:var(--bg);color:var(--tx);padding-bottom:4rem}}

/* ── header ── */
.hdr{{background:var(--surf);border-bottom:1px solid var(--bdr);padding:.9rem 2rem;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}}
.brand{{font-size:1rem;font-weight:700;letter-spacing:.04em;color:var(--tx)}}
.brand span{{color:var(--acc)}}
.hdr-right{{display:flex;align-items:center;gap:1rem}}
.hdr-meta{{font-size:10.5px;color:var(--mut);text-align:right;line-height:1.8}}
.theme-btn{{cursor:pointer;font-size:11px;padding:.25rem .6rem;border-radius:4px;border:1px solid var(--bdr);background:var(--raised);color:var(--mut)}}

/* ── run summary banner ── */
.run-banner{{max-width:1180px;margin:1.5rem auto .5rem;padding:0 1.5rem}}
.run-inner{{background:color-mix(in srgb,var(--acc) 8%,transparent);border:1px solid color-mix(in srgb,var(--acc) 22%,transparent);border-radius:6px;padding:.85rem 1.25rem}}
.run-top{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem}}
.run-meta{{font-size:11.5px;color:var(--tx)}}
.run-ts{{font-family:var(--mono);font-size:11px;color:var(--mut);margin-right:.7rem}}
.run-pills{{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.5rem}}
.rpill{{font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:.18rem .55rem;border-radius:3px}}

/* ── test stat tiles ── */
.test-stats{{max-width:1180px;margin:0 auto;padding:0 1.5rem}}
.stat-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.6rem;margin-bottom:1rem}}
.stat-tile{{background:var(--surf);border:1px solid var(--bdr);border-radius:6px;padding:.75rem 1rem}}
.stat-n{{font-family:var(--mono);font-size:1.6rem;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}}
.stat-l{{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);margin-top:.15rem}}
.tile-ok .stat-n{{color:var(--ok)}}
.tile-fail .stat-n{{color:var(--err)}}
.tile-warn .stat-n{{color:var(--warn)}}
.tile-mut .stat-n{{color:var(--mut)}}
.tile-held .stat-n{{color:var(--mock)}}

/* ── cards wrap ── */
.wrap{{max-width:1180px;margin:0 auto;padding:0 1.5rem;display:flex;flex-direction:column;gap:2rem}}

/* ── instrument card ── */
.card{{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;overflow:hidden}}
.card-hdr{{display:flex;align-items:center;justify-content:space-between;padding:.65rem 1.2rem;background:var(--raised);border-bottom:1px solid var(--bdr)}}
.card-id{{display:flex;align-items:center;gap:.7rem}}
.idx{{font-family:var(--mono);font-size:1.3rem;font-weight:700;color:var(--faint);width:2.8rem;text-align:right;user-select:none}}
.chq-label{{font-size:.9rem;font-weight:600;color:var(--tx)}}
.chq-sub{{font-size:10px;color:var(--mut);font-family:var(--mono);margin-top:1px}}

/* ── digest 3-column grid ── */
.digest-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:0}}
.dc{{padding:.85rem 1.1rem;border-right:1px solid var(--bdr)}}
.dc:last-child{{border-right:none}}
.eyebrow{{font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin-bottom:.55rem;padding-bottom:.3rem;border-bottom:1px solid var(--faint)}}
.ft{{width:100%;border-collapse:collapse}}
.ft tr{{border-bottom:1px solid var(--faint)}}
.ft tr:last-child{{border-bottom:none}}
.ft td{{padding:.25rem 0;vertical-align:top}}
.fl{{color:var(--mut);font-size:10.5px;padding-right:.6rem;white-space:nowrap;width:40%}}
.mono{{font-family:var(--mono);font-size:11px}}
.small{{font-size:10.5px}}
.muted{{color:var(--mut)}}
.amount{{font-family:var(--mono);font-size:13px;font-weight:600}}

/* ── pipeline step table ── */
.step-table{{width:100%;border-collapse:collapse;font-size:11.5px}}
.step-row td{{padding:.28rem 0;border-bottom:1px solid var(--faint);vertical-align:middle}}
.step-row:last-child td{{border-bottom:none}}
.step-icon{{width:18px;text-align:center;font-size:11px;font-weight:700}}
.step-name{{padding-right:.5rem;white-space:nowrap;color:var(--tx)}}
.step-outcome{{font-family:var(--mono);font-size:10px;letter-spacing:.04em}}
.step-extras{{color:var(--mut);font-size:.68rem;display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}}
.step-score{{font-family:var(--mono);font-size:.68rem}}
.step-violation{{color:var(--err);font-size:.68rem}}
.step-detail{{color:var(--mut)}}

/* step outcome colours */
.step-ok .step-icon,.step-ok .step-outcome{{color:var(--ok)}}
.step-fail .step-icon,.step-fail .step-outcome{{color:var(--err)}}
.step-warn .step-icon,.step-warn .step-outcome{{color:var(--warn)}}
.step-held .step-icon,.step-held .step-outcome{{color:var(--mock)}}
.step-muted .step-icon,.step-muted .step-outcome{{color:var(--mut)}}

/* ── SHAP ── */
.shap-row{{display:flex;flex-wrap:wrap;gap:.25rem .65rem;margin-top:.4rem;font-size:10px;font-family:var(--mono)}}
.shap-k{{color:var(--mut)}}
.shap-v{{font-weight:600}}
.shap-pos{{color:var(--err)}}
.shap-neg{{color:var(--ok)}}

/* ── decision panel ── */
.dec-badge-lg{{font-size:.85rem;font-weight:700;letter-spacing:.06em;padding:.4rem .8rem;border-radius:4px;display:inline-block;margin-bottom:.5rem;text-transform:uppercase}}
.rationale{{font-size:11.5px;color:var(--tx);line-height:1.55;margin-bottom:.4rem}}
.inst-testname{{font-size:10px;font-family:var(--mono);color:var(--mut);margin-top:.35rem}}

/* ── decision + workflow badges ── */
.decision-badge{{font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:.22rem .6rem;border-radius:3px}}
.badge{{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:.1rem .38rem;border-radius:2px}}
.badge-inward{{background:color-mix(in srgb,var(--blue) 12%,transparent);color:var(--blue)}}
.badge-outward{{background:color-mix(in srgb,var(--warn) 12%,transparent);color:var(--warn)}}

/* decision colours (card header + decision panel) */
.dec-confirm{{background:color-mix(in srgb,var(--ok) 14%,transparent);color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 28%,transparent)}}
.dec-return{{background:color-mix(in srgb,var(--err) 14%,transparent);color:var(--err);border:1px solid color-mix(in srgb,var(--err) 28%,transparent)}}
.dec-review{{background:color-mix(in srgb,var(--warn) 14%,transparent);color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 28%,transparent)}}
.dec-held{{background:color-mix(in srgb,var(--mock) 14%,transparent);color:var(--mock);border:1px solid color-mix(in srgb,var(--mock) 28%,transparent)}}
.dec-unknown{{background:var(--faint);color:var(--mut);border:1px solid var(--bdr)}}

/* run pills same colours */
.rpill.dec-confirm{{background:color-mix(in srgb,var(--ok) 14%,transparent);color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 28%,transparent)}}
.rpill.dec-return{{background:color-mix(in srgb,var(--err) 14%,transparent);color:var(--err);border:1px solid color-mix(in srgb,var(--err) 28%,transparent)}}
.rpill.dec-review{{background:color-mix(in srgb,var(--warn) 14%,transparent);color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 28%,transparent)}}
.rpill.dec-held{{background:color-mix(in srgb,var(--mock) 14%,transparent);color:var(--mock);border:1px solid color-mix(in srgb,var(--mock) 28%,transparent)}}
.rpill.dec-unknown{{background:var(--faint);color:var(--mut)}}

/* ── module breakdown ── */
.section{{max-width:1180px;margin:2rem auto 0;padding:0 1.5rem}}
.section-hdr{{font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin-bottom:.7rem;padding-bottom:.3rem;border-bottom:1px solid var(--bdr)}}
.mod-table{{width:100%;border-collapse:collapse;font-size:12px}}
.mod-table th{{text-align:left;padding:.35rem .6rem;font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);border-bottom:1px solid var(--bdr)}}
.mod-table td{{padding:.3rem .6rem;border-bottom:1px solid var(--faint);vertical-align:top}}
.mod-table tr:last-child td{{border-bottom:none}}
.mod-path{{font-family:var(--mono);font-size:.7rem;word-break:break-all}}
.row-fail .mod-path{{color:var(--err)}}
.num{{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}}
.num.ok{{color:var(--ok)}}
.num.fail{{color:var(--err)}}
.num.warn{{color:var(--warn)}}

/* ── failures ── */
.failure-item{{border:1px solid color-mix(in srgb,var(--err) 22%,transparent);border-radius:6px;margin-bottom:.5rem;overflow:hidden}}
.failure-item summary{{padding:.45rem .9rem;cursor:pointer;display:flex;align-items:baseline;gap:.25rem;font-family:var(--mono);font-size:.72rem;list-style:none;background:var(--surf)}}
.failure-item[open] summary{{background:color-mix(in srgb,var(--err) 10%,transparent);border-bottom:1px solid var(--bdr)}}
.failure-item summary::-webkit-details-marker{{display:none}}
.fi-file{{color:var(--mut)}}
.fi-sep{{color:var(--faint)}}
.fi-test{{color:var(--tx);font-weight:600}}
.fi-trace{{font-family:var(--mono);font-size:.68rem;padding:.75rem;background:var(--bg);overflow-x:auto;color:var(--mut);white-space:pre;max-height:280px;overflow-y:auto}}

.no-steps{{color:var(--mut);font-size:.75rem;font-style:italic;padding:.3rem 0}}
.ocr-model{{color:var(--mock);font-size:10.5px}}
.no-instruments{{color:var(--mut);font-size:.8rem;padding:.75rem 0;font-style:italic}}
.card-media{{display:flex;align-items:flex-start;gap:.75rem;background:var(--faint);border-bottom:1px solid var(--bdr);padding:.4rem 1.1rem}}
.card-chq{{flex:1 1 auto;min-width:0}}
.card-sig{{flex:0 0 auto;display:flex;flex-direction:column;align-items:flex-start}}
.media-lbl{{font-size:9px;font-weight:600;color:var(--mut);text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}}
.media-hint{{font-weight:400;text-transform:none;letter-spacing:0;font-style:italic}}
.card-chq img.thumb{{max-width:520px;max-height:155px;width:100%;height:auto;object-fit:contain;border-radius:3px;display:block;box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:zoom-in;transition:opacity .15s}}
.card-chq img.thumb:hover{{opacity:.85}}
.card-sig img.sig-thumb{{max-width:220px;max-height:120px;height:auto;object-fit:contain;border-radius:3px;display:block;box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:zoom-in;transition:opacity .15s}}
.card-sig img.sig-thumb:hover{{opacity:.85}}
.ocr-payee{{color:var(--acc);font-weight:500}}
#chq-zoom-ov{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;align-items:center;justify-content:center;cursor:zoom-out}}
#chq-zoom-ov img{{max-width:92vw;max-height:88vh;border-radius:5px;box-shadow:0 10px 60px rgba(0,0,0,.7);object-fit:contain}}

@media(max-width:820px){{
  .digest-grid{{grid-template-columns:1fr}}
  .dc{{border-right:none;border-bottom:1px solid var(--bdr)}}
  .dc:last-child{{border-bottom:none}}
  .run-top{{flex-direction:column;align-items:flex-start}}
}}
</style>
<script>
function _toggleTheme(){{
  var r=document.documentElement;
  var cur=r.dataset.theme||(window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
  r.dataset.theme=cur==='dark'?'light':'dark';
  document.getElementById('thbtn').textContent=r.dataset.theme==='dark'?'☀ Light':'☾ Dark';
}}
(function(){{
  var ov=null;
  function _makeOv(){{
    if(ov)return;
    ov=document.createElement('div');ov.id='chq-zoom-ov';
    var img=document.createElement('img');
    ov.appendChild(img);
    ov.addEventListener('click',function(){{ov.style.display='none';}});
    document.addEventListener('keydown',function(e){{if(e.key==='Escape')ov.style.display='none';}});
    document.body.appendChild(ov);
  }}
  window._showCheque=function(src){{_makeOv();ov.querySelector('img').src=src;ov.style.display='flex';}};
}})();
</script>
</head>
<body>

<div class="hdr">
  <div class="brand">ASTRA <span>CTS</span> — Test Digest</div>
  <div class="hdr-right">
    <div class="hdr-meta">{ts} &nbsp;·&nbsp; {branch}@{sha} &nbsp;·&nbsp; {py_ver} &nbsp;·&nbsp; {elapsed}</div>
    <button class="theme-btn" id="thbtn" onclick="_toggleTheme()">☀ Light</button>
  </div>
</div>

<div class="run-banner">
  <div class="run-inner">
    <div class="run-top">
      <div class="run-meta">
        <span class="run-ts">{ts}</span>
        <strong>{n_instruments}</strong> instruments &nbsp;·&nbsp;
        {passed} passed &nbsp;·&nbsp; {failed} failed &nbsp;·&nbsp; {skipped} skipped
        <span class="status-badge {status_class}" style="margin-left:.6rem;padding:.15rem .55rem;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase">{status_label}</span>
      </div>
    </div>
    <div class="run-pills">
      <span class="rpill dec-confirm">{n_confirmed} Confirmed</span>
      <span class="rpill dec-return">{n_returned} Returned</span>
      <span class="rpill dec-review">{n_review} Human Review</span>
      <span class="rpill dec-held">{n_held} Held</span>
    </div>
  </div>
</div>

<div class="test-stats">
  <div class="stat-row">
    <div class="stat-tile tile-ok"><div class="stat-n">{passed}</div><div class="stat-l">Tests Passed</div></div>
    <div class="stat-tile tile-fail"><div class="stat-n">{failed}</div><div class="stat-l">Failed</div></div>
    <div class="stat-tile tile-warn"><div class="stat-n">{skipped}</div><div class="stat-l">Skipped</div></div>
    <div class="stat-tile tile-mut"><div class="stat-n">{errors}</div><div class="stat-l">Errors</div></div>
    <div class="stat-tile tile-ok"><div class="stat-n">{n_confirmed}</div><div class="stat-l">Confirmed</div></div>
    <div class="stat-tile tile-fail"><div class="stat-n">{n_returned}</div><div class="stat-l">Returned</div></div>
    <div class="stat-tile tile-warn"><div class="stat-n">{n_review}</div><div class="stat-l">Human Review</div></div>
    <div class="stat-tile tile-held"><div class="stat-n">{n_held}</div><div class="stat-l">Held</div></div>
  </div>
</div>

<div class="wrap">
{inst_cards}
</div>

<div class="section">
  <div class="section-hdr">Test Module Breakdown</div>
  <div style="overflow-x:auto">
    <table class="mod-table">
      <thead><tr>
        <th>Module</th>
        <th style="text-align:right">Pass</th>
        <th style="text-align:right">Fail</th>
        <th style="text-align:right">Skip</th>
      </tr></thead>
      <tbody>{mod_rows}</tbody>
    </table>
  </div>
</div>

{failures_section}

</body>
</html>"""
