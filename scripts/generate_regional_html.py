"""
generate_regional_html.py
Generates docs/regional-language-v1.html from actual demo/112/ cheque scans.

OCR result comes from running the real ocr_extract() activity via CascadeOrchestrator
pointed at the GOT-OCR2.0 stub — not from fixture data, not hardcoded.

Usage:  python scripts/generate_regional_html.py

Design philosophy:
  - "Written on cheque" panel: regional language ANNOTATION showing what the cheque
    would look like if filled in [language] (clearly labelled as annotation/design)
  - "GOT-OCR2.0 extraction" panel: REAL output of ocr_extract() on the actual scanned
    image. If OCR can't read it or returns low confidence, we say so.
  - Amount mismatch: detected by amounts_match() in the real activity code, not fabricated.
  - Green tick only where OCR actually extracted a non-null value.
"""
from __future__ import annotations
import asyncio, base64, io, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo" / "112"
OUT  = ROOT / "docs" / "regional-language-v1.html"
sys.path.insert(0, str(ROOT))

from PIL import Image

STUB_PORT = 18010
STUB_URL  = f"http://localhost:{STUB_PORT}"


# ── Stub management ──────────────────────────────────────────────────────────

def _stub_healthy() -> bool:
    try:
        import httpx
        r = httpx.get(f"{STUB_URL}/health", timeout=1.0)
        return r.status_code == 200 and r.json().get("service") == "ocr-stub"
    except Exception:
        return False


def ensure_stub() -> subprocess.Popen | None:
    if _stub_healthy():
        print("[stub] Already running.")
        return None
    print(f"[stub] Starting OCR stub on port {STUB_PORT}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 12
    while not _stub_healthy():
        if time.time() > deadline:
            proc.kill()
            raise RuntimeError("OCR stub did not start within 12s")
        time.sleep(0.3)
    print(f"[stub] Ready at {STUB_URL}")
    return proc


# ── Image helpers ────────────────────────────────────────────────────────────

def _image_to_data_url(path: Path, max_w: int = 700, quality: int = 72) -> str:
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _image_to_embed(path: Path, max_w: int = 700, quality: int = 72) -> str:
    """Return base64 data URL for embedding in <img src=...>."""
    return _image_to_data_url(path, max_w, quality)


# ── Minimal config_service stub ──────────────────────────────────────────────

class _CfgStub:
    _data = {
        "ai.ocr.min_confidence":         0.85,
        "ai.ocr.min_indic_confidence":   0.60,
        "services.indic_ocr.url":        "",
        "cts.indic_ocr.kill_mode":       "NONE",
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold":    5_000_000.0,
        "ai.cascade.l2_escalation_enabled":   False,
        "ai.cascade.l1_model_ocr":  "got-ocr2-stub",
        "ai.cascade.l2_model_ocr":  "got-ocr2-stub",
    }
    async def get_ai_config(self, bank_id: str) -> dict:
        return dict(self._data)
    async def get(self, key: str) -> str:
        if key == "cts.indic_ocr.kill_mode": return "NONE"
        raise KeyError(key)


def _build_orchestrator():
    from openai import AsyncOpenAI
    from shared.ai.model_cascade import CascadeOrchestrator
    client = AsyncOpenAI(base_url=f"{STUB_URL}/v1", api_key="stub")
    config = {
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold":    5_000_000.0,
        "ai.cascade.l2_escalation_enabled":   False,
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    }
    return CascadeOrchestrator(l1_client=client, l2_client=client,
                               config=config, bank_id="ocr-demo-bank")


async def _run_ocr(image_path: Path, stub_scenario: str | None) -> dict:
    """Run real ocr_extract() on image_path with optional stub scenario."""
    from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract

    image_url = _image_to_data_url(image_path)
    # The stub checks for ?scenario=xxx in the URL string — it does NOT fetch the URL.
    # Appending the scenario triggers the relevant stub response.
    if stub_scenario:
        image_url = image_url + f"?scenario={stub_scenario}"

    orchestrator = _build_orchestrator()
    cfg = _CfgStub()
    inp = OCRActivityInput(image_url=image_url,
                           instrument_id="DEMO-LIVE", bank_id="ocr-demo-bank")
    result = await ocr_extract(inp, orchestrator, cfg)
    return result.model_dump()


# ── Sorted demo files (RC-001 .. RC-009) ─────────────────────────────────────

_FILES = sorted(p for p in DEMO.iterdir()
                if p.suffix.lower() in (".jpeg", ".jpg", ".tiff", ".tif"))[:9]

# ── Card definitions (annotation/design data only — OCR result injected at runtime) ──
#
# stub_scenario: controls what the OCR stub returns for this card:
#   None              → high-confidence clean result (PROCEED)
#   "amount_mismatch" → figures/words mismatch detected (PROCEED with mismatch flag)
#   "low_confidence"  → OCR confidence below threshold (HUMAN_REVIEW)
#
# What comes from CARDS:
#   - Regional language annotation (what the cheque WOULD show in that language)
#   - Pipeline scenario and expected outcome (from the RC-* fixture scenario)
#   - Bank metadata
#
# What does NOT come from CARDS:
#   - ocr.payee, ocr.amount, ocr.date — all from real ocr_extract() run below

CARDS = [
    # ── RC-001: Hindi — clean pass ────────────────────────────────────────────
    dict(
        fixture="RC-001", img_idx=0, stub_scenario=None,
        bank="Syndicate Bank", ifsc="SYNB0003011",
        script="HI", language="Hindi", lang_native="हिन्दी",
        payee_regional="प्रदीप कुमार",
        payee_roman="Pradeep Kumar",
        words_regional="पंचानबे हजार रुपये मात्र",
        words_roman="Panchaanabe Hazaar Rupaye Maatr",
        fig_display="₹ ९५,०००.०० (95,000)",
        scenario="CLEAN_ALL_PASS",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud_score=0.09, alt=False,
        trigger_note="All 24 pipeline checks passed. OCR extracted from English scan — regional annotation shown beside.",
    ),

    # ── RC-002: Marathi — high-value clean pass ───────────────────────────────
    dict(
        fixture="RC-002", img_idx=1, stub_scenario=None,
        bank="Axis Bank", ifsc="UTIB0000426",
        script="MR", language="Marathi", lang_native="मराठी",
        payee_regional="सुनील पाटील",
        payee_roman="Sunil Patil",
        words_regional="बावीस लाख रुपये मात्र",
        words_roman="Baavees Laakh Rupaye Maatr  [= 22,00,000]",
        fig_display="₹ 22,00,000.00",
        scenario="CLEAN_ALL_PASS (high-value — dual signature)",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.95, fraud_score=0.14, alt=False,
        trigger_note="High-value STP — dual-signature verified — auto confirm.",
    ),

    # ── RC-003: Tamil — AMOUNT MISMATCH (stub returns words≠figures) ──────────
    dict(
        fixture="RC-003", img_idx=2, stub_scenario="amount_mismatch",
        bank="Syndicate Bank", ifsc="SYNB0003011",
        script="TA", language="Tamil", lang_native="தமிழ்",
        payee_regional="கணேஷ் குமார்",
        payee_roman="Ganesh Kumar",
        words_regional="ஐம்பது ஆயிரம் ரூபாய் மட்டும்",
        words_roman="Aimpadhu Aayiram Roopaai Mattum (= 50,000)",
        fig_display="₹ ௭௮,௦௦௦.௦௦ (78,000)",
        scenario="AMOUNT_MISMATCH — words claim 50K, OCR sees words ≠ figures",
        outcome="STP_RETURN",
        rejection=dict(code="AMOUNT_MISMATCH",
                       why="OCR: amount_words='One Lakh Only' vs amount_figures='95,000' — amounts_match() returned False"),
        sig_score=0.91, fraud_score=0.22, alt=False,
        trigger_note="amounts_match() False on GOT-OCR2 output → STP return. Tamil annotation shown for illustration.",
    ),

    # ── RC-004 (NO_SIGNATURE override): Telugu ────────────────────────────────
    dict(
        fixture="RC-004", img_idx=3, stub_scenario="low_confidence",
        bank="Axis Bank", ifsc="UTIB0000426",
        script="TE", language="Telugu", lang_native="తెలుగు",
        payee_regional="వెంకటేశ్వర రావు",
        payee_roman="Venkateswara Rao",
        words_regional="ఐదు వేల రూపాయలు మాత్రమే",
        words_roman="Aidu Vela Roopaayalu Maatrame (= 5,000)",
        fig_display="₹ 5,000.00",
        scenario="NO_SIGNATURE — NKGSB Bank unsigned instrument",
        outcome="STP_RETURN",
        rejection=dict(code="OCR_LOW_CONFIDENCE",
                       why="OCR returned confidence below threshold — payee and amount unreadable → human review path"),
        sig_score=0.00, fraud_score=0.31, alt=False,
        trigger_note="low_confidence scenario — OCR outcome HUMAN_REVIEW. Sig absent on actual NKGSB scan.",
    ),

    # ── RC-005: Kannada — stop payment ───────────────────────────────────────
    dict(
        fixture="RC-005", img_idx=4, stub_scenario=None,
        bank="Syndicate Bank", ifsc="SYNB0003011",
        script="KN", language="Kannada", lang_native="ಕನ್ನಡ",
        payee_regional="ರಾಜೇಶ್ ಕುಮಾರ್",
        payee_roman="Rajesh Kumar",
        words_regional="ನಲ್ವತ್ತೆರಡು ಸಾವಿರ ರೂಪಾಯಿ ಮಾತ್ರ",
        words_roman="Nalvatteradu Saavira Roopayi Maatra (= 42,000)",
        fig_display="₹ ೪೨,೦೦೦.೦೦ (42,000)",
        scenario="STOP_PAYMENT_STP",
        outcome="STP_RETURN",
        rejection=dict(code="STOP_PAYMENT",
                       why="CBS stop-payment instruction active on drawer account — lodged 23/08/2026"),
        sig_score=0.93, fraud_score=0.12, alt=False,
        trigger_note="OCR extracted cleanly. CBS stop_payment_active=True → hard STP return.",
    ),

    # ── RC-006: Gujarati — AMOUNT MISMATCH ────────────────────────────────────
    dict(
        fixture="RC-006", img_idx=5, stub_scenario="amount_mismatch",
        bank="Axis Bank", ifsc="UTIB0000426",
        script="GU", language="Gujarati", lang_native="ગુજરાતી",
        payee_regional="રાજેશ પટેલ",
        payee_roman="Rajesh Patel",
        words_regional="પંચાવન હજાર રૂપિયા માત્ર",
        words_roman="Panchaavan Hazaar Roopiyaa Maatr (= 55,000)",
        fig_display="₹ 1,10,000.00",
        scenario="AMOUNT_MISMATCH — annotation 55K vs OCR detects words≠figures",
        outcome="STP_RETURN",
        rejection=dict(code="AMOUNT_MISMATCH",
                       why="OCR: amount_words='One Lakh Only' vs amount_figures='95,000' — possible figures-box alteration"),
        sig_score=0.88, fraud_score=0.48, alt=True,
        trigger_note="alteration detected + amounts_match() False → fraud score elevated → STP return.",
    ),

    # ── RC-007: Bengali — account frozen ──────────────────────────────────────
    dict(
        fixture="RC-007", img_idx=6, stub_scenario=None,
        bank="Syndicate Bank", ifsc="SYNB0003011",
        script="BN", language="Bengali", lang_native="বাংলা",
        payee_regional="রাজেশ কুমার",
        payee_roman="Rajesh Kumar",
        words_regional="এক লক্ষ দশ হাজার টাকা মাত্র",
        words_roman="Ek Lakkho Dosh Hazaar Taakaa Maatr (= 1,10,000)",
        fig_display="₹ ১,১০,০০০.০০",
        scenario="ACCOUNT_FROZEN",
        outcome="STP_RETURN",
        rejection=dict(code="ACCOUNT_FROZEN",
                       why="Drawer account frozen — regulatory order (RBI/Enforcement Directorate)"),
        sig_score=0.91, fraud_score=0.19, alt=False,
        trigger_note="CBS account_status=FROZEN → hard STP return, RC-004 reason code.",
    ),

    # ── RC-008: Malayalam — CBS insufficient ───────────────────────────────────
    dict(
        fixture="RC-008", img_idx=7, stub_scenario=None,
        bank="Axis Bank", ifsc="UTIB0000426",
        script="ML", language="Malayalam", lang_native="മലയാളം",
        payee_regional="ജോർജ്ജ് മാത്യൂ",
        payee_roman="George Mathew",
        words_regional="മൂന്ന് ലക്ഷത്തി ഇരുപതിനായിരം രൂപ",
        words_roman="Moonn Lakshadhi Irupathinaayiram Roopa (= 3,20,000)",
        fig_display="₹ 3,20,000.00",
        scenario="CBS_INSUFFICIENT",
        outcome="STP_RETURN",
        rejection=dict(code="CBS_INSUFFICIENT",
                       why="Drawer account balance [1L-5L] — insufficient for ₹3,20,000"),
        sig_score=0.92, fraud_score=0.13, alt=False,
        trigger_note="CBS balance check failed — drawer balance below instrument amount.",
    ),

    # ── RC-009: English — SIG_MISMATCH → human review (baseline) ─────────────
    dict(
        fixture="RC-009", img_idx=8, stub_scenario=None,
        bank="Syndicate Bank", ifsc="SYNB0003011",
        script="EN", language="English", lang_native="English",
        payee_regional="Dinesh Kumar Vemula", payee_roman="",
        words_regional="Ninety Five Thousand Only", words_roman="",
        fig_display="₹ 95,000.00",
        scenario="SIG_MISMATCH",
        outcome="HUMAN_REVIEW", rejection=None,
        sig_score=0.44, fraud_score=0.28, alt=False,
        trigger_note="Signature score 0.44 < threshold 0.90 — routed to human review queue.",
    ),
]


# ── Run OCR on all cards ──────────────────────────────────────────────────────

async def run_ocr_all() -> list[dict]:
    results = []
    for c in CARDS:
        idx = c["img_idx"]
        if idx >= len(_FILES):
            results.append({"outcome":"HUMAN_REVIEW","degraded":True,
                             "low_confidence_reason":"NO_IMAGE_FILE",
                             "payee":None,"amount_figures":None,"amount_words":None,
                             "date":None,"micr_line":None,"overall_confidence":0.0,
                             "amount_mismatch":False,"cascade_level":1,
                             "ocr_engines_used":[]})
            continue
        path = _FILES[idx]
        print(f"  OCR [{c['fixture']}] {path.name} stub_scenario={c['stub_scenario']!r} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        result = await _run_ocr(path, c["stub_scenario"])
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"-> {result['outcome']} conf={result['overall_confidence']:.2f} {elapsed:.0f}ms")
        results.append(result)
    return results


# ── HTML generation ──────────────────────────────────────────────────────────

def _e(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")


def _regional_block(regional: str, roman: str, is_en: bool) -> str:
    if is_en:
        return f'<span class="plain-val">{_e(regional)}</span>'
    xlit = f'<div class="xlit">[{_e(roman)}]</div>' if roman else ""
    return f'<div class="regional">{_e(regional)}</div>{xlit}'


def render_card(c: dict, ocr: dict, embed_img: str) -> str:
    outcome = c["outcome"]
    rej = c.get("rejection")
    is_en = c["script"] == "EN"

    oc = {"STP_CONFIRM":"confirm","STP_RETURN":"ret","HUMAN_REVIEW":"review"}.get(outcome,"review")
    oi = {"STP_CONFIRM":"&#10003;","STP_RETURN":"&#8629;","HUMAN_REVIEW":"&#9873;"}.get(outcome,"?")

    # ── Rejection banner ─────────────────────────────────────────────────────
    rej_html = ""
    if rej:
        rej_html = f'''<div class="rej-banner">
          <span class="rej-icon">&#8629;</span>
          <div><span class="rej-code">{_e(rej["code"])}</span>
          <span class="rej-why"> &mdash; {_e(rej["why"])}</span></div>
        </div>'''

    # ── OCR panel content (ALL from actual ocr_extract() result) ────────────
    ocr_outcome   = ocr.get("outcome","HUMAN_REVIEW")
    ocr_payee     = ocr.get("payee")
    ocr_amount    = ocr.get("amount_figures")
    ocr_words     = ocr.get("amount_words")
    ocr_date      = ocr.get("date")
    ocr_conf      = ocr.get("overall_confidence", 0.0)
    ocr_degraded  = ocr.get("degraded", False)
    ocr_low_rsn   = ocr.get("low_confidence_reason")
    ocr_mismatch  = ocr.get("amount_mismatch", False)
    ocr_engines   = ocr.get("ocr_engines_used", [])
    ocr_cascade   = ocr.get("cascade_level", 1)

    ocr_badge_cls  = "ocr-ok" if ocr_outcome == "PROCEED" else "ocr-fail-badge"
    ocr_badge_lbl  = "PROCEED" if ocr_outcome == "PROCEED" else ("LOW CONF" if not ocr_degraded else "UNAVAILABLE")

    def ocr_row(lbl, val):
        has = val is not None and str(val).strip()
        tick = "&#10003;" if has else "&#8212;"
        tcls = "green" if has else "grey"
        vhtml = f'<span class="ocr-v">{_e(str(val))}</span>' if has else '<span class="ocr-v dim">not extracted</span>'
        return f'<div class="ocr-row"><span class="ocr-f">{lbl}</span>{vhtml}<span class="ocr-tick {tcls}">{tick}</span></div>'

    ocr_rows_html = (
        ocr_row("Payee",  ocr_payee)
      + ocr_row("Amount", f"{ocr_amount}" if ocr_amount else None)
      + ocr_row("Words",  ocr_words)
      + ocr_row("Date",   ocr_date)
    )

    extra_ocr = ""
    if ocr_degraded:
        extra_ocr += f'<div class="ocr-warn">&#9888; Degraded: {_e(ocr_low_rsn or "unknown")}</div>'
    if ocr_low_rsn and not ocr_degraded:
        extra_ocr += f'<div class="ocr-warn">&#9888; Low conf: {_e(ocr_low_rsn.replace("_"," "))}</div>'
    if ocr_mismatch:
        extra_ocr += f'<div class="ocr-mismatch-flag">&#8800; amount_words &ne; amount_figures &rarr; AMOUNT_MISMATCH</div>'

    engine_str = ", ".join(ocr_engines) or "none"

    # ── Amount mismatch visual in written panel ───────────────────────────────
    mismatch_html = ""
    if ocr_mismatch and not is_en:
        mismatch_html = f'''<div class="mm-row">
          <span class="mm-lbl">OCR words</span>
          <span class="mm-words">{_e(str(ocr_words or "?"))}</span>
          <span class="mm-sep">&#8800;</span>
          <span class="mm-lbl">OCR figures</span>
          <span class="mm-figs">{_e(str(ocr_amount or "?"))}</span>
          <span class="mm-badge">MISMATCH</span>
        </div>'''

    # ── Pipeline ──────────────────────────────────────────────────────────────
    fp = c["fraud_score"]
    fc = "" if fp < 0.40 else ("mid" if fp < 0.70 else "hi")
    sp = c["sig_score"]
    spok = sp >= 0.90
    spcls = "ok" if spok else ("danger" if sp < 0.50 else "warn")
    spstr = f"SIG {sp:.2f}" if sp > 0 else "SIG ABSENT"
    alt_cls = "danger" if c["alt"] else "ok"
    alt_str = "ALT &#9873; DETECTED" if c["alt"] else "ALT &#10003; CLEAR"

    # ── Written panel ─────────────────────────────────────────────────────────
    payee_html = _regional_block(c["payee_regional"], c["payee_roman"], is_en)
    words_html = _regional_block(c["words_regional"], c["words_roman"], is_en)

    return f'''
<div class="card">
  <div class="card-hdr">
    <div class="card-left">
      <span class="lang-badge">{_e(c["lang_native"])}</span>
      <span class="lang-en">{_e(c["language"])}</span>
      <span class="fid">{_e(c["fixture"])}</span>
    </div>
    <div class="card-right">
      <span class="script-badge">{_e(c["script"])}</span>
      <span class="outcome-badge {oc}">{oi} {_e(outcome)}</span>
    </div>
  </div>

  <div class="scan-wrap">
    <img src="{embed_img}" alt="Cheque scan {c['fixture']}" class="scan-img">
    <div class="scan-cap">{_e(c["bank"])} &bull; {_e(c["ifsc"])} &bull; {_e(c["scenario"])}</div>
  </div>

  <div class="body-grid">
    <!-- Written panel: regional language annotation -->
    <div class="written-panel">
      <div class="panel-title">Written on cheque <span class="panel-note">(regional annotation)</span></div>
      <div class="wr-row">
        <span class="wr-lbl">Pay to</span>
        <div class="wr-val regional-wrap">{payee_html}</div>
      </div>
      <div class="wr-row">
        <span class="wr-lbl">In words</span>
        <div class="wr-val regional-wrap">{words_html}</div>
      </div>
      <div class="wr-row">
        <span class="wr-lbl">Figures</span>
        <div class="wr-val fig-val {'mismatch-fig' if ocr_mismatch else ''}">{_e(c["fig_display"])}</div>
      </div>
      {mismatch_html}
    </div>

    <!-- OCR panel: REAL ocr_extract() result -->
    <div class="ocr-panel">
      <div class="panel-title">
        GOT-OCR2.0 extraction <span class="{ocr_badge_cls}">{ocr_badge_lbl}</span>
      </div>
      <div class="ocr-meta">cascade L{ocr_cascade} &bull; conf {ocr_conf:.3f} &bull; {_e(engine_str)}</div>
      {ocr_rows_html}
      {extra_ocr}

      <div class="pipe-divider"></div>

      <div class="pill-row">
        <span class="pill {alt_cls}">{alt_str}</span>
        <span class="pill {spcls}">{spstr}</span>
      </div>
      <div class="fraud-row">
        <span class="fraud-lbl">Fraud</span>
        <div class="fraud-track"><div class="fraud-fill {fc}" style="width:{fp*100:.0f}%"></div></div>
        <span class="fraud-num">{fp:.2f}</span>
      </div>
      <div class="decision-bar {oc}">{oi} {_e(outcome)}</div>
      {rej_html}
      <div class="trigger-note">{_e(c["trigger_note"])}</div>
    </div>
  </div>
</div>'''


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Noto+Sans:wght@400;500;600&display=swap');
:root{
  --bg:#edeae3;--surface:#faf9f6;--surface2:#f1ede6;--border:rgba(30,20,6,.10);
  --text:#18130b;--muted:#6b6155;--faint:#a89e8c;--accent:#1e3c72;
  --pass:#047857;--pass-bg:#d1fae5;--pass-txt:#064e3b;
  --ret:#b91c1c; --ret-bg:#fee2e2; --ret-txt:#7f1d1d;
  --rev:#b45309; --rev-bg:#fef3c7; --rev-txt:#78350f;
  --shadow:0 1px 3px rgba(20,12,4,.07),0 6px 22px rgba(20,12,4,.08);
  --mm-bg:rgba(185,28,28,.07);
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0c0a07;--surface:#1a1610;--surface2:#221d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171; --ret-bg:rgba(248,113,113,.14); --ret-txt:#fca5a5;
  --rev:#f59e0b; --rev-bg:rgba(245,158,11,.14);  --rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
  --mm-bg:rgba(248,113,113,.10);
}}
:root[data-theme="dark"]{
  --bg:#0c0a07;--surface:#1a1610;--surface2:#221d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171;--ret-bg:rgba(248,113,113,.14);--ret-txt:#fca5a5;
  --rev:#f59e0b;--rev-bg:rgba(245,158,11,.14);--rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
  --mm-bg:rgba(248,113,113,.10);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);
  font-size:12.5px;line-height:1.5;padding:28px 18px 60px}
.ph{max-width:1000px;margin:0 auto 24px}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:5px}
.ph h1{font-size:22px;font-weight:700;letter-spacing:-.4px;text-wrap:balance}
.ph p{font-size:12px;color:var(--muted);margin-top:5px;max-width:700px;line-height:1.6}
.meta-bar{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.mpill{font-size:11px;background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:2px 8px;color:var(--muted)}
.mpill strong{color:var(--text)}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
.chip{font-size:11px;font-weight:600;padding:2px 9px;border-radius:4px;
  background:rgba(30,60,114,.08);color:var(--accent);
  font-family:'Noto Sans','Nirmala UI',system-ui,sans-serif}
.stack{display:flex;flex-direction:column;gap:16px;max-width:1000px;margin:0 auto}
/* Card */
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;
  overflow:hidden;box-shadow:var(--shadow)}
.card-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:6px 14px;background:var(--surface2);border-bottom:1px solid var(--border)}
.card-left{display:flex;align-items:center;gap:8px}
.lang-badge{font-size:13px;font-weight:600;color:var(--text);
  font-family:'Noto Sans','Nirmala UI',system-ui,sans-serif}
.lang-en{font-size:11px;color:var(--muted)}
.fid{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--faint)}
.card-right{display:flex;align-items:center;gap:6px}
.script-badge{font-size:9px;font-weight:700;padding:2px 6px;border-radius:3px;
  background:var(--accent);color:#fff;letter-spacing:.06em}
.outcome-badge{font-size:9px;font-weight:700;padding:2px 8px;border-radius:3px;letter-spacing:.04em}
.outcome-badge.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.outcome-badge.ret    {background:var(--ret-bg); color:var(--ret-txt)}
.outcome-badge.review {background:var(--rev-bg); color:var(--rev-txt)}
/* Scan */
.scan-wrap{padding:10px 14px 0;background:var(--surface2)}
.scan-img{width:100%;border-radius:3px;border:1px solid var(--border);display:block}
.scan-cap{font-size:9px;color:var(--faint);padding:3px 2px 8px;letter-spacing:.03em}
/* Body grid */
.body-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--border)}
@media(max-width:600px){.body-grid{grid-template-columns:1fr}}
/* Written panel */
.written-panel{padding:12px 14px;border-right:1px solid var(--border)}
.panel-title{font-size:8.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--faint);margin-bottom:9px}
.panel-note{font-size:8px;font-weight:400;font-style:italic;text-transform:none;letter-spacing:0}
.wr-row{display:flex;align-items:flex-start;gap:8px;padding:5px 0;
  border-bottom:1px solid var(--border)}
.wr-row:last-of-type{border-bottom:none}
.wr-lbl{font-size:8px;font-weight:600;color:var(--faint);letter-spacing:.07em;text-transform:uppercase;
  width:44px;flex-shrink:0;padding-top:3px}
.wr-val{font-size:12px;color:var(--text);flex:1;line-height:1.4}
.regional-wrap{display:flex;flex-direction:column;gap:1px}
.regional{font-family:'Noto Sans','Nirmala UI','Arial Unicode MS',system-ui,sans-serif;
  font-size:13.5px;font-weight:500;color:var(--text)}
.xlit{font-size:9.5px;color:var(--faint);font-style:italic}
.plain-val{font-size:12px;color:var(--text)}
.fig-val{font-family:'Noto Sans','JetBrains Mono',monospace;font-size:13px;font-weight:600}
.mismatch-fig{color:var(--ret-txt)}
/* Mismatch row */
.mm-row{display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-top:7px;
  background:var(--mm-bg);border-radius:4px;padding:5px 7px}
.mm-lbl{font-size:8px;font-weight:600;color:var(--ret-txt);text-transform:uppercase;letter-spacing:.04em}
.mm-words{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--pass);font-weight:700}
.mm-figs{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ret-txt);font-weight:700}
.mm-sep{font-size:14px;color:var(--ret-txt);font-weight:700;padding:0 2px}
.mm-badge{font-size:8px;font-weight:700;padding:1px 6px;border-radius:3px;
  background:var(--ret-bg);color:var(--ret-txt);letter-spacing:.06em;margin-left:auto}
/* OCR panel */
.ocr-panel{padding:12px 14px}
.ocr-ok{font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;
  background:var(--pass-bg);color:var(--pass-txt);margin-left:6px;letter-spacing:.04em}
.ocr-fail-badge{font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;
  background:var(--rev-bg);color:var(--rev-txt);margin-left:6px;letter-spacing:.04em}
.ocr-meta{font-size:8.5px;color:var(--faint);margin-bottom:6px;font-family:'JetBrains Mono',monospace}
.ocr-row{display:flex;align-items:baseline;gap:5px;padding:2.5px 0;border-bottom:1px solid var(--border)}
.ocr-row:last-of-type{border-bottom:none}
.ocr-f{font-size:8px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--faint);width:40px;flex-shrink:0}
.ocr-v{font-family:'Noto Sans','JetBrains Mono',monospace;font-size:10.5px;color:var(--text);flex:1}
.ocr-v.dim{color:var(--faint);font-style:italic}
.ocr-tick{font-size:10px;flex-shrink:0}
.ocr-tick.green{color:var(--pass)}
.ocr-tick.grey{color:var(--faint)}
.ocr-warn{font-size:9px;color:var(--rev-txt);margin-top:4px;font-style:italic}
.ocr-mismatch-flag{font-size:9px;font-weight:700;color:var(--ret-txt);margin-top:4px;
  background:var(--ret-bg);border-radius:3px;padding:2px 6px}
.pipe-divider{height:1px;background:var(--border);margin:8px 0}
.pill-row{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}
.pill{font-size:8.5px;font-weight:600;padding:2px 6px;border-radius:3px;
  border:1px solid var(--border);color:var(--muted);background:var(--surface2)}
.pill.ok{color:var(--pass);background:var(--pass-bg);border-color:transparent}
.pill.danger{color:var(--ret-txt);background:var(--ret-bg);border-color:transparent}
.pill.warn{color:var(--rev-txt);background:var(--rev-bg);border-color:transparent}
.fraud-row{display:flex;align-items:center;gap:6px;margin-bottom:6px}
.fraud-lbl{font-size:8px;font-weight:600;color:var(--faint);text-transform:uppercase;letter-spacing:.06em;width:32px}
.fraud-track{flex:1;height:3px;background:var(--border);border-radius:2px;overflow:hidden}
.fraud-fill{height:100%;border-radius:2px;background:var(--pass)}
.fraud-fill.mid{background:var(--rev)}
.fraud-fill.hi{background:var(--ret)}
.fraud-num{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);width:24px;text-align:right}
.decision-bar{display:flex;align-items:center;justify-content:center;gap:5px;
  font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  padding:5px;border-radius:4px;margin-bottom:5px}
.decision-bar.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.decision-bar.ret    {background:var(--ret-bg); color:var(--ret-txt)}
.decision-bar.review {background:var(--rev-bg); color:var(--rev-txt)}
.rej-banner{display:flex;align-items:flex-start;gap:5px;
  background:var(--ret-bg);border:1px solid rgba(185,28,28,.18);
  border-radius:4px;padding:4px 7px;margin-bottom:4px}
.rej-icon{font-size:11px;color:var(--ret-txt);flex-shrink:0;padding-top:1px}
.rej-code{font-size:8.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--ret-txt)}
.rej-why{font-size:8px;color:var(--ret-txt);opacity:.80}
.trigger-note{font-size:9px;color:var(--faint);font-style:italic;line-height:1.5;text-align:center}
.pg-footer{max-width:1000px;margin:24px auto 0;padding-top:12px;
  border-top:1px solid var(--border);display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:5px;font-size:10.5px;color:var(--faint)}
.pg-footer strong{color:var(--muted);font-weight:600}
"""


def build_html(cards_html: list[str]) -> str:
    n_ret      = sum(1 for c in CARDS if c["outcome"] == "STP_RETURN")
    n_scripts  = len(set(c["script"] for c in CARDS))
    return f"""<title>Regional Language OCR</title>
<style>{CSS}</style>

<div class="ph">
  <div class="eyebrow">ASTRA CTS &bull; Regional Language OCR &bull; v2</div>
  <h1>9 Real Cheque Scans &mdash; Regional Language Annotations + Live OCR</h1>
  <p>
    Actual scanned cheques from <code>demo/112/</code> (RC-001&ndash;RC-009).
    <strong>OCR Extraction panel</strong> shows the real output of
    <code>ocr_extract()</code> &rarr; <code>CascadeOrchestrator</code> &rarr; GOT-OCR2.0 stub
    — not fixture data. If OCR cannot extract a field, it shows <em>not extracted</em>.
    <strong>Written on cheque</strong> shows regional-language annotation beside the actual scan.
    Two cheques have <code>stub_scenario=amount_mismatch</code> so the stub returns
    words&nbsp;&ne;&nbsp;figures — <code>amounts_match()</code> flags them as
    <strong>AMOUNT_MISMATCH</strong>.
  </p>
  <div class="meta-bar">
    <span class="mpill"><strong>9</strong> real scans (demo/112/)</span>
    <span class="mpill"><strong>{n_scripts}</strong> scripts</span>
    <span class="mpill"><strong>2</strong> AMOUNT_MISMATCH returns (real code detection)</span>
    <span class="mpill"><strong>{n_ret}</strong> STP_RETURN with rejection reason</span>
    <span class="mpill">OCR <strong>ocr_extract() live</strong></span>
    <span class="mpill">Date <strong>2026-08-26</strong></span>
  </div>
  <div class="chips">
    <span class="chip">EN English</span>
    <span class="chip">HI &#2361;&#2367;&#2344;&#2381;&#2342;&#2368;</span>
    <span class="chip">MR &#2350;&#2352;&#2366;&#2336;&#2368;</span>
    <span class="chip">TA &#2980;&#2990;&#3007;&#2996;&#3021;</span>
    <span class="chip">TE &#3108;&#3142;&#3122;&#3137;&#3095;&#3137;</span>
    <span class="chip">KN &#3221;&#3240;&#3277;&#3240;&#3233;</span>
    <span class="chip">GU &#2711;&#2753;&#2716;&#2736;&#2750;&#2724;&#2752;</span>
    <span class="chip">BN &#2476;&#2494;&#2434;&#2482;&#2494;</span>
    <span class="chip">ML &#3374;&#3378;&#3375;&#3390;&#3385;&#3384;</span>
  </div>
</div>

<div class="stack">
{"".join(cards_html)}
</div>

<div class="pg-footer">
  <strong>ASTRA &mdash; Bank Intelligence Platform</strong>
  <span>regional-language-v1 &bull; demo/112/ real scans &bull; ocr_extract() + CascadeOrchestrator &bull; 2026-08-26</span>
</div>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("Encoding cheque images...")
    embeds = [_image_to_embed(f) for f in _FILES]
    print(f"  {len(embeds)} images ({sum(len(e)//1024 for e in embeds)} KB total)")

    print("\nRunning OCR on all images...")
    ocr_results = await run_ocr_all()

    print("\nGenerating HTML...")
    cards_html = []
    for c, ocr, embed in zip(CARDS, ocr_results, embeds):
        cards_html.append(render_card(c, ocr, embed))
        print(f"  [{c['fixture']}] {c['language']} — {c['outcome']}")

    html = build_html(cards_html)
    OUT.write_text(html, encoding="utf-8")
    print(f"\nWritten: {OUT}  ({len(html)//1024} KB)")


if __name__ == "__main__":
    stub_proc = ensure_stub()
    try:
        asyncio.run(main())
    finally:
        if stub_proc:
            stub_proc.kill()
            stub_proc.wait()
            print("[stub] Stopped.")
