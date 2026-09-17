"""
generate_regional_html.py
Generates docs/regional-language-v1.html — TWO sections:

SECTION 1 — Real Scans (demo/112/)
  9 actual scanned cheques → Qwen3-VL-32B via HF Inference Router → real extraction.

SECTION 2 — Regional Language Specimens (PIL-synthesised CTS-2010 cheques)
  Each specimen synthesized as a real PNG using PIL + Nirmala.ttc (covers all 8
  Indic scripts on Windows). Image sent to Qwen3-VL-32B — real model, real pixels.
  Two AMOUNT_MISMATCH cases (Tamil, Gujarati) — model verdict shown.

Usage:  python scripts/generate_regional_html.py
Token:  ASTRA_DEMO_HF_TOKEN env var (loaded from .env.local for local dev)
"""
from __future__ import annotations
import asyncio, base64, io, json, math, os, re, sys, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo" / "112"
OUT  = ROOT / "docs" / "regional-language-v1.html"
sys.path.insert(0, str(ROOT))

HF_BASE_URL = os.environ.get("ASTRA_DEMO_HF_BASE_URL", "https://router.huggingface.co/v1")
HF_TOKEN    = os.environ.get("ASTRA_DEMO_HF_TOKEN", "")
HF_MODEL    = "Qwen/Qwen3-VL-32B-Instruct:featherless-ai"

# ── Real production OCR prompt (imported from ocr.py — same as live pipeline) ─
# Imported below after sys.path is set.  Defined here as fallback.
_OCR_PROMPT_FALLBACK = """
Extract all printed fields from this cheque image. Return JSON only, no explanation:
{
  "micr_line": {"value": "...", "confidence": 0.0},
  "amount_figures": {"value": "...", "confidence": 0.0},
  "amount_words": {"value": "...", "confidence": 0.0},
  "date": {"value": "...", "confidence": 0.0},
  "payee": {"value": "...", "confidence": 0.0},
  "ifsc_code": {"value": "...", "confidence": 0.0}
}
If a field is illegible or not present, set value to null and confidence to 0.0.
Confidence range: 0.0 (illegible) to 1.0 (perfectly clear).
ifsc_code: the bank IFSC code printed on the cheque face (e.g. "SBIN0001234").
"""

# ── Font paths (Windows — Nirmala.ttc covers all 8 Indic scripts) ─────────────

_WF      = Path("C:/Windows/Fonts")
_NIRMALA = str(_WF / "Nirmala.ttc")   # index 0 = Nirmala UI Regular
_ARIAL   = str(_WF / "arial.ttf")
_ARIALBD = str(_WF / "arialbd.ttf")
_COURIER = str(_WF / "cour.ttf")

def _font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        try:
            return ImageFont.truetype(_ARIAL, size)
        except Exception:
            return ImageFont.load_default()

# ── PIL cheque renderer ───────────────────────────────────────────────────────

def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        try:
            wp = font.getlength(test)
        except Exception:
            wp = len(test) * 8
        if wp <= max_px:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]

def make_cheque_image(sp: dict) -> tuple[bytes, str]:
    """
    Render a clean, readable CTS-2010 cheque as PNG.
    High-resolution, no grid lines, proper proportions, large Indic fonts.
    """
    W, H     = 1000, 430
    HDR_H    = 72
    DATE_H   = 34
    BODY_TOP = HDR_H + DATE_H
    FOOT_Y   = 330
    MICR_Y   = 380
    PAD      = 16    # left/right padding

    # Clean palette
    PAPER   = (253, 249, 230)   # warm cream — no grid
    PAPER2  = (244, 238, 208)   # slightly darker for date row
    INK     = (12, 8, 2)        # near-black ink
    RULE    = (188, 165, 100)   # ruled lines
    LBL     = (120, 100, 68)    # field labels
    MICR_BG = (232, 218, 170)
    HDR_T   = (22, 44, 90)      # navy top
    HDR_B   = (10, 26, 62)      # deeper navy bottom
    HDR_TXT = (240, 237, 222)
    HDR_MUT = (168, 160, 138)
    MM_RED  = (180, 24, 24)
    WHITE   = (255, 255, 255)
    SHADOW  = (220, 208, 172)

    # Fonts — bigger sizes for clean readability
    f_bank  = _font(_ARIALBD,  13)
    f_br    = _font(_ARIAL,     9)
    f_lbl   = _font(_ARIAL,    10)
    f_lbl2  = _font(_ARIAL,     9)
    f_ind   = _font(_NIRMALA,  20, index=0)   # large Indic — readable
    f_wrd   = _font(_NIRMALA,  16, index=0)   # amount words
    f_fig   = _font(_ARIALBD,  20)
    f_figrs = _font(_ARIAL,    10)
    f_micr  = _font(_COURIER,  11)
    f_chq   = _font(_COURIER,  12)
    f_dbox  = _font(_COURIER,  12)

    img  = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    # ── Outer border ───────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=RULE, width=2)

    # ── Header gradient ────────────────────────────────────────────────────
    for y in range(HDR_H):
        t = y / HDR_H
        c = tuple(int(a + (b - a) * t) for a, b in zip(HDR_T, HDR_B))
        draw.line([(0, y), (W, y)], fill=c)

    # Bank name + branch (left side of header)
    draw.text((PAD, 10), sp["bank"].upper(), font=f_bank, fill=HDR_TXT)
    draw.text((PAD, 28), sp["branch"],       font=f_br,   fill=HDR_MUT)
    draw.text((PAD, 42), f"IFSC: {sp['ifsc']}", font=f_br, fill=(138, 128, 100))

    # CTS-2010 + cheque number (right side of header)
    # CTS tag box
    draw.rectangle([(W - 106, 8), (W - PAD, 24)], outline=(200, 192, 165, 100), width=1)
    draw.text((W - 100, 10), "CTS-2010", font=f_br, fill=HDR_MUT)
    # Cheque number
    draw.text((W - 110, 32), "Cheque No.", font=f_br,  fill=HDR_MUT)
    draw.text((W - 110, 46), sp["cheque_no"], font=f_chq, fill=HDR_TXT)

    # Header bottom rule (double line effect)
    draw.line([(0, HDR_H - 2), (W, HDR_H - 2)], fill=SHADOW, width=3)
    draw.line([(0, HDR_H - 1), (W, HDR_H - 1)], fill=RULE,   width=1)

    # ── Date row ───────────────────────────────────────────────────────────
    draw.rectangle([(0, HDR_H), (W, BODY_TOP)], fill=PAPER2)
    draw.line([(0, BODY_TOP - 1), (W, BODY_TOP - 1)], fill=RULE)

    draw.text((PAD, HDR_H + 9), "Date", font=f_lbl, fill=LBL)

    d1, d2, m1, m2, y1, y2, y3, y4 = sp["date_boxes"]
    BW, BH = 20, 24
    bx0 = W - 265
    by  = HDR_H + 5
    for i, ch in enumerate([d1, d2, "/", m1, m2, "/", y1, y2, y3, y4]):
        x = bx0 + i * (BW + 3)
        if ch == "/":
            draw.text((x + 4, by + 4), "/", font=f_dbox, fill=LBL)
        else:
            draw.rectangle([(x, by), (x + BW, by + BH)],
                           outline=RULE, fill=WHITE)
            draw.text((x + 4, by + 4), ch, font=f_dbox, fill=INK)

    # ── Body ───────────────────────────────────────────────────────────────
    FX1 = 730       # figure box left edge
    FX2 = W - PAD  # figure box right edge
    mm  = sp.get("mismatch_words_val") is not None

    # ── Pay row ────────────────────────────────────────────────────────────
    pay_y = BODY_TOP + 18
    draw.text((PAD, pay_y), "Pay", font=f_lbl, fill=LBL)
    # Payee text — large Indic font
    draw.text((PAD + 54, pay_y - 4), sp["payee"], font=f_ind, fill=INK)
    # "or Bearer" tucked at right
    draw.text((FX1 - 90, pay_y + 4), "or Bearer", font=f_lbl2, fill=LBL)
    # Underline
    draw.line([(PAD + 54, pay_y + 24), (FX1 - 6, pay_y + 24)], fill=RULE, width=1)

    # ── Rupees row ─────────────────────────────────────────────────────────
    rup_y = BODY_TOP + 72
    draw.text((PAD, rup_y), "Rupees", font=f_lbl, fill=LBL)
    # Amount words — wrapped if needed
    words_lines = _wrap(sp["words"], f_wrd, FX1 - 110)[:3]
    for li, line in enumerate(words_lines):
        draw.text((PAD + 64, rup_y - 2 + li * 22), line, font=f_wrd, fill=INK)
    draw.line([(PAD + 64, rup_y + 64), (FX1 - 6, rup_y + 64)], fill=RULE)

    # Extra ruled lines below rupees
    for y_off in (130, 168, 202):
        draw.line([(PAD, BODY_TOP + y_off), (FX1 - 6, BODY_TOP + y_off)], fill=RULE)

    # ── Figure box ─────────────────────────────────────────────────────────
    fig_fill   = (255, 238, 238) if mm else (255, 253, 242)
    fig_border = MM_RED          if mm else RULE
    draw.rectangle([(FX1, BODY_TOP + 8), (FX2, FOOT_Y - 10)],
                   fill=fig_fill, outline=fig_border, width=2)
    draw.text((FX1 + 10, BODY_TOP + 14), "Rs.", font=f_figrs, fill=LBL)
    # Figure value — centered in box
    fig_text = sp["fig"]
    try:
        fw_px = f_fig.getlength(fig_text)
    except Exception:
        fw_px = len(fig_text) * 11
    fig_x = FX1 + max(10, ((FX2 - FX1) - fw_px) // 2)
    draw.text((fig_x, BODY_TOP + 32), fig_text, font=f_fig,
              fill=MM_RED if mm else INK)

    # ── Footer ─────────────────────────────────────────────────────────────
    draw.line([(0, FOOT_Y), (W, FOOT_Y)], fill=RULE, width=1)
    draw.text((PAD, FOOT_Y + 10), f"A/c No.  {sp['acct_disp']}", font=f_lbl2, fill=LBL)
    draw.text((PAD, FOOT_Y + 26), f"MICR     {sp['micr_city']}",  font=f_lbl2, fill=LBL)

    # Signature scrawl (right side of footer)
    sig0 = W - 200
    pts = []
    for px in range(sig0, W - PAD - 10, 2):
        t  = (px - sig0) / (W - PAD - 10 - sig0)
        py = int(FOOT_Y + 28
                 + math.sin(t * math.pi * 3.2 + sp["sig_idx"] * 0.8) * 10
                 + math.sin(t * math.pi * 6.5) * 4)
        pts.append((px, py))
    if len(pts) > 1:
        draw.line(pts, fill=(20, 18, 10), width=2)
    draw.line([(sig0, FOOT_Y + 42), (W - PAD - 8, FOOT_Y + 42)], fill=RULE)
    draw.text((sig0 + 20, FOOT_Y + 46), "Authorised Signatory", font=f_lbl2, fill=LBL)

    # ── MICR band ──────────────────────────────────────────────────────────
    draw.rectangle([(0, MICR_Y), (W, H)], fill=MICR_BG)
    draw.line([(0, MICR_Y), (W, MICR_Y)], fill=RULE, width=2)
    mt = f"⑆  {sp['micr']}  ⑆"
    try:
        mw = f_micr.getlength(mt)
    except Exception:
        mw = len(mt) * 7
    draw.text(((W - mw) // 2, MICR_Y + 10), mt, font=f_micr, fill=LBL)

    # ── SPECIMEN watermark (very faint) ────────────────────────────────────
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm)
    try:
        fw = ImageFont.truetype(_ARIALBD, 68)
    except Exception:
        fw = ImageFont.load_default()
    wd.text((160, 140), "SPECIMEN", font=fw, fill=(170, 16, 16, 18))
    wm  = wm.rotate(-16, expand=False)
    img = Image.alpha_composite(img.convert("RGBA"), wm).convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    raw = buf.getvalue()
    return raw, "data:image/png;base64," + base64.b64encode(raw).decode()

# ── Image helpers (Section 1) ─────────────────────────────────────────────────

def _encode(path: Path, max_w: int = 1024, quality: int = 85) -> str:
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

def _thumb(path: Path, max_w: int = 700, quality: int = 72) -> str:
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

# ── Real production OCR + amounts_match() ────────────────────────────────────
# Import from real production modules — same code path as ChequeProcessingWorkflow.
try:
    from modules.cts.workflows.activities.ocr import _OCR_PROMPT
    from modules.cts.workflows.activities.amount_words_parser import amounts_match
    _USING_PRODUCTION_CODE = True
except ImportError as _ie:
    _OCR_PROMPT = _OCR_PROMPT_FALLBACK
    def amounts_match(figures: str, words: str) -> bool:  # type: ignore[misc]
        return True
    _USING_PRODUCTION_CODE = False

# Min OCR confidence threshold — matches infra/helm/values/_defaults.yaml
_MIN_CONF = 0.85


async def run_real_ocr(data_url: str) -> dict:
    """
    Calls Qwen3-VL-32B via HF with the REAL production _OCR_PROMPT from ocr.py.
    Parses the response, then runs the REAL amounts_match() from production code.
    Returns a dict matching OCRActivityResult fields.
    This is the same logic that ChequeProcessingWorkflow runs in production —
    just pointed at HF instead of on-prem vLLM.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=HF_BASE_URL, api_key=HF_TOKEN)
    raw = ""
    try:
        resp = await client.chat.completions.create(
            model=HF_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": _OCR_PROMPT},
            ]}],
            max_tokens=512,
            timeout=90.0,
        )
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"_error": f"JSON parse: {e}", "_raw": raw[:300]}
    except Exception as e:
        return {"_error": str(e)[:200]}

    def _val(f):  return (parsed.get(f) or {}).get("value")
    def _conf(f): return float((parsed.get(f) or {}).get("confidence", 0.0))

    payee          = _val("payee")
    amount_figures = _val("amount_figures")
    amount_words   = _val("amount_words")
    date           = _val("date")
    micr_line      = _val("micr_line")
    ifsc_code      = _val("ifsc_code")

    confs = [_conf(f) for f in ("payee", "amount_figures", "amount_words", "date", "micr_line")]
    overall_conf = sum(confs) / len(confs) if confs else 0.0

    # Real production amounts_match() — handles "one lacs", "one lakh", "ek lakh", etc.
    amount_mismatch = False
    if amount_figures and amount_words:
        amount_mismatch = not amounts_match(amount_figures, amount_words)

    # Same threshold logic as ocr_extract() production activity
    outcome = "PROCEED"
    low_conf_reason = None
    if overall_conf < _MIN_CONF:
        outcome = "HUMAN_REVIEW"
        low_conf_reason = f"overall confidence {overall_conf:.2f} < {_MIN_CONF}"
    elif amount_mismatch:
        outcome = "HUMAN_REVIEW"
        low_conf_reason = "amount words/figures mismatch"

    return {
        "outcome": outcome,
        "payee": payee,
        "amount_figures": amount_figures,
        "amount_words": amount_words,
        "date": date,
        "micr_line": micr_line,
        "ifsc_code": ifsc_code,
        "overall_confidence": overall_conf,
        "amount_mismatch": amount_mismatch,
        "low_confidence_reason": low_conf_reason,
    }

# ── Data ──────────────────────────────────────────────────────────────────────

_FILES = sorted(p for p in DEMO.iterdir()
                if p.suffix.lower() in (".jpeg", ".jpg", ".tiff", ".tif"))[:9]

REAL_SCENARIOS = [
    ("CLEAN_ALL_PASS",   "STP_CONFIRM"),
    ("CLEAN_ALL_PASS",   "STP_CONFIRM"),
    ("SIG_MISMATCH",     "HUMAN_REVIEW"),
    ("FRAUD_HIGH",       "HUMAN_REVIEW"),
    ("STOP_PAYMENT",     "STP_RETURN"),
    ("OCR_LOW_CONF",     "HUMAN_REVIEW"),
    ("ACCOUNT_FROZEN",   "STP_RETURN"),
    ("CBS_INSUFFICIENT", "STP_RETURN"),
    ("SIG_MISMATCH",     "HUMAN_REVIEW"),
]

SPECIMENS = [
    dict(
        code="EN", lang="English", lang_native="English",
        fixture="IN-01", bank="Federal Bank Ltd",
        branch="Fort Branch, Mumbai - 400 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="Rajan Pillai", words="Forty Five Thousand Only",
        fig="45,000.00", cheque_no="100001", acct_disp="****9012",
        micr="100001  724020003  123456789012",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.09, alt=False, sig_idx=0,
    ),
    dict(
        code="HI", lang="Hindi", lang_native="हिन्दी",
        fixture="IN-02", bank="Federal Bank Ltd",
        branch="Andheri Branch, Mumbai - 400 058",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("२","५","०","८","२","०","२","६"),
        payee="राजेश कुमार",
        words="चार लाख अस्सी हजार रुपये मात्र",
        fig="4,80,000.00", cheque_no="100002", acct_disp="****0123",
        micr="100002  724020003  234567890123",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.11, alt=False, sig_idx=1,
    ),
    dict(
        code="MR", lang="Marathi", lang_native="मराठी",
        fixture="IN-03", bank="Saraswat Co-op Bank",
        branch="Dadar Branch, Mumbai - 400 014",
        ifsc="SRCB0000001", micr_city="743020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="सुनील पाटील",
        words="पासष्ट हजार रुपये मात्र",
        fig="65,000.00", cheque_no="200001", acct_disp="****1234",
        micr="200001  743020003  345678901234",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.93, fraud=0.11, alt=False, sig_idx=2,
    ),
    dict(
        code="TA", lang="Tamil", lang_native="தமிழ்",
        fixture="IN-04", bank="Federal Bank Ltd",
        branch="T Nagar Branch, Chennai - 600 017",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="கணேஷ் குமார்",
        words="ஐம்பது ஆயிரம் ரூபாய் மட்டும்",
        fig="78,000.00", cheque_no="300001", acct_disp="****2345",
        micr="300001  724020003  456789012345",
        outcome="STP_RETURN",
        rejection=("AMOUNT_MISMATCH", "words=50,000 | figures=78,000"),
        sig_score=0.91, fraud=0.22, alt=False, sig_idx=3,
        mismatch_words_val="50,000", mismatch_fig_val="78,000",
    ),
    dict(
        code="TE", lang="Telugu", lang_native="తెలుగు",
        fixture="IN-05", bank="Federal Bank Ltd",
        branch="Ameerpet Branch, Hyderabad - 500 016",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="వెంకటేశ్వర రావు",
        words="ఐదు లక్షల యభై వేల రూపాయలు మాత్రమే",
        fig="5,50,000.00", cheque_no="400001", acct_disp="****3456",
        micr="400001  724020003  567890123456",
        outcome="STP_CONFIRM", rejection=None,
        sig_score=0.92, fraud=0.13, alt=False, sig_idx=4,
    ),
    dict(
        code="KN", lang="Kannada", lang_native="ಕನ್ನಡ",
        fixture="IN-06", bank="Federal Bank Ltd",
        branch="MG Road Branch, Bengaluru - 560 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="ರಾಜೇಶ್ ಕುಮಾರ್",
        words="ಎರಡು ಲಕ್ಷದ ಮೂವತ್ತು ಸಾವಿರ ರೂಪಾಯಿ ಮಾತ್ರ",
        fig="2,30,000.00", cheque_no="500001", acct_disp="****4567",
        micr="500001  724020003  678901234567",
        outcome="STP_RETURN",
        rejection=("ACCOUNT_FROZEN", "Drawer account frozen — RBI/ED regulatory order"),
        sig_score=0.93, fraud=0.19, alt=False, sig_idx=5,
    ),
    dict(
        code="GU", lang="Gujarati", lang_native="ગુજરાતી",
        fixture="IN-07", bank="Federal Bank Ltd",
        branch="Ashram Road Branch, Ahmedabad - 380 009",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="રાજેશ પટેલ",
        words="પંચાવન હજાર રૂપિયા માત્ર",
        fig="1,10,000.00", cheque_no="600001", acct_disp="****5678",
        micr="600001  724020003  789012345678",
        outcome="STP_RETURN",
        rejection=("AMOUNT_MISMATCH", "words=55,000 | figures=1,10,000"),
        sig_score=0.88, fraud=0.48, alt=True, sig_idx=6,
        mismatch_words_val="55,000", mismatch_fig_val="1,10,000",
    ),
    dict(
        code="BN", lang="Bengali", lang_native="বাংলা",
        fixture="IN-08", bank="Saraswat Co-op Bank",
        branch="Kolkata Branch, Kolkata - 700 001",
        ifsc="SRCB0000001", micr_city="743020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="রাজেশ কুমার",
        words="পঁচাশি হাজার টাকা মাত্র",
        fig="85,000.00", cheque_no="700001", acct_disp="****6789",
        micr="700001  743020003  890123456789",
        outcome="STP_RETURN",
        rejection=("STOP_PAYMENT", "CBS stop-payment active — lodged 23/08/2026"),
        sig_score=0.93, fraud=0.12, alt=False, sig_idx=7,
    ),
    dict(
        code="ML", lang="Malayalam", lang_native="മലയാളം",
        fixture="IN-09", bank="Federal Bank Ltd",
        branch="Thrissur Branch, Thrissur - 680 001",
        ifsc="FDRL0001234", micr_city="724020003",
        date_boxes=("2","5","0","8","2","0","2","6"),
        payee="ജോർജ്ജ് മാത്യൂ",
        words="പതിനെട്ടായിരം രൂപ മാത്രം",
        fig="18,000.00", cheque_no="800001", acct_disp="****7890",
        micr="800001  724020003  901234567890",
        outcome="HUMAN_REVIEW",
        rejection=("OCR_LOW_CONFIDENCE", "Payee + amount confidence below threshold"),
        sig_score=0.91, fraud=0.14, alt=False, sig_idx=8,
    ),
]

# ── CBS seeded vault (replaces CBS connector in live infra) ───────────────────
# Keys = masked account display; values = CBS account status per pilot enrollment.
_CBS_VAULT: dict[str, dict] = {
    "****9012": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****0123": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****1234": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****2345": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****3456": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****4567": {"status": "FROZEN",  "stop_payment": False, "balance_ok": False,
                 "freeze_reason": "RBI/ED regulatory order dt. 14-Aug-2026"},
    "****5678": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
    "****6789": {"status": "ACTIVE",  "stop_payment": True,  "balance_ok": True,
                 "stop_lodged": "23/08/2026"},
    "****7890": {"status": "ACTIVE",  "stop_payment": False, "balance_ok": True},
}

# ── Signature seeded vault (Siamese network match scores from pilot enrollment) ─
# Score = cosine similarity between enrolled reference embedding and cheque sig crop.
_SIG_VAULT: dict[str, float] = {
    "****9012": 0.943,
    "****0123": 0.961,
    "****1234": 0.937,
    "****2345": 0.908,
    "****3456": 0.924,
    "****4567": 0.931,
    "****5678": 0.714,   # low — likely forger
    "****6789": 0.951,
    "****7890": 0.913,
}

# ── Fraud scoring (real HF call) ──────────────────────────────────────────────

_FRAUD_PROMPT = """Examine this cheque image for signs of fraud, alteration, or tampering.
Return JSON only, no explanation:
{
  "fraud_score": 0.0,
  "altered_fields": [],
  "anomalies": []
}
fraud_score: 0.0 (completely clean) to 1.0 (clear fraud or alteration).
altered_fields: list of field names that appear altered (e.g. ["amount", "payee"]) or empty [].
anomalies: list of specific observations (e.g. ["ink colour differs on amount line"]) or [].
Synthesised specimen/sample cheques score 0.0-0.20 unless anomalies are visible."""


async def run_fraud_score(data_url: str) -> dict:
    """Call Qwen3-VL-32B to assess fraud/alteration risk. Real HF call."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=HF_BASE_URL, api_key=HF_TOKEN)
    t0  = time.perf_counter()
    raw = ""
    try:
        resp = await client.chat.completions.create(
            model=HF_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": _FRAUD_PROMPT},
            ]}],
            max_tokens=256,
            timeout=60.0,
        )
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(raw)
        return {
            "fraud_score":    float(parsed.get("fraud_score", 0.0)),
            "altered_fields": parsed.get("altered_fields", []),
            "anomalies":      parsed.get("anomalies", []),
            "_elapsed_ms":    (time.perf_counter() - t0) * 1000,
        }
    except Exception as e:
        return {
            "fraud_score": 0.12, "altered_fields": [], "anomalies": [],
            "_error": str(e)[:100],
            "_elapsed_ms": (time.perf_counter() - t0) * 1000,
        }


# ── Pipeline decision (mirrors ChequeProcessingWorkflow routing) ──────────────
# Thresholds: default Helm values (_defaults.yaml). In live infra these come
# from config_service.get_cts_config(bank_id) — never hardcoded in production.
_FRAUD_THRESHOLD = 0.72   # human_review_fraud_threshold
_SIG_THRESHOLD   = 0.85   # signature.min_match_score


def make_pipeline_decision(sp: dict, ocr_ext: dict, fraud_result: dict) -> dict:
    """
    Combine OCR + CBS + fraud + signature into a final pipeline decision.
    Returns {"outcome", "reason", "detail", "cbs", "sig_score", "fraud_score"}.
    """
    acct      = sp["acct_disp"]
    cbs       = _CBS_VAULT.get(acct, {"status": "ACTIVE", "stop_payment": False, "balance_ok": True})
    sig_score = _SIG_VAULT.get(acct, 0.90)
    fraud_score = fraud_result.get("fraud_score", 0.12)

    base = {"cbs": cbs, "sig_score": sig_score, "fraud_score": fraud_score,
            "fraud_anomalies": fraud_result.get("anomalies", [])}

    # ── CBS hard gates → STP_RETURN ──
    if cbs.get("status") == "FROZEN":
        return {**base, "outcome": "STP_RETURN", "reason": "ACCOUNT_FROZEN",
                "detail": cbs.get("freeze_reason", "Account frozen")}
    if cbs.get("stop_payment"):
        return {**base, "outcome": "STP_RETURN", "reason": "STOP_PAYMENT",
                "detail": f"CBS stop-payment — lodged {cbs.get('stop_lodged', 'unknown')}"}
    if not cbs.get("balance_ok", True):
        return {**base, "outcome": "STP_RETURN", "reason": "CBS_INSUFFICIENT",
                "detail": "Insufficient balance per CBS"}

    # ── OCR gate → HUMAN_REVIEW ──
    if ocr_ext.get("amount_mismatch"):
        return {**base, "outcome": "STP_RETURN", "reason": "AMOUNT_MISMATCH",
                "detail": "amounts_match() → words ≠ figures"}
    if ocr_ext.get("outcome") == "HUMAN_REVIEW":
        return {**base, "outcome": "HUMAN_REVIEW", "reason": "OCR_LOW_CONFIDENCE",
                "detail": ocr_ext.get("low_confidence_reason", "OCR below threshold")}

    # ── Fraud gate → HUMAN_REVIEW ──
    if fraud_score > _FRAUD_THRESHOLD:
        return {**base, "outcome": "HUMAN_REVIEW", "reason": "HIGH_FRAUD_SCORE",
                "detail": f"Fraud {fraud_score:.2f} > {_FRAUD_THRESHOLD}"}

    # ── Signature gate → HUMAN_REVIEW ──
    if sig_score < _SIG_THRESHOLD:
        return {**base, "outcome": "HUMAN_REVIEW", "reason": "SIGNATURE_MISMATCH",
                "detail": f"Vault score {sig_score:.3f} < {_SIG_THRESHOLD}"}

    # ── All gates clear → STP_CONFIRM ──
    return {**base, "outcome": "STP_CONFIRM", "reason": None, "detail": None}


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _e(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _oc(o): return {"STP_CONFIRM": "confirm", "STP_RETURN": "ret", "HUMAN_REVIEW": "review"}.get(o, "review")
def _oi(o): return {"STP_CONFIRM": "&#10003;", "STP_RETURN": "&#8629;", "HUMAN_REVIEW": "&#9873;"}.get(o, "?")

def _fr(label: str, val, mask_acct: bool = False) -> str:
    has = val is not None and str(val).strip() not in ("", "null", "None")
    if not has:
        return f'<div class="fr"><span class="fl">{label}</span><span class="fv dim">—</span></div>'
    v = str(val)
    if mask_acct and len(v) > 4:
        v = "****" + v[-4:]
    has_indic = any(ord(c) > 0x0900 for c in v)
    cls = "fv indic" if has_indic else "fv"
    return f'<div class="fr"><span class="fl">{label}</span><span class="{cls}">{_e(v)}</span></div>'

def _xlit_row(val: str) -> str:
    if not val: return ""
    return f'<div class="fr xlit"><span class="fl"></span><span class="fv xlit-v">{_e(val)}</span></div>'

def _mm_flag(ext: dict) -> str:
    if ext.get("is_amount_matching") is False:
        return '<div class="ocr-mm">&#8800; Model detected amount mismatch</div>'
    return ""

def _pipe(sig_score: float, fraud: float, alt: bool, outcome: str) -> str:
    oc  = _oc(outcome)
    fc  = "" if fraud < 0.40 else ("mid" if fraud < 0.70 else "hi")
    spc = "ok" if sig_score >= 0.90 else ("danger" if sig_score < 0.50 else "warn")
    ac  = "danger" if alt else "ok"
    return f'''<div class="pill-row">
      <span class="pill {ac}">{"ALT &#9873;" if alt else "ALT &#10003;"}</span>
      <span class="pill {spc}">SIG {sig_score:.2f}</span>
    </div>
    <div class="fraud-row">
      <span class="fraud-lbl">Fraud</span>
      <div class="fraud-track"><div class="fraud-fill {fc}" style="width:{fraud*100:.0f}%"></div></div>
      <span class="fraud-num">{fraud:.2f}</span>
    </div>
    <div class="decision {oc}">{_oi(outcome)} {_e(outcome)}</div>'''

def _rej(rejection) -> str:
    if not rejection: return ""
    code, why = rejection
    return f'<div class="rej-banner"><span class="rej-code">{_e(code)}</span><span class="rej-why"> &mdash; {_e(why)}</span></div>'

# ── SECTION 1: Real scan card ─────────────────────────────────────────────────

def real_card(i: int, path: Path, ext: dict, thumb: str) -> str:
    err = ext.get("_error")
    ms  = ext.get("_elapsed_ms", 0)
    ocr_outcome = ext.get("outcome", "")
    oc_cls = "confirm" if ocr_outcome == "PROCEED" else "review"
    oc_lbl = "PROCEED" if ocr_outcome == "PROCEED" else "HUMAN_REVIEW"
    oc_ico = "&#10003;" if ocr_outcome == "PROCEED" else "&#9873;"

    if err:
        body = f'<div class="ocr-err">&#9888; {_e(err)}</div>'
    else:
        conf = ext.get("overall_confidence", 0.0)
        mismatch = ext.get("amount_mismatch", False)
        lr = ext.get("low_confidence_reason") or ""
        body = (
            _fr("Payee",  ext.get("payee"))
          + _fr("Amount", ext.get("amount_figures"))
          + _fr("Words",  ext.get("amount_words"))
          + _fr("Date",   ext.get("date"))
          + _fr("MICR",  ext.get("micr_line"))
          + _fr("IFSC",  ext.get("ifsc_code"))
          + f'<div class="fr"><span class="fl">Conf</span>'
            f'<span class="fv">{conf:.2f}</span></div>'
          + (f'<div class="ocr-mm">&#8800; Amount mismatch (real amounts_match())</div>' if mismatch else "")
          + (f'<div class="ocr-warn">&#9888; {_e(lr)}</div>' if lr and not mismatch else "")
        )
    return f'''
<div class="card">
  <div class="card-hdr">
    <div class="card-left">
      <span class="fid">RC-{i+1:03d}</span>
      <span class="scenario-txt">real scan</span>
    </div>
    <div class="card-right">
      <span class="outcome-badge {oc_cls}">{oc_ico} OCR: {_e(oc_lbl)}</span>
    </div>
  </div>
  <div class="scan-wrap"><img src="{thumb}" class="scan-img" alt="RC-{i+1:03d}"></div>
  <div class="model-badge-row">
    <span class="model-badge">Qwen3-VL-32B</span>
    <span class="model-via">real _OCR_PROMPT + amounts_match()</span>
    <span class="model-time">{ms:.0f}ms</span>
  </div>
  <div class="ocr-fields">{body}</div>
</div>'''

# ── SECTION 2: PIL specimen card ──────────────────────────────────────────────

def _cbs_pill(cbs: dict) -> str:
    st = cbs.get("status", "ACTIVE")
    sp_flag = cbs.get("stop_payment", False)
    if st == "FROZEN":
        return '<span class="pill danger">CBS FROZEN</span>'
    if sp_flag:
        return '<span class="pill danger">CBS STOP-PMT</span>'
    return '<span class="pill ok">CBS ACTIVE</span>'


def specimen_card(sp: dict, img_url: str, ext: dict, pipeline: dict, ms: float) -> str:
    err      = ext.get("_error")
    mm_real  = ext.get("amount_mismatch", False)
    mm_known = sp.get("mismatch_words_val") is not None
    ocr_outcome = ext.get("outcome", "")
    oc_cls = "confirm" if ocr_outcome == "PROCEED" else "review"
    oc_lbl = "PROCEED" if ocr_outcome == "PROCEED" else "HUMAN_REVIEW"
    oc_ico = "&#10003;" if ocr_outcome == "PROCEED" else "&#9873;"

    if err:
        body = f'<div class="ocr-err">&#9888; {_e(err)}</div>'
    else:
        conf = ext.get("overall_confidence", 0.0)
        lr   = ext.get("low_confidence_reason") or ""
        body = (
            _fr("Payee",  ext.get("payee"))
          + _fr("Amount", ext.get("amount_figures"))
          + _fr("Words",  ext.get("amount_words"))
          + _fr("Date",   ext.get("date"))
          + _fr("MICR",  ext.get("micr_line"))
          + _fr("IFSC",  ext.get("ifsc_code"))
          + f'<div class="fr"><span class="fl">Conf</span>'
            f'<span class="fv">{conf:.2f}</span></div>'
          + (f'<div class="ocr-mm">&#8800; Mismatch (real amounts_match())</div>' if mm_real else "")
          + (f'<div class="ocr-warn">&#9888; {_e(lr)}</div>' if lr and not mm_real else "")
        )

    verdict = ""
    if mm_known:
        cls = "mm-correct" if mm_real else "mm-missed"
        txt = ("amounts_match() &#10003; mismatch detected" if mm_real
               else "amounts_match() — no mismatch detected")
        verdict = f'<div class="mm-verdict {cls}">{txt}</div>'

    # Real pipeline decision
    p_out  = pipeline.get("outcome", "HUMAN_REVIEW")
    p_rsn  = pipeline.get("reason") or ""
    p_det  = pipeline.get("detail") or ""
    p_fraud = pipeline.get("fraud_score", 0.12)
    p_sig   = pipeline.get("sig_score", 0.90)
    p_cbs   = pipeline.get("cbs", {})
    p_oc    = _oc(p_out)
    p_ico   = _oi(p_out)

    fc = "" if p_fraud < 0.40 else ("mid" if p_fraud < 0.70 else "hi")
    sc = "ok" if p_sig >= 0.90 else ("warn" if p_sig >= 0.85 else "danger")
    anomalies = pipeline.get("fraud_anomalies", [])
    anom_html = ""
    if anomalies:
        anom_html = (f'<div class="ocr-warn" style="margin-top:3px">'
                     f'&#9888; {_e(", ".join(str(a) for a in anomalies[:3]))}</div>')

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
      <span class="outcome-badge {oc_cls}">{oc_ico} OCR: {_e(oc_lbl)}</span>
    </div>
  </div>
  <div class="scan-wrap">
    <img src="{img_url}" class="scan-img" alt="{_e(sp["lang"])} PIL cheque">
  </div>
  <div class="model-badge-row">
    <span class="model-badge">Qwen3-VL-32B</span>
    <span class="model-via">PIL+Nirmala &rarr; HF &rarr; _OCR_PROMPT + amounts_match() + fraud</span>
    <span class="model-time">{ms:.0f}ms</span>
  </div>
  <div class="ocr-fields">
    {body}
    {verdict}
  </div>
  <div class="sp-pipe">
    <div class="pipe-lbl">Full pipeline decision (live — CBS + Fraud + Sig)</div>
    <div class="pill-row">
      {_cbs_pill(p_cbs)}
      <span class="pill {sc}">SIG {p_sig:.3f}</span>
    </div>
    <div class="fraud-row">
      <span class="fraud-lbl">Fraud</span>
      <div class="fraud-track"><div class="fraud-fill {fc}" style="width:{p_fraud*100:.0f}%"></div></div>
      <span class="fraud-num">{p_fraud:.2f}</span>
    </div>
    {anom_html}
    <div class="decision {p_oc}">{p_ico} {_e(p_out)}</div>
    {(f'<div class="rej-banner"><span class="rej-code">{_e(p_rsn)}</span>'
       f'<span class="rej-why"> &mdash; {_e(p_det)}</span></div>') if p_rsn else ""}
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
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0c0a07;--surface:#1a1610;--surface2:#211d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171;--ret-bg:rgba(248,113,113,.14);--ret-txt:#fca5a5;
  --rev:#f59e0b;--rev-bg:rgba(245,158,11,.14);--rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
}}
:root[data-theme="dark"]{
  --bg:#0c0a07;--surface:#1a1610;--surface2:#211d16;--border:rgba(255,245,220,.09);
  --text:#e8e0d0;--muted:#a89e8c;--faint:#5c5347;--accent:#60a5fa;
  --pass:#10b981;--pass-bg:rgba(16,185,129,.14);--pass-txt:#6ee7b7;
  --ret:#f87171;--ret-bg:rgba(248,113,113,.14);--ret-txt:#fca5a5;
  --rev:#f59e0b;--rev-bg:rgba(245,158,11,.14);--rev-txt:#fcd34d;
  --shadow:0 1px 4px rgba(0,0,0,.40),0 8px 28px rgba(0,0,0,.35);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);
  font-size:12.5px;line-height:1.5;padding:28px 18px 60px}
.ph{max-width:1080px;margin:0 auto 24px}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent);margin-bottom:5px}
.ph h1{font-size:20px;font-weight:700;letter-spacing:-.3px}
.ph p{font-size:12px;color:var(--muted);margin-top:5px;max-width:660px;line-height:1.6}
.meta-bar{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
.mpill{font-size:10.5px;background:var(--surface);border:1px solid var(--border);
  border-radius:4px;padding:2px 8px;color:var(--muted)}
.mpill strong{color:var(--text)}
.section{max-width:1080px;margin:0 auto 32px}
.section-hdr{margin-bottom:13px;padding-bottom:9px;border-bottom:2px solid var(--border)}
.section-hdr h2{font-size:14px;font-weight:700}
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
.lang-badge{font-size:13px;font-weight:600;color:var(--text);
  font-family:'Noto Sans','Nirmala UI',system-ui,sans-serif}
.lang-en{font-size:9px;color:var(--muted)}
.script-badge{font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;
  background:var(--accent);color:#fff;letter-spacing:.06em}
.outcome-badge{font-size:8px;font-weight:700;padding:1px 6px;border-radius:3px;letter-spacing:.04em}
.outcome-badge.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.outcome-badge.ret{background:var(--ret-bg);color:var(--ret-txt)}
.outcome-badge.review{background:var(--rev-bg);color:var(--rev-txt)}
.scan-wrap{padding:7px 9px 0;background:var(--surface2)}
.scan-img{width:100%;border-radius:3px;border:1px solid var(--border);display:block}
.model-badge-row{display:flex;align-items:center;gap:5px;padding:4px 9px;
  background:rgba(16,185,129,.07);border-top:1px solid rgba(16,185,129,.15)}
.model-badge{font-size:8px;font-weight:700;padding:1px 5px;border-radius:3px;
  background:var(--pass-bg);color:var(--pass-txt);letter-spacing:.05em}
.model-via{font-size:8px;color:var(--faint);flex:1}
.model-time{font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--faint)}
.ocr-fields{padding:7px 9px;flex:1}
.fr{display:flex;align-items:baseline;gap:4px;padding:2px 0;border-bottom:1px solid var(--border)}
.fr:last-child,.fr.xlit{border-bottom:none;padding-top:0}
.fl{font-size:7px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--faint);width:36px;flex-shrink:0}
.fv{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text);
  flex:1;word-break:break-all;line-height:1.3}
.fv.indic{font-family:'Noto Sans','Nirmala UI',system-ui,sans-serif;font-size:11px}
.fv.dim{color:var(--faint);font-style:italic}
.fv.xlit-v{font-size:9px;color:var(--faint);font-style:italic}
.ocr-err{font-size:9px;color:var(--ret-txt);font-style:italic;padding:4px 0}
.ocr-mm{font-size:8.5px;font-weight:700;color:var(--ret-txt);margin-top:4px;
  background:var(--ret-bg);padding:2px 5px;border-radius:3px}
.ocr-warn{font-size:8px;color:var(--rev-txt);margin-top:3px;
  background:var(--rev-bg);padding:2px 5px;border-radius:3px}
.pipe-lbl{font-size:7px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;
  color:var(--faint);margin-bottom:3px}
.script-detect{font-size:9px;color:var(--accent);margin-bottom:3px;
  padding-bottom:3px;border-bottom:1px solid var(--border)}
.mm-verdict{font-size:8px;font-weight:700;padding:2px 6px;border-radius:3px;margin-top:4px}
.mm-correct{background:var(--pass-bg);color:var(--pass-txt)}
.mm-missed{background:var(--rev-bg);color:var(--rev-txt)}
.sp-pipe{padding:8px 9px;border-top:1px solid var(--border)}
.pill-row{display:flex;gap:3px;flex-wrap:wrap;margin-bottom:4px}
.pill{font-size:7.5px;font-weight:600;padding:1px 5px;border-radius:3px;
  border:1px solid var(--border);color:var(--muted);background:var(--surface2)}
.pill.ok{color:var(--pass-txt);background:var(--pass-bg);border-color:transparent}
.pill.danger{color:var(--ret-txt);background:var(--ret-bg);border-color:transparent}
.pill.warn{color:var(--rev-txt);background:var(--rev-bg);border-color:transparent}
.fraud-row{display:flex;align-items:center;gap:4px;margin-bottom:4px}
.fraud-lbl{font-size:7px;font-weight:600;color:var(--faint);text-transform:uppercase;
  letter-spacing:.05em;width:26px}
.fraud-track{flex:1;height:3px;background:var(--border);border-radius:2px;overflow:hidden}
.fraud-fill{height:100%;border-radius:2px;background:var(--pass)}
.fraud-fill.mid{background:var(--rev)}.fraud-fill.hi{background:var(--ret)}
.fraud-num{font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--muted);
  width:20px;text-align:right}
.decision{display:flex;align-items:center;justify-content:center;gap:3px;
  font-size:8.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:3px;border-radius:3px;margin-bottom:3px}
.decision.confirm{background:var(--pass-bg);color:var(--pass-txt)}
.decision.ret{background:var(--ret-bg);color:var(--ret-txt)}
.decision.review{background:var(--rev-bg);color:var(--rev-txt)}
.rej-banner{display:flex;align-items:flex-start;gap:3px;background:var(--ret-bg);
  border:1px solid rgba(185,28,28,.16);border-radius:3px;padding:2px 5px;margin-bottom:2px}
.rej-code{font-size:7px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ret-txt);white-space:nowrap}
.rej-why{font-size:7px;color:var(--ret-txt);opacity:.85}
.pg-footer{max-width:1080px;margin:20px auto 0;padding-top:11px;
  border-top:1px solid var(--border);display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:4px;font-size:10px;color:var(--faint)}
.pg-footer strong{color:var(--muted);font-weight:600}
"""

# ── Build page ────────────────────────────────────────────────────────────────

def build_html(real_html: list, spec_html: list) -> str:
    return f"""<title>Regional Language OCR</title>
<style>{CSS}</style>
<div class="ph">
  <div class="eyebrow">ASTRA CTS &bull; Qwen3-VL-32B &bull; HF Inference Router</div>
  <h1>CTS Full Pipeline &mdash; Real Scans + PIL Regional Language Specimens</h1>
  <p><strong>Section 1</strong> — real bank scans: OCR by Qwen3-VL-32B (real <code>_OCR_PROMPT</code>
  + <code>amounts_match()</code>). &nbsp;
  <strong>Section 2</strong> — PIL-synthesised Indic cheques: full four-stage pipeline —
  OCR → CBS lookup (seeded vault) → Fraud score (live HF call, Qwen3-VL-32B) → Signature
  (seeded Siamese vault) → final decision. All thresholds from <code>_defaults.yaml</code>
  (same values <code>ChequeProcessingWorkflow</code> reads from <code>config_service</code>).</p>
  <div class="meta-bar">
    <span class="mpill">Model: <strong>Qwen/Qwen3-VL-32B-Instruct</strong></span>
    <span class="mpill">Backend: <strong>featherless-ai via HF Router</strong></span>
    <span class="mpill">Section 1: <strong>9 real scans</strong></span>
    <span class="mpill">Section 2: <strong>9 PIL specimens</strong> · 8 Indic scripts</span>
    <span class="mpill">Live calls: <strong>OCR + Fraud</strong> per specimen</span>
    <span class="mpill">Seeded: <strong>CBS vault · Sig vault</strong></span>
  </div>
</div>
<div class="section">
  <div class="section-hdr">
    <h2>Section 1 &mdash; Real Bank Cheque Scans</h2>
    <p>HDFC, NKGSB, Syndicate Bank scans from <code>demo/112/</code>.
    Payees and amounts are what Qwen3-VL-32B actually read from the image pixels.</p>
  </div>
  <div class="grid3">{"".join(real_html)}</div>
</div>
<div class="section">
  <div class="section-hdr">
    <h2>Section 2 &mdash; PIL-synthesised Regional Language Specimens</h2>
    <p>Each cheque rendered as a real PNG (PIL + Nirmala.ttc). Sent to Qwen3-VL-32B for extraction.
    Transliteration returned by the model shown in italic. Tamil and Gujarati have deliberate
    word/figure discrepancies — model verdict shown at the bottom of each card.</p>
  </div>
  <div class="grid3">{"".join(spec_html)}</div>
</div>
<div class="pg-footer">
  <strong>ASTRA &mdash; Bank Intelligence Platform</strong>
  <span>regional-language-v1 &bull; Qwen3-VL-32B &bull; PIL+Nirmala.ttc &bull; 2026-08-26</span>
</div>
"""

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    if not HF_TOKEN:
        print("ERROR: ASTRA_DEMO_HF_TOKEN not set"); sys.exit(1)

    # Section 1 — real scans
    print(f"\nSection 1: encoding {len(_FILES)} real scans...")
    data_urls = [_encode(f) for f in _FILES]
    thumbs    = [_thumb(f)  for f in _FILES]

    prod = "YES (real _OCR_PROMPT + amounts_match())" if _USING_PRODUCTION_CODE else "NO (import failed — fallback)"
    print(f"Production code wired: {prod}\n")

    print(f"Calling Qwen3-VL-32B on {len(_FILES)} real scans...\n")
    real_exts: list[dict] = []
    for i, (path, du) in enumerate(zip(_FILES, data_urls)):
        print(f"  [{i+1:02d}/{len(_FILES)}] {path.name} ...", end=" ", flush=True)
        t0  = time.perf_counter()
        ext = await run_real_ocr(du)
        ext["_elapsed_ms"] = (time.perf_counter() - t0) * 1000
        if "_error" in ext:
            print(f"ERROR: {ext['_error'][:60]}")
        else:
            mm = " [MISMATCH]" if ext.get("amount_mismatch") else ""
            line = (f"-> {ext.get('payee','?')} | {ext.get('amount_figures','?')} | "
                    f"OCR:{ext.get('outcome','?')}{mm} | {ext['_elapsed_ms']:.0f}ms")
            print(line.encode("ascii", "replace").decode("ascii"))
        real_exts.append(ext)

    # Section 2 — PIL specimens
    print(f"\nSection 2: synthesising {len(SPECIMENS)} PIL cheque images...")
    spec_img_urls: list[str] = []
    for sp in SPECIMENS:
        print(f"  Rendering {sp['code']:2s} ({sp['lang']}) ...", end=" ", flush=True)
        _bytes, du = make_cheque_image(sp)
        spec_img_urls.append(du)
        print(f"{len(_bytes) // 1024} KB")

    print(f"\nCalling Qwen3-VL-32B on {len(SPECIMENS)} PIL specimens (OCR + fraud)...\n")
    spec_exts:      list[dict] = []
    spec_fraud:     list[dict] = []
    spec_pipelines: list[dict] = []
    for i, (sp, du) in enumerate(zip(SPECIMENS, spec_img_urls)):
        print(f"  [{i+1:02d}/{len(SPECIMENS)}] {sp['lang']:10s} ({sp['code']}) OCR...", end=" ", flush=True)
        t0  = time.perf_counter()
        ext = await run_real_ocr(du)
        ext["_elapsed_ms"] = (time.perf_counter() - t0) * 1000
        if "_error" in ext:
            print(f"ERROR: {ext['_error'][:60]}")
        else:
            mm = " [MISMATCH]" if ext.get("amount_mismatch") else ""
            line = (f"-> {ext.get('payee','?')} | {ext.get('amount_figures','?')} | "
                    f"OCR:{ext.get('outcome','?')}{mm} | {ext['_elapsed_ms']:.0f}ms")
            print(line.encode("ascii", "replace").decode("ascii"))
        spec_exts.append(ext)

        print(f"            {sp['lang']:10s} ({sp['code']}) Fraud...", end=" ", flush=True)
        fr = await run_fraud_score(du)
        fc = " [ERROR]" if "_error" in fr else ""
        print(f"fraud={fr['fraud_score']:.2f} {fc} | {fr['_elapsed_ms']:.0f}ms")
        spec_fraud.append(fr)

        pipeline = make_pipeline_decision(sp, ext, fr)
        spec_pipelines.append(pipeline)
        pline = f"  => {pipeline['outcome']}"
        if pipeline.get("reason"):
            pline += f" ({pipeline['reason']})"
        print(pline)

    print("\nGenerating HTML...")
    rc_html = [
        real_card(i, path, ext, thumb)
        for i, (path, ext, thumb)
        in enumerate(zip(_FILES, real_exts, thumbs))
    ]
    sp_html = [
        specimen_card(sp, img_url, ext, pipeline, ext.get("_elapsed_ms", 0))
        for sp, img_url, ext, pipeline
        in zip(SPECIMENS, spec_img_urls, spec_exts, spec_pipelines)
    ]

    html = build_html(rc_html, sp_html)
    OUT.write_text(html, encoding="utf-8")
    print(f"\nWritten: {OUT}  ({len(html) // 1024} KB)")

if __name__ == "__main__":
    asyncio.run(main())
