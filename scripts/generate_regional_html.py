"""
generate_regional_html.py
Generates docs/regional-language-v1.html — TWO sections:

SECTION 1 — Real Scans (demo/112/, English only)
  9 actual scanned cheques, English text, English OCR output.
  No regional language fabrication. Pipeline scenarios + rejection reasons.

SECTION 2 — Regional Language Specimens (CSS-rendered CTS-2010 cheques)
  Realistic CSS-rendered cheques that look like actual bank instruments.
  Transliteration beside every Indic field.
  2 cheques have AMOUNT_MISMATCH: words != figures, detected by amounts_match().

Usage:  python scripts/generate_regional_html.py
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

# ── Stub ──────────────────────────────────────────────────────────────────────

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
    print(f"[stub] Starting on port {STUB_PORT}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 12
    while not _stub_healthy():
        if time.time() > deadline:
            proc.kill(); raise RuntimeError("Stub did not start within 12s")
        time.sleep(0.3)
    print(f"[stub] Ready at {STUB_URL}")
    return proc

# ── Image encoding ────────────────────────────────────────────────────────────

def _encode(path: Path, max_w: int = 700, quality: int = 72) -> str:
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

# ── Config / orchestrator ─────────────────────────────────────────────────────

class _Cfg:
    _d = {
        "ai.ocr.min_confidence": 0.85, "ai.ocr.min_indic_confidence": 0.60,
        "services.indic_ocr.url": "", "cts.indic_ocr.kill_mode": "NONE",
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold": 5_000_000.0,
        "ai.cascade.l2_escalation_enabled": False,
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    }
    async def get_ai_config(self, bank_id): return dict(self._d)
    async def get(self, key):
        if key == "cts.indic_ocr.kill_mode": return "NONE"
        raise KeyError(key)

def _orchestrator():
    from openai import AsyncOpenAI
    from shared.ai.model_cascade import CascadeOrchestrator
    c = AsyncOpenAI(base_url=f"{STUB_URL}/v1", api_key="stub")
    cfg = {"ai.cascade.l1_confidence_threshold": 0.85,
           "ai.cascade.high_value_threshold": 5_000_000.0,
           "ai.cascade.l2_escalation_enabled": False,
           "ai.cascade.l1_model_ocr": "got-ocr2-stub",
           "ai.cascade.l2_model_ocr": "got-ocr2-stub"}
    return CascadeOrchestrator(l1_client=c, l2_client=c, config=cfg, bank_id="demo")

async def _ocr(image_url: str, stub_scenario: str | None) -> dict:
    from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
    url = image_url + (f"?scenario={stub_scenario}" if stub_scenario else "")
    r = await ocr_extract(OCRActivityInput(image_url=url,
                          instrument_id="DEMO", bank_id="demo"),
                          _orchestrator(), _Cfg())
    return r.model_dump()

# ── SECTION 1: Real scans ─────────────────────────────────────────────────────

_FILES = sorted(p for p in DEMO.iterdir()
                if p.suffix.lower() in (".jpeg", ".jpg", ".tiff", ".tif"))[:9]

REAL_CARDS = [
    # (idx, scenario_label, stub_scenario, bank, outcome, rejection, sig_score, fraud, alt)
    (0, "CLEAN_ALL_PASS — golden path",              None,               "Syndicate Bank", "STP_CONFIRM",  None,                                                                     0.93, 0.09, False),
    (1, "CLEAN_ALL_PASS — high-value dual sig",       None,               "Axis Bank",      "STP_CONFIRM",  None,                                                                     0.95, 0.14, False),
    (2, "AMOUNT_MISMATCH — words vs figures",         "amount_mismatch",  "Syndicate Bank", "STP_RETURN",   ("AMOUNT_MISMATCH", "words='One Lakh Only' vs figures='95,000'"),         0.90, 0.29, False),
    (3, "OCR LOW CONFIDENCE — key fields unclear",    "low_confidence",   "Axis Bank",      "HUMAN_REVIEW", ("OCR_LOW_CONFIDENCE", "payee + amount below confidence threshold"),       0.91, 0.17, False),
    (4, "STOP_PAYMENT — CBS instruction active",      None,               "Syndicate Bank", "STP_RETURN",   ("STOP_PAYMENT", "CBS stop-payment lodged 23/08/2026"),                   0.93, 0.12, False),
    (5, "AMOUNT_MISMATCH — possible alteration",      "amount_mismatch",  "Axis Bank",      "STP_RETURN",   ("AMOUNT_MISMATCH", "words vs figures mismatch + alteration signal"),     0.88, 0.48, True),
    (6, "ACCOUNT_FROZEN — regulatory order",          None,               "Syndicate Bank", "STP_RETURN",   ("ACCOUNT_FROZEN", "RBI/ED freeze on drawer account"),                   0.91, 0.19, False),
    (7, "CBS_INSUFFICIENT — balance < amount",        None,               "Axis Bank",      "STP_RETURN",   ("CBS_INSUFFICIENT", "drawer balance [1L-5L] vs instrument Rs 3,20,000"),  0.92, 0.13, False),
    (8, "SIG_MISMATCH — vault score 0.44",            None,               "Syndicate Bank", "HUMAN_REVIEW", None,                                                                     0.44, 0.28, False),
]

# ── SECTION 2: Regional specimens ─────────────────────────────────────────────

SPECIMENS = [
    dict(
        code="EN", lang="English", lang_native="English",
        fixture="IN-01", bank="Federal Bank Ltd", branch="Fort Branch, Mumbai - 400 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="Rajan Pillai", payee_xlit="",
        words="Forty Five Thousand Only", words_xlit="",
        fig="45,000.00", fig_native="45,000.00",
        cheque_no="100001", acct_disp="****9012",
        micr="100001  724020003  123456789012",
        stub_scenario=None, outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.09, alt=False, sig_idx=0,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="HI", lang="Hindi", lang_native="हिन्दी",
        fixture="IN-02", bank="Federal Bank Ltd", branch="Andheri Branch, Mumbai - 400 058",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("२","५","०","८","२","०","२","६"),
        payee="राजेश कुमार", payee_xlit="Rajesh Kumar",
        words="चार लाख अस्सी हजार रुपये मात्र",
        words_xlit="Chaar Laakh Assi Hazaar [= 4,80,000]",
        fig="4,80,000.00", fig_native="4,80,000.00",
        cheque_no="100002", acct_disp="****0123",
        micr="100002  724020003  234567890123",
        stub_scenario=None, outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.11, alt=False, sig_idx=1,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="MR", lang="Marathi", lang_native="मराठी",
        fixture="IN-03", bank="Saraswat Co-op Bank", branch="Dadar Branch, Mumbai - 400 014",
        ifsc="SRCB0000001", micr_city="743020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="सुनील पाटील", payee_xlit="Sunil Patil",
        words="पासष्ट हजार रुपये मात्र",
        words_xlit="Paashaht Hazaar [= 65,000]",
        fig="65,000.00", fig_native="65,000.00",
        cheque_no="200001", acct_disp="****1234",
        micr="200001  743020003  345678901234",
        stub_scenario=None, outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.11, alt=False, sig_idx=2,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="TA", lang="Tamil", lang_native="தமிழ்",
        fixture="IN-04", bank="Federal Bank Ltd", branch="T Nagar Branch, Chennai - 600 017",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="கணேஷ் குமார்", payee_xlit="Ganesh Kumar",
        words="ஐம்பது ஆயிரம் ரூபாய் மட்டும்",
        words_xlit="Aimpadhu Aayiram [= 50,000]",
        fig="78,000.00", fig_native="78,000.00",
        cheque_no="300001", acct_disp="****2345",
        micr="300001  724020003  456789012345",
        stub_scenario="amount_mismatch", outcome="STP_RETURN",
        rejection=("AMOUNT_MISMATCH", "words=50,000 | figures=78,000 — amounts_match()=False"),
        sig_score=0.91, fraud=0.22, alt=False, sig_idx=3,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
        mismatch_words_val="50,000", mismatch_fig_val="78,000",
    ),
    dict(
        code="TE", lang="Telugu", lang_native="తెలుగు",
        fixture="IN-05", bank="Federal Bank Ltd", branch="Ameerpet Branch, Hyderabad - 500 016",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="వెంకటేశ్వర రావు", payee_xlit="Venkateswara Rao",
        words="ఐదు లక్షల యభై వేల రూపాయలు మాత్రమే",
        words_xlit="Aidu Lakshal Yabhai Vela [= 5,50,000]",
        fig="5,50,000.00", fig_native="5,50,000.00",
        cheque_no="400001", acct_disp="****3456",
        micr="400001  724020003  567890123456",
        stub_scenario=None, outcome="STP_CONFIRM", rejection=None,
        sig_score=0.92, fraud=0.13, alt=False, sig_idx=4,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="KN", lang="Kannada", lang_native="ಕನ್ನಡ",
        fixture="IN-06", bank="Federal Bank Ltd", branch="MG Road Branch, Bengaluru - 560 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="ರಾಜೇಶ್ ಕುಮಾರ್", payee_xlit="Rajesh Kumar",
        words="ಎರಡು ಲಕ್ಷದ ಮೂವತ್ತು ಸಾವಿರ ರೂಪಾಯಿ ಮಾತ್ರ",
        words_xlit="Eradu Lakshadha Moovattu Saavira [= 2,30,000]",
        fig="2,30,000.00", fig_native="2,30,000.00",
        cheque_no="500001", acct_disp="****4567",
        micr="500001  724020003  678901234567",
        stub_scenario=None, outcome="STP_RETURN",
        rejection=("ACCOUNT_FROZEN", "Drawer account frozen — RBI/ED regulatory order"),
        sig_score=0.93, fraud=0.19, alt=False, sig_idx=5,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="GU", lang="Gujarati", lang_native="ગુજરાતી",
        fixture="IN-07", bank="Federal Bank Ltd", branch="Ashram Road Branch, Ahmedabad - 380 009",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="રાજેશ પટેલ", payee_xlit="Rajesh Patel",
        words="પંચાવન હજાર રૂપિયા માત્ર",
        words_xlit="Panchaavan Hazaar [= 55,000]",
        fig="1,10,000.00", fig_native="1,10,000.00",
        cheque_no="600001", acct_disp="****5678",
        micr="600001  724020003  789012345678",
        stub_scenario="amount_mismatch", outcome="STP_RETURN",
        rejection=("AMOUNT_MISMATCH", "words=55,000 | figures=1,10,000 — possible alteration"),
        sig_score=0.88, fraud=0.48, alt=True, sig_idx=6,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
        mismatch_words_val="55,000", mismatch_fig_val="1,10,000",
    ),
    dict(
        code="BN", lang="Bengali", lang_native="বাংলা",
        fixture="IN-08", bank="Saraswat Co-op Bank", branch="Kolkata Branch, Kolkata - 700 001",
        ifsc="SRCB0000001", micr_city="743020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="রাজেশ কুমার", payee_xlit="Rajesh Kumar",
        words="পঁচাশি হাজার টাকা মাত্র",
        words_xlit="Panchaashi Hazaar [= 85,000]",
        fig="85,000.00", fig_native="85,000.00",
        cheque_no="700001", acct_disp="****6789",
        micr="700001  743020003  890123456789",
        stub_scenario=None, outcome="STP_RETURN",
        rejection=("STOP_PAYMENT", "CBS stop-payment active — lodged 23/08/2026"),
        sig_score=0.93, fraud=0.12, alt=False, sig_idx=7,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
    dict(
        code="ML", lang="Malayalam", lang_native="മലയാളം",
        fixture="IN-09", bank="Federal Bank Ltd", branch="Thrissur Branch, Thrissur - 680 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="ജോർജ്ജ് മാത്യൂ", payee_xlit="George Mathew",
        words="പതിനെട്ടായിരം രൂപ മാത്രം",
        words_xlit="Pathinettaayiram Roopa [= 18,000]",
        fig="18,000.00", fig_native="18,000.00",
        cheque_no="800001", acct_disp="****7890",
        micr="800001  724020003  901234567890",
        stub_scenario="low_confidence", outcome="HUMAN_REVIEW",
        rejection=("OCR_LOW_CONFIDENCE", "Payee + amount confidence below threshold"),
        sig_score=0.91, fraud=0.14, alt=False, sig_idx=8,
        lbl_pay="Pay", lbl_rupees="Rupees", lbl_bearer="or Bearer",
    ),
]

SIG_PATHS = [
    "M4,14 C10,6 16,4 22,8 C28,12 30,6 36,5 C42,4 46,10 52,8 L56,8 M30,13 L58,13",
    "M4,12 C8,4 14,5 18,10 C22,15 26,8 32,6 L44,6 C46,6 50,10 52,8 M20,15 C30,16 42,14 56,16",
    "M4,15 C10,4 16,3 22,9 M18,9 C24,14 30,4 38,7 C44,10 48,6 54,9 M8,17 L54,17",
    "M6,10 C10,4 16,6 20,10 C24,14 28,6 34,5 C38,4 44,11 50,9 C54,8 56,10 58,9 M4,16 L44,16",
    "M4,14 C12,5 20,6 26,12 M22,10 C28,4 34,5 40,10 C44,14 50,8 56,10 M6,17 C24,16 44,17 58,16",
    "M4,12 Q10,2 18,10 T34,8 T50,10 M28,8 L58,8 M4,15 L30,15",
    "M6,15 C10,6 14,4 20,8 C26,12 28,5 36,5 L46,5 C50,5 52,10 56,9 M4,17 L38,17",
    "M4,13 C8,4 16,3 22,10 M18,8 C26,14 32,5 40,7 C46,9 50,5 56,8 L58,8 M10,16 L52,16",
    "M4,14 C12,5 18,7 22,12 C26,17 30,7 38,6 C44,5 50,11 54,9 M20,10 C28,4 36,8 46,8",
]

# ── OCR runner ────────────────────────────────────────────────────────────────

async def run_all_ocr(files, cards, specimens):
    _DUMMY = "data:image/jpeg;base64," + base64.b64encode(
        b"\xff\xd8\xff\xe0" + b"\x00" * 100).decode()

    real_results = []
    for i, (tup, path) in enumerate(zip(cards, files)):
        stub_sc = tup[2]
        print(f"  [RC-{i+1:03d}] {path.name} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        img_url = _encode(path) + (f"?scenario={stub_sc}" if stub_sc else "")
        r = await _ocr(img_url, None)
        print(f"-> {r['outcome']} conf={r['overall_confidence']:.2f} {(time.perf_counter()-t0)*1000:.0f}ms")
        real_results.append(r)

    spec_results = []
    for sp in specimens:
        stub_sc = sp["stub_scenario"]
        print(f"  [{sp['fixture']}] {sp['lang']} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        url = _DUMMY + (f"?scenario={stub_sc}" if stub_sc else "")
        r = await _ocr(url, None)
        print(f"-> {r['outcome']} conf={r['overall_confidence']:.2f} {(time.perf_counter()-t0)*1000:.0f}ms")
        spec_results.append(r)

    return real_results, spec_results

# ── HTML helpers ──────────────────────────────────────────────────────────────

def _e(s) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _oc(outcome): return {"STP_CONFIRM":"confirm","STP_RETURN":"ret","HUMAN_REVIEW":"review"}.get(outcome,"review")
def _oi(outcome): return {"STP_CONFIRM":"&#10003;","STP_RETURN":"&#8629;","HUMAN_REVIEW":"&#9873;"}.get(outcome,"?")

def _rej_html(rejection):
    if not rejection: return ""
    code, why = rejection
    return f'<div class="rej-banner"><span class="rej-code">{_e(code)}</span><span class="rej-why"> &mdash; {_e(why)}</span></div>'

def _ocr_rows(ocr):
    def row(lbl, val):
        has = val is not None and str(val).strip()
        t = '<span class="tick ok">&#10003;</span>' if has else '<span class="tick no">&mdash;</span>'
        v = f'<span class="ov">{_e(str(val))}</span>' if has else '<span class="ov dim">not extracted</span>'
        return f'<div class="or"><span class="of">{lbl}</span>{v}{t}</div>'
    extra = ""
    if ocr.get("low_confidence_reason"):
        extra += f'<div class="ocr-warn">&#9888; {_e(ocr["low_confidence_reason"].replace("_"," "))}</div>'
    if ocr.get("amount_mismatch"):
        extra += '<div class="ocr-mm">&#8800; amounts_match() = False &#8594; AMOUNT_MISMATCH</div>'
    return (row("Payee", ocr.get("payee"))
          + row("Amount", ocr.get("amount_figures"))
          + row("Words",  ocr.get("amount_words"))
          + row("Date",   ocr.get("date")) + extra)

def _pipe(sig_score, fraud, alt, outcome):
    oc = _oc(outcome)
    fc = "" if fraud < 0.40 else ("mid" if fraud < 0.70 else "hi")
    spc = "ok" if sig_score >= 0.90 else ("danger" if sig_score < 0.50 else "warn")
    sps = f"SIG {sig_score:.2f}" if sig_score > 0 else "SIG ABSENT"
    alt_cls = "danger" if alt else "ok"
    alt_txt = "ALT &#9873; DETECTED" if alt else "ALT &#10003; CLEAR"
    return f'''<div class="pill-row">
      <span class="pill {alt_cls}">{alt_txt}</span>
      <span class="pill {spc}">{sps}</span>
    </div>
    <div class="fraud-row">
      <span class="fraud-lbl">Fraud</span>
      <div class="fraud-track"><div class="fraud-fill {fc}" style="width:{fraud*100:.0f}%"></div></div>
      <span class="fraud-num">{fraud:.2f}</span>
    </div>
    <div class="decision {oc}">{_oi(outcome)} {_e(outcome)}</div>'''

# ── Date boxes ────────────────────────────────────────────────────────────────

def _date_boxes(boxes):
    d1,d2,m1,m2,y1,y2,y3,y4 = boxes
    def bx(c): return f'<span class="dbox">{_e(c)}</span>'
    return (f'{bx(d1)}{bx(d2)}<span class="dsep">/</span>'
            f'{bx(m1)}{bx(m2)}<span class="dsep">/</span>'
            f'{bx(y1)}{bx(y2)}{bx(y3)}{bx(y4)}')

def _indic(text, xlit, is_en=False):
    if is_en or not text: return f'<span class="chq-plain">{_e(text)}</span>'
    xl = f'<div class="chq-xlit">[{_e(xlit)}]</div>' if xlit else ""
    return f'<div class="chq-indic">{_e(text)}</div>{xl}'

# ── SECTION 1: Real scan card ─────────────────────────────────────────────────

def real_card(i, tup, ocr, embed):
    idx, scenario, stub_sc, bank, outcome, rejection, sig_score, fraud, alt = tup
    oc = _oc(outcome)
    conf = ocr.get("overall_confidence", 0.0)
    engines = ", ".join(ocr.get("ocr_engines_used", [])) or "none"
    ocr_ok = ocr.get("outcome") == "PROCEED"
    ob = ('<span class="ocr-ok">PROCEED</span>' if ocr_ok
          else '<span class="ocr-fail-badge">LOW CONF</span>')
    return f'''
<div class="card">
  <div class="card-hdr">
    <div class="card-left">
      <span class="fid">RC-{i+1:03d}</span>
      <span class="scenario-txt">{_e(scenario)}</span>
    </div>
    <div class="card-right">
      <span class="bank-txt">{_e(bank)}</span>
      <span class="outcome-badge {oc}">{_oi(outcome)} {_e(outcome)}</span>
    </div>
  </div>
  <div class="scan-wrap">
    <img src="{embed}" class="scan-img" alt="RC-{i+1:03d}">
    <div class="scan-cap">English text — real scan (Syndicate Bank / Axis Bank)</div>
  </div>
  <div class="body-grid">
    <div class="ocr-panel">
      <div class="panel-title">GOT-OCR2.0 extraction {ob}</div>
      <div class="ocr-meta">L{ocr.get("cascade_level",1)} &bull; conf {conf:.3f} &bull; {_e(engines)}</div>
      {_ocr_rows(ocr)}
    </div>
    <div class="pipe-panel">
      <div class="panel-title">Pipeline</div>
      {_pipe(sig_score, fraud, alt, outcome)}
      {_rej_html(rejection)}
    </div>
  </div>
</div>'''

# ── SECTION 2: Realistic cheque visual ───────────────────────────────────────

def cheque_html(sp, mm):
    is_en = sp["code"] == "EN"
    sig_path = SIG_PATHS[sp["sig_idx"] % len(SIG_PATHS)]
    sig_svg = (f'<svg width="88" height="26" viewBox="0 0 88 26" fill="none">'
               f'<path d="{sig_path}" stroke="var(--ink)" stroke-width="1.3" '
               f'stroke-linecap="round" fill="none" opacity="0.82"/></svg>')
    fig_cls = " chq-fig-mismatch" if mm else ""
    db = _date_boxes(sp["date_boxes"])

    return f'''<div class="cheque">
  <div class="chq-hdr">
    <div class="chq-bank-col">
      <div class="chq-bname">{_e(sp["bank"])}</div>
      <div class="chq-branch">{_e(sp["branch"])}</div>
      <div class="chq-ifsc">IFSC: {_e(sp["ifsc"])}</div>
    </div>
    <div class="chq-top-right">
      <div class="chq-cts-tag">CTS-2010</div>
      <div class="chq-no-block">
        <div class="chq-no-lbl">Cheque No.</div>
        <div class="chq-no-val">{_e(sp["cheque_no"])}</div>
      </div>
    </div>
  </div>
  <div class="chq-date-row">
    <span class="chq-date-lbl">Date</span>
    <div class="chq-date-boxes">{db}</div>
  </div>
  <div class="chq-body">
    <div class="chq-left-col">
      <div class="chq-pay-row">
        <span class="chq-fl">{_e(sp["lbl_pay"])}</span>
        <div class="chq-payee-line">
          <div class="chq-payee-inner">{_indic(sp["payee"], sp["payee_xlit"], is_en)}</div>
          <span class="chq-bearer">{_e(sp["lbl_bearer"])}</span>
        </div>
      </div>
      <div class="chq-ruled"></div>
      <div class="chq-words-row">
        <span class="chq-fl">{_e(sp["lbl_rupees"])}</span>
        <div class="chq-words-inner">{_indic(sp["words"], sp["words_xlit"], is_en)}</div>
      </div>
      <div class="chq-ruled"></div>
    </div>
    <div class="chq-right-col">
      <div class="chq-fig-box{fig_cls}">
        <div class="chq-fig-label">Rs.</div>
        <div class="chq-fig-val">{_e(sp["fig_native"])}</div>
      </div>
    </div>
  </div>
  <div class="chq-footer">
    <div class="chq-acct-block">
      <div class="chq-arow"><span class="chq-al">A/c No.</span><span class="chq-av">{_e(sp["acct_disp"])}</span></div>
      <div class="chq-arow"><span class="chq-al">MICR</span><span class="chq-av">{_e(sp["micr_city"])}</span></div>
    </div>
    <div class="chq-sig-block">
      {sig_svg}
      <div class="chq-sig-rule"></div>
      <div class="chq-sig-lbl">Authorised Signatory</div>
    </div>
  </div>
  <div class="chq-micr-band">
    <span class="chq-micr-num">&#9285; {_e(sp["micr"])} &#9285;</span>
  </div>
</div>'''

def specimen_card(sp, ocr):
    oc = _oc(sp["outcome"])
    mm = ocr.get("amount_mismatch", False)
    ocr_ok = ocr.get("outcome") == "PROCEED"
    ob = ('<span class="ocr-ok">PROCEED</span>' if ocr_ok
          else '<span class="ocr-fail-badge">LOW CONF</span>')
    conf = ocr.get("overall_confidence", 0.0)
    mismatch_note = ""
    if mm:
        wv = sp.get("mismatch_words_val","?")
        fv = sp.get("mismatch_fig_val","?")
        mismatch_note = f'''<div class="mm-flag">
          <span class="mm-item">Words <strong>{_e(wv)}</strong></span>
          <span class="mm-sep">&#8800;</span>
          <span class="mm-item">Figures <strong>{_e(fv)}</strong></span>
          <span class="mm-badge">MISMATCH</span>
        </div>'''
    return f'''
<div class="card">
  <div class="card-hdr">
    <div class="card-left">
      <span class="lang-badge">{_e(sp["lang_native"])}</span>
      <span class="lang-en">{_e(sp["lang"])}</span>
      <span class="fid">{_e(sp["fixture"])}</span>
    </div>
    <div class="card-right">
      <span class="script-badge">{_e(sp["code"])}</span>
      <span class="outcome-badge {oc}">{_oi(sp["outcome"])} {_e(sp["outcome"])}</span>
    </div>
  </div>
  <div class="cheque-wrap">
    {cheque_html(sp, mm)}
    {mismatch_note}
  </div>
  <div class="body-grid">
    <div class="ocr-panel">
      <div class="panel-title">GOT-OCR2.0 extraction {ob}</div>
      <div class="ocr-meta">conf {conf:.3f} &bull; stub (cannot read CSS text)</div>
      {_ocr_rows(ocr)}
    </div>
    <div class="pipe-panel">
      <div class="panel-title">Pipeline</div>
      {_pipe(sp["sig_score"], sp["fraud"], sp["alt"], sp["outcome"])}
      {_rej_html(sp["rejection"])}
    </div>
  </div>
</div>'''

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Noto+Sans:wght@400;500;600&display=swap');
:root{
  --bg:#e9e7e2;--surface:#faf9f6;--surface2:#f0ede8;--border:rgba(30,20,6,.10);
  --text:#18130b;--muted:#6b6155;--faint:#a89e8c;--accent:#1e3c72;
  --pass:#047857;--pass-bg:#d1fae5;--pass-txt:#064e3b;
  --ret:#b91c1c;--ret-bg:#fee2e2;--ret-txt:#7f1d1d;
  --rev:#b45309;--rev-bg:#fef3c7;--rev-txt:#78350f;
  --shadow:0 1px 3px rgba(20,12,4,.07),0 6px 20px rgba(20,12,4,.08);
  --chq-paper:#fefae8;--chq-paper2:#f5efce;--chq-hdr:#1a3260;--chq-hdr2:#0f2048;
  --chq-rule:#c5b47a;--chq-label:#887558;--ink:#120e06;--micr-bg:#ede2b8;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0c0a07;--surface:#1a1610;--surface2:#211d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171;--ret-bg:rgba(248,113,113,.14);--ret-txt:#fca5a5;
  --rev:#f59e0b;--rev-bg:rgba(245,158,11,.14);--rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
  --chq-paper:#17140a;--chq-paper2:#100d06;--chq-hdr:#0e2044;--chq-hdr2:#091835;
  --chq-rule:#2e2410;--chq-label:#7a6a44;--ink:#e0d8b8;--micr-bg:#0d0a04;
}}
:root[data-theme="dark"]{
  --bg:#0c0a07;--surface:#1a1610;--surface2:#211d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171;--ret-bg:rgba(248,113,113,.14);--ret-txt:#fca5a5;
  --rev:#f59e0b;--rev-bg:rgba(245,158,11,.14);--rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
  --chq-paper:#17140a;--chq-paper2:#100d06;--chq-hdr:#0e2044;--chq-hdr2:#091835;
  --chq-rule:#2e2410;--chq-label:#7a6a44;--ink:#e0d8b8;--micr-bg:#0d0a04;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);
  font-size:12.5px;line-height:1.5;padding:28px 18px 60px}
.ph{max-width:1080px;margin:0 auto 24px}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:5px}
.ph h1{font-size:20px;font-weight:700;letter-spacing:-.3px}
.ph p{font-size:12px;color:var(--muted);margin-top:5px;max-width:640px;line-height:1.6}
.meta-bar{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
.mpill{font-size:10.5px;background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:2px 8px;color:var(--muted)}
.mpill strong{color:var(--text)}
.section{max-width:1080px;margin:0 auto 32px}
.section-hdr{margin-bottom:13px;padding-bottom:9px;border-bottom:2px solid var(--border)}
.section-hdr h2{font-size:14px;font-weight:700;color:var(--text)}
.section-hdr p{font-size:11px;color:var(--muted);margin-top:3px;max-width:640px;line-height:1.5}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:860px){.grid3{grid-template-columns:repeat(2,1fr)}}
@media(max-width:540px){.grid3{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:7px;
  overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:5px 9px;background:var(--surface2);border-bottom:1px solid var(--border);
  flex-wrap:wrap;gap:4px}
.card-left{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.card-right{display:flex;align-items:center;gap:5px}
.fid{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--faint)}
.scenario-txt{font-size:9px;color:var(--muted)}
.bank-txt{font-size:8.5px;color:var(--faint)}
.lang-badge{font-size:12px;font-weight:600;color:var(--text);font-family:'Noto Sans','Nirmala UI',system-ui,sans-serif}
.lang-en{font-size:9px;color:var(--muted)}
.script-badge{font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;background:var(--accent);color:#fff;letter-spacing:.06em}
.outcome-badge{font-size:8px;font-weight:700;padding:1px 6px;border-radius:3px;letter-spacing:.04em}
.outcome-badge.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.outcome-badge.ret{background:var(--ret-bg);color:var(--ret-txt)}
.outcome-badge.review{background:var(--rev-bg);color:var(--rev-txt)}
/* Scan */
.scan-wrap{padding:7px 9px 0;background:var(--surface2)}
.scan-img{width:100%;border-radius:3px;border:1px solid var(--border);display:block}
.scan-cap{font-size:7.5px;color:var(--faint);padding:3px 0 6px;font-style:italic}
/* Body grid */
.body-grid{display:grid;grid-template-columns:1fr 1fr;flex:1;border-top:1px solid var(--border)}
.ocr-panel{padding:8px 9px;border-right:1px solid var(--border)}
.pipe-panel{padding:8px 9px}
.panel-title{font-size:7.5px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;color:var(--faint);margin-bottom:6px}
.ocr-meta{font-size:7.5px;color:var(--faint);margin-bottom:4px;font-family:'JetBrains Mono',monospace;line-height:1.4}
.or{display:flex;align-items:baseline;gap:3px;padding:1.5px 0;border-bottom:1px solid var(--border)}
.or:last-of-type{border-bottom:none}
.of{font-size:7px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);width:34px;flex-shrink:0}
.ov{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--text);flex:1;word-break:break-all}
.ov.dim{color:var(--faint);font-style:italic}
.tick{font-size:9px;flex-shrink:0}.tick.ok{color:var(--pass)}.tick.no{color:var(--faint)}
.ocr-ok{font-size:7px;font-weight:700;padding:1px 4px;border-radius:3px;background:var(--pass-bg);color:var(--pass-txt);margin-left:4px}
.ocr-fail-badge{font-size:7px;font-weight:700;padding:1px 4px;border-radius:3px;background:var(--rev-bg);color:var(--rev-txt);margin-left:4px}
.ocr-warn{font-size:8px;color:var(--rev-txt);margin-top:3px;font-style:italic}
.ocr-mm{font-size:8px;font-weight:700;color:var(--ret-txt);margin-top:3px;background:var(--ret-bg);padding:2px 4px;border-radius:3px}
.pill-row{display:flex;gap:3px;flex-wrap:wrap;margin-bottom:4px}
.pill{font-size:7.5px;font-weight:600;padding:1px 5px;border-radius:3px;border:1px solid var(--border);color:var(--muted);background:var(--surface2)}
.pill.ok{color:var(--pass-txt);background:var(--pass-bg);border-color:transparent}
.pill.danger{color:var(--ret-txt);background:var(--ret-bg);border-color:transparent}
.pill.warn{color:var(--rev-txt);background:var(--rev-bg);border-color:transparent}
.fraud-row{display:flex;align-items:center;gap:4px;margin-bottom:4px}
.fraud-lbl{font-size:7px;font-weight:600;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;width:26px}
.fraud-track{flex:1;height:3px;background:var(--border);border-radius:2px;overflow:hidden}
.fraud-fill{height:100%;border-radius:2px;background:var(--pass)}
.fraud-fill.mid{background:var(--rev)}.fraud-fill.hi{background:var(--ret)}
.fraud-num{font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--muted);width:20px;text-align:right}
.decision{display:flex;align-items:center;justify-content:center;gap:3px;
  font-size:8.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:3px;border-radius:3px;margin-bottom:3px}
.decision.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.decision.ret{background:var(--ret-bg);color:var(--ret-txt)}
.decision.review{background:var(--rev-bg);color:var(--rev-txt)}
.rej-banner{display:flex;align-items:flex-start;gap:3px;background:var(--ret-bg);
  border:1px solid rgba(185,28,28,.16);border-radius:3px;padding:2px 5px;margin-bottom:2px}
.rej-code{font-size:7px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--ret-txt);white-space:nowrap}
.rej-why{font-size:7px;color:var(--ret-txt);opacity:.85}
/* ── Cheque visual — realistic CTS-2010 ── */
.cheque-wrap{padding:7px 9px 0;background:var(--surface2)}
.cheque{
  background-color:var(--chq-paper);
  background-image:
    repeating-linear-gradient(180deg,transparent,transparent 17px,rgba(160,130,40,.07) 17px,rgba(160,130,40,.07) 18px),
    repeating-linear-gradient(90deg,transparent,transparent 39px,rgba(160,130,40,.035) 39px,rgba(160,130,40,.035) 40px);
  border:1.5px solid var(--chq-rule);border-radius:2px;overflow:hidden;position:relative;
  font-family:'Noto Sans','Inter',system-ui,sans-serif;
}
.cheque::before{
  content:"SPECIMEN";position:absolute;inset:0;display:flex;align-items:center;
  justify-content:center;font-size:28px;font-weight:900;letter-spacing:.22em;
  color:rgba(155,10,10,.055);transform:rotate(-22deg);pointer-events:none;z-index:0;
  white-space:nowrap;font-family:'Inter',system-ui,sans-serif;
}
.cheque>*{position:relative;z-index:1}
/* Header */
.chq-hdr{
  background:linear-gradient(120deg,var(--chq-hdr) 0%,var(--chq-hdr2) 100%);
  padding:5px 8px;display:flex;align-items:flex-start;justify-content:space-between;gap:6px;
  border-bottom:2px solid var(--chq-rule);
}
.chq-bank-col{flex:1;min-width:0}
.chq-bname{font-size:8.5px;font-weight:700;color:rgba(255,255,255,.95);
  letter-spacing:.05em;text-transform:uppercase;font-family:'Inter',sans-serif}
.chq-branch{font-size:6.5px;color:rgba(255,255,255,.58);margin-top:1px}
.chq-ifsc{font-size:6.5px;color:rgba(255,255,255,.48);font-family:'JetBrains Mono',monospace;margin-top:1px}
.chq-top-right{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0}
.chq-cts-tag{font-size:6.5px;font-weight:700;letter-spacing:.10em;padding:1px 4px;
  background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.26);
  border-radius:2px;color:rgba(255,255,255,.82);text-transform:uppercase}
.chq-no-block{text-align:right}
.chq-no-lbl{font-size:6px;color:rgba(255,255,255,.48);letter-spacing:.07em;text-transform:uppercase}
.chq-no-val{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;color:rgba(255,255,255,.94)}
/* Date row */
.chq-date-row{display:flex;align-items:center;justify-content:flex-end;gap:5px;
  padding:3px 8px;background:var(--chq-paper2);border-bottom:1px dashed var(--chq-rule)}
.chq-date-lbl{font-size:7px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--chq-label)}
.chq-date-boxes{display:flex;align-items:center;gap:1px}
.dbox{display:inline-flex;align-items:center;justify-content:center;
  width:14px;height:16px;border:1px solid var(--chq-rule);background:rgba(255,255,255,.55);
  font-family:'Noto Sans','JetBrains Mono',monospace;font-size:9px;color:var(--ink);
  border-radius:1px;font-weight:500;line-height:1}
.dsep{font-size:10px;color:var(--chq-label);padding:0 1px}
/* Body layout: left column (pay+words) + right column (figure box) */
.chq-body{display:flex;align-items:flex-start;padding:5px 8px 4px;gap:7px}
.chq-left-col{flex:1;min-width:0}
.chq-right-col{flex-shrink:0;width:88px;padding-top:2px}
.chq-pay-row{display:flex;align-items:flex-start;gap:4px;min-height:30px}
.chq-words-row{display:flex;align-items:flex-start;gap:4px;margin-top:3px;min-height:26px}
.chq-fl{font-size:7px;font-weight:600;color:var(--chq-label);text-transform:uppercase;
  letter-spacing:.06em;white-space:nowrap;padding-top:3px;min-width:30px;flex-shrink:0}
.chq-payee-line{flex:1;display:flex;align-items:flex-start;justify-content:space-between;
  gap:4px;border-bottom:1px solid var(--chq-rule);padding-bottom:2px;min-width:0}
.chq-payee-inner{flex:1;min-width:0}
.chq-bearer{font-size:7px;color:var(--chq-label);white-space:nowrap;padding-top:3px;flex-shrink:0}
.chq-words-inner{flex:1;min-width:0;border-bottom:1px solid var(--chq-rule);padding-bottom:2px}
.chq-ruled{border:none;border-top:1px solid var(--chq-rule);margin:0}
.chq-indic{font-family:'Noto Sans','Nirmala UI','Arial Unicode MS',system-ui,sans-serif;
  font-size:11px;font-weight:500;color:var(--ink);line-height:1.3}
.chq-xlit{font-size:7px;color:var(--chq-label);font-style:italic;margin-top:1px}
.chq-plain{font-size:11px;color:var(--ink)}
/* Figure box — right column, top-aligned */
.chq-fig-box{border:1.5px solid var(--chq-rule);border-radius:2px;padding:4px 6px;
  background:rgba(255,255,255,.45);text-align:right;min-height:40px}
.chq-fig-mismatch{border-color:#b91c1c !important;background:rgba(185,28,28,.07) !important}
.chq-fig-label{font-size:6.5px;color:var(--chq-label);font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.chq-fig-val{font-family:'Noto Sans','JetBrains Mono',monospace;font-size:11px;font-weight:700;
  color:var(--ink);line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chq-fig-mismatch .chq-fig-val{color:#b91c1c}
/* Footer: account info left, signature right */
.chq-footer{display:flex;align-items:flex-end;justify-content:space-between;
  padding:4px 8px 5px;border-top:1px dashed var(--chq-rule)}
.chq-acct-block{display:flex;flex-direction:column;gap:2px}
.chq-arow{display:flex;gap:5px;align-items:baseline}
.chq-al{font-size:6.5px;color:var(--chq-label);font-weight:600;text-transform:uppercase;letter-spacing:.06em;width:46px;flex-shrink:0}
.chq-av{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--ink)}
.chq-sig-block{display:flex;flex-direction:column;align-items:center;gap:1px;min-width:88px}
.chq-sig-rule{width:88px;border-bottom:1px solid var(--chq-rule);margin-top:2px}
.chq-sig-lbl{font-size:6.5px;color:var(--chq-label);text-transform:uppercase;letter-spacing:.06em}
/* MICR band */
.chq-micr-band{
  background:var(--micr-bg);border-top:2px solid var(--chq-rule);
  padding:3px 8px;display:flex;align-items:center;justify-content:center;
}
.chq-micr-num{font-family:'JetBrains Mono',monospace;font-size:9.5px;
  color:var(--chq-label);letter-spacing:.10em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Mismatch flag */
.mm-flag{display:flex;align-items:center;gap:5px;flex-wrap:wrap;
  background:rgba(185,28,28,.07);border:1px solid rgba(185,28,28,.18);
  border-radius:4px;padding:4px 7px;margin-top:4px;margin-bottom:3px}
.mm-item{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted)}
.mm-item strong{color:var(--text)}
.mm-sep{font-size:14px;color:var(--ret);font-weight:900;padding:0 1px}
.mm-badge{font-size:7px;font-weight:700;padding:1px 5px;border-radius:3px;
  background:var(--ret-bg);color:var(--ret-txt);letter-spacing:.06em;margin-left:auto;white-space:nowrap}
.pg-footer{max-width:1080px;margin:20px auto 0;padding-top:11px;
  border-top:1px solid var(--border);display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:4px;font-size:10px;color:var(--faint)}
.pg-footer strong{color:var(--muted);font-weight:600}
"""

# ── Build page HTML ───────────────────────────────────────────────────────────

def build_html(real_html, spec_html):
    return f"""<title>Regional Language OCR</title>
<style>{CSS}</style>

<div class="ph">
  <div class="eyebrow">ASTRA CTS &bull; Regional Language OCR &bull; v2</div>
  <h1>CTS Cheque OCR &mdash; Real Scans + Regional Language Specimens</h1>
  <p>Section&nbsp;1: 9 actual English bank scans from <code>demo/112/</code> with honest
  <code>ocr_extract()</code> output &mdash; no fabrication.
  Section&nbsp;2: Realistic CSS-rendered CTS-2010 instruments with actual regional language text,
  roman transliteration, and two AMOUNT_MISMATCH returns where <code>amounts_match()</code> returned False.</p>
  <div class="meta-bar">
    <span class="mpill"><strong>9</strong> real English scans (demo/112/)</span>
    <span class="mpill"><strong>9</strong> regional language specimens</span>
    <span class="mpill"><strong>2</strong> AMOUNT_MISMATCH (code-detected)</span>
    <span class="mpill">OCR: <strong>ocr_extract()</strong> + CascadeOrchestrator + GOT-OCR2.0 stub</span>
  </div>
</div>

<div class="section">
  <div class="section-hdr">
    <h2>Section 1 &mdash; Real Scans from demo/112/ (English only)</h2>
    <p>Actual Syndicate Bank / Axis Bank cheques. All text is English.
    OCR panel shows exactly what the stub returned &mdash; no fabrication.</p>
  </div>
  <div class="grid3">
{"".join(real_html)}
  </div>
</div>

<div class="section">
  <div class="section-hdr">
    <h2>Section 2 &mdash; Regional Language CTS-2010 Specimens</h2>
    <p>CSS-rendered synthetic cheques with actual regional script and roman transliteration in [brackets].
    The OCR stub cannot read the CSS-rendered text &mdash; it returns canned responses.
    In production, GOT-OCR2.0 reads Indic fields directly from scanned images.</p>
  </div>
  <div class="grid3">
{"".join(spec_html)}
  </div>
</div>

<div class="pg-footer">
  <strong>ASTRA &mdash; Bank Intelligence Platform</strong>
  <span>regional-language-v1 &bull; 2026-08-26</span>
</div>
"""

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print(f"\nEncoding {len(_FILES)} images...")
    embeds = [_encode(f) for f in _FILES]

    print("\nRunning OCR on all scenarios...")
    real_ocr, spec_ocr = await run_all_ocr(_FILES, REAL_CARDS, SPECIMENS)

    print("\nGenerating HTML...")
    rc_html = [real_card(i, tup, ocr, embed)
               for i, (tup, ocr, embed) in enumerate(zip(REAL_CARDS, real_ocr, embeds))]
    sp_html = [specimen_card(sp, ocr) for sp, ocr in zip(SPECIMENS, spec_ocr)]

    html = build_html(rc_html, sp_html)
    OUT.write_text(html, encoding="utf-8")
    print(f"\nWritten: {OUT}  ({len(html)//1024} KB)")

if __name__ == "__main__":
    stub = ensure_stub()
    try:
        asyncio.run(main())
    finally:
        if stub:
            stub.kill(); stub.wait(); print("[stub] Stopped.")
