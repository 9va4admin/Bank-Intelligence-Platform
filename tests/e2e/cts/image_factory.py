"""
CTS E2E Synthetic Cheque Image Generator
==========================================
Visual DNA derived from real Indian bank CTS-2010 cheques (demo/112/):

  Real cheques studied:
  • Syndicate Bank — mint-green security paper, blue handwriting, single sig
  • Axis Bank      — cream/off-white paper, black handwriting, single sig

  What this generator produces:
  ✓ Proper CTS paper layout  — header / PAY / RUPEES / A/c No / MICR
  ✓ Indic payee names        — Nirmala UI font (Windows built-in)
                                covers: Hindi · Marathi · Tamil · Telugu ·
                                Kannada · Gujarati · Bengali · Malayalam · English
  ✓ Handwritten style        — Inkfree font for payee name + amount-in-words
  ✓ Amount in words          — proper Indian system (lakhs / crores)
  ✓ 1 / 2 / 3 signature boxes — driven by scenario:
                                  single  → normal cheque
                                  two     → high-value (≥ ₹20L) / joint account
                                  three   → MSV scenario (3rd box left unsigned = fraud trigger)
  ✓ Security watermark       — faint bank-name tile across lower body
  ✓ CTS-2010 vertical margin text (left edge)
  ✓ Date box                 — individual D D | M M | Y Y Y Y cells
  ✓ MICR band                — dark navy, monospace
  ✓ 52 px test-metadata annotation bar (fixture ID, polarity, trigger, outcome)
  ✓ 4 px polarity border     — green = POSITIVE, red = NEGATIVE
"""
from __future__ import annotations

import base64
import io
import math
import random as _rnd

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Font registry
# ─────────────────────────────────────────────────────────────────────────────

_FC: dict[str, object] = {}

def _f(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    """Arial regular / bold — printed labels."""
    k = f"{'b' if bold else 'r'}{size}"
    if k not in _FC:
        cands = (["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"]
                 if bold else ["C:/Windows/Fonts/arial.ttf"])
        for p in cands:
            try: _FC[k] = ImageFont.truetype(p, size); break
            except: pass
        else: _FC[k] = ImageFont.load_default()
    return _FC[k]


def _fmono(size: int) -> "ImageFont.FreeTypeFont":
    """Courier New — MICR line and account numbers."""
    k = f"mono{size}"
    if k not in _FC:
        for p in ["C:/Windows/Fonts/cour.ttf", "C:/Windows/Fonts/consola.ttf"]:
            try: _FC[k] = ImageFont.truetype(p, size); break
            except: pass
        else: _FC[k] = _f(size)
    return _FC[k]


def _fhand(size: int) -> "ImageFont.FreeTypeFont":
    """Inkfree — handwritten-style English text (payee name, amount in words)."""
    k = f"hand{size}"
    if k not in _FC:
        for p in ["C:/Windows/Fonts/Inkfree.ttf", "C:/Windows/Fonts/LHANDW.TTF",
                  "C:/Windows/Fonts/comic.ttf"]:
            try: _FC[k] = ImageFont.truetype(p, size); break
            except: pass
        else: _FC[k] = _f(size)
    return _FC[k]


def _findic(size: int) -> "ImageFont.FreeTypeFont":
    """Nirmala UI — covers all 9 Indian scripts from a single .ttc file."""
    k = f"indic{size}"
    if k not in _FC:
        try: _FC[k] = ImageFont.truetype("C:/Windows/Fonts/Nirmala.ttc", size, index=0)
        except: _FC[k] = _f(size)
    return _FC[k]


def _payee_font(text: str, size: int) -> "ImageFont.FreeTypeFont":
    """Choose Inkfree for ASCII names, Nirmala for Indic scripts."""
    return _findic(size) if any(ord(c) > 127 for c in text) else _fhand(size)


# ─────────────────────────────────────────────────────────────────────────────
# Indian amount-in-words (lakhs / crores system)
# ─────────────────────────────────────────────────────────────────────────────

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _sub_hundred(n: int) -> str:
    if n == 0: return ""
    if n < 20: return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _sub_thousand(n: int) -> str:
    if n == 0: return ""
    h, r = n // 100, n % 100
    parts = []
    if h: parts.append(f"{_ONES[h]} Hundred")
    if r: parts.append(_sub_hundred(r))
    return " ".join(parts)


def _amount_in_words(amount: float) -> str:
    n, p = int(amount), round((amount - int(amount)) * 100)
    if n == 0 and p == 0: return "Zero Rupees Only"
    parts: list[str] = []
    for div, label in [(10_000_000, "Crore"), (100_000, "Lakh"),
                       (1_000, "Thousand"), (1, "")]:
        q = n // div; n %= div
        if not q: continue
        chunk = _sub_thousand(q)
        if label:
            parts.append(f"{chunk} {label}{'s' if q > 1 and label in ('Crore', 'Lakh') else ''}")
        else:
            parts.append(chunk)
    result = "Rupees " + " ".join(parts)
    if p: result += f" and {_sub_hundred(p)} Paise"
    return result + " Only"


def _tampered_digit_amount(fixture) -> float:
    """Fraudulent amount: prepend first digit (42,000 → 4,42,000) — simulates digit-box tampering."""
    n = str(int(fixture.amount))
    return float(n[0] + n)


# ─────────────────────────────────────────────────────────────────────────────
# Regional numeral tables — Unicode digit blocks for each Indic script
# ─────────────────────────────────────────────────────────────────────────────

_REGIONAL_DIGITS: dict[str, str] = {
    # script-key      : "0123456789" in that script
    "devanagari": "०१२३४५६७८९",   # Hindi + Marathi
    "bengali":    "০১২৩৪৫৬৭৮৯",
    "tamil":      "௦௧௨௩௪௫௬௭௮௯",
    "telugu":     "౦౧౨౩౪౫౬౭౮౯",
    "kannada":    "೦೧೨೩೪೫೬೭೮೯",
    "gujarati":   "૦૧૨૩૪૫૬૭૮૯",
    "malayalam":  "൦൧൨൩൪൫൬൭൮൯",
}

# Language label (lower-case) → which script key to use
_LANG_SCRIPT: dict[str, str] = {
    "hindi":      "devanagari",
    "marathi":    "devanagari",
    "mixed hi+mr":"devanagari",
    "bengali":    "bengali",
    "tamil":      "tamil",
    "telugu":     "telugu",
    "kannada":    "kannada",
    "gujarati":   "gujarati",
    "malayalam":  "malayalam",
}


def _to_regional(text: str, language: str) -> str:
    """Replace ASCII digits in *text* with the regional numeral script for *language*.
    Commas and '/-' stay in ASCII — that is standard on Indian cheques."""
    script = _LANG_SCRIPT.get(language.lower().strip())
    if not script:
        return text                          # English / bilingual → keep ASCII
    table = _REGIONAL_DIGITS[script]
    return "".join(table[int(c)] if c.isdigit() else c for c in text)


def _format_inr(amount: float) -> str:
    """Format amount in Indian comma convention: 25,00,000/- (not 2,500,000/-)."""
    n = int(amount)
    if n < 1000:
        return f"{n}/-"
    # Last 3 digits as units block, then groups of 2
    units = n % 1000
    rest  = n // 1000
    parts = [f"{units:03d}"]
    while rest:
        parts.append(f"{rest % 100:02d}" if rest >= 100 else str(rest % 100))
        rest //= 100
    return ",".join(reversed(parts)) + "/-"


# ─────────────────────────────────────────────────────────────────────────────
# Paper & colour palette (two real-world cheque styles)
# ─────────────────────────────────────────────────────────────────────────────

# (paper_bg, bank_accent, rule_col, watermark_col)
_PAPER_STYLES = {
    0: ((228, 248, 234), (14,  100,  52), (140, 195, 158), (175, 230, 190)),  # mint-green  (PSB/Coop)
    1: ((252, 250, 240), (140,  15,  38), (200, 175, 155), (232, 212, 195)),  # cream-maroon (Axis/ICICI)
    2: ((232, 244, 254), ( 10,  60, 145), (150, 185, 228), (180, 215, 250)),  # light-blue   (UCB/Coop)
    3: ((252, 248, 224), ( 85,  58,  12), (205, 185, 138), (235, 220, 178)),  # warm-cream   (Karnataka/Canara)
}

_INK    = (8,  18,  80)       # dark blue ink — handwritten text
_PRINT  = (12, 12,  18)       # near-black — printed labels
_MICR_BG = (10, 16, 34)
_MICR_FG = (205, 228, 255)


def _style(bank_id: str) -> tuple:
    return _PAPER_STYLES[hash(bank_id) % 4]


# ─────────────────────────────────────────────────────────────────────────────
# Canvas constants
# ─────────────────────────────────────────────────────────────────────────────

_W       = 1400
_BODY_H  = 648
_ANNO_H  = 52
_TOTAL_H = _ANNO_H + _BODY_H
_ML      = 36     # left margin
_MR      = 36     # right margin


# ─────────────────────────────────────────────────────────────────────────────
# Security watermark — faint bank-name tile across lower body
# ─────────────────────────────────────────────────────────────────────────────

def _watermark(img: "Image.Image", bank_name: str, wm_col: tuple,
               y_start: int, height: int) -> None:
    layer = Image.new("RGBA", (_W, _TOTAL_H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    txt = (bank_name.upper() + "  ") * 4
    fn  = _f(11)
    step_x, step_y = 240, 38
    for row in range(height // step_y + 2):
        for col in range(_W // step_x + 2):
            x = col * step_x - 60 + (row * 35 % step_x)
            y = y_start + row * step_y - 8
            ld.text((x, y), txt, font=fn, fill=(*wm_col, 75))
    img.paste(layer, mask=layer.split()[3])


# ─────────────────────────────────────────────────────────────────────────────
# Date box — individual cells: D D | M M | Y Y Y Y
# ─────────────────────────────────────────────────────────────────────────────

def _date_box(d: "ImageDraw.Draw", x: int, y: int,
              date_str: str, accent: tuple) -> None:
    parts = date_str.replace("-", "/").split("/")
    if len(parts) == 3:
        digits = list(parts[0].zfill(2) + parts[1].zfill(2) + parts[2].zfill(4))
    else:
        digits = list("        ")

    d.text((x, y - 16), "DATE  /  दिनांक", font=_f(9), fill=accent)

    cw, ch = 28, 34
    gap = 6   # extra gap between D/D, M/M, Y/Y/Y/Y groups
    groups = [0, 0, 1, 1, 2, 2, 2, 2]
    for i, ch_val in enumerate(digits):
        cx = x + i * cw + (groups[i] * gap)
        d.rectangle([cx, y, cx + cw - 2, y + ch], outline=accent, width=1)
        d.text((cx + 6, y + 7), ch_val.strip(), font=_fmono(17), fill=_PRINT)

    for i, lbl in enumerate(["D", "D", "M", "M", "Y", "Y", "Y", "Y"]):
        cx = x + i * cw + (groups[i] * gap)
        d.text((cx + 9, y + ch + 3), lbl, font=_f(8), fill=accent)


# ─────────────────────────────────────────────────────────────────────────────
# Parametric handwritten signature
# ─────────────────────────────────────────────────────────────────────────────

def _signature(d: "ImageDraw.Draw", bx: int, by: int, bw: int, bh: int,
               seed: int, ink: tuple) -> None:
    rng  = _rnd.Random(seed)
    pen  = 2
    px   = bw // 10
    py   = bh // 8
    x0   = bx + px
    x1   = bx + bw - px
    span = x1 - x0
    cy   = by + int(bh * rng.uniform(0.42, 0.58))

    # Initial loop (first initial)
    iw   = int(span * rng.uniform(0.24, 0.36))
    f1   = rng.uniform(1.4, 2.2)
    a1   = int(bh * rng.uniform(0.18, 0.30))
    ph1  = rng.uniform(0, math.pi)
    pts1 = [(x0 + t / 70 * iw,
             cy + a1 * math.sin(t * math.pi / 70) * math.sin(f1 * t * math.pi * 2 / 70 + ph1))
            for t in range(71)]
    d.line(pts1, fill=ink, width=pen + 1)

    # Surname wave
    sx2 = x0 + iw - 3
    f2  = rng.uniform(0.7, 1.2)
    a2  = int(bh * rng.uniform(0.12, 0.22))
    ph2 = rng.uniform(0, math.pi)
    pts2 = [(sx2 + t / 120 * (x1 - sx2),
             cy + a2 * math.sin(t * math.pi / 120) * (1 - 0.4 * t / 120)
                * math.sin(f2 * t * math.pi * 2 / 120 + ph2))
            for t in range(121)]
    d.line(pts2, fill=ink, width=pen)

    # Trailing hook
    hx     = x1 - int(span * rng.uniform(0.05, 0.12))
    hook_d = int(bh * rng.uniform(0.14, 0.24))
    pts3   = [(hx + t / 30 * (x1 - hx + 5),
               cy + hook_d * math.sin(t * math.pi / 2 / 30))
              for t in range(31)]
    d.line(pts3, fill=ink, width=pen)

    # Underline
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


# ─────────────────────────────────────────────────────────────────────────────
# Language → signature style routing
# ─────────────────────────────────────────────────────────────────────────────

_LANG_SIG_STYLE: dict[str, str] = {
    "hindi":        "devanagari",
    "marathi":      "devanagari",
    "mixed hi+mr":  "devanagari",
    "bengali":      "bengali",
    "tamil":        "dravidian",
    "telugu":       "dravidian",
    "kannada":      "dravidian",
    "gujarati":     "gujarati",
    "malayalam":    "malayalam",
}


def _sig_devanagari(d: "ImageDraw.Draw", bx: int, by: int,
                    bw: int, bh: int, seed: int, ink: tuple) -> None:
    """Hindi/Marathi — strong shirorekhā bar, angular hanging strokes, right-curl flourish."""
    rng = _rnd.Random(seed)
    px, py = bw // 10, bh // 8
    x0, x1 = bx + px, bx + bw - px
    bar_y = by + int(bh * 0.30)

    # Shirorekha (horizontal bar — defines Devanagari scripts)
    d.line([(x0, bar_y), (x1, bar_y)], fill=ink, width=2)

    # Angular downstrokes hanging from bar
    n_strokes = rng.randint(3, 5)
    for i in range(n_strokes):
        sx = x0 + int((i + rng.uniform(0.2, 0.8)) * (x1 - x0) / n_strokes)
        drop = int(bh * rng.uniform(0.28, 0.50))
        slant = rng.randint(-7, 7)
        d.line([(sx, bar_y), (sx + slant, bar_y + drop)], fill=ink, width=2)
        d.line([(sx + slant - 4, bar_y + drop),
                (sx + slant + 4, bar_y + drop)], fill=ink, width=1)

    # Right-curling end flourish (half-circle)
    fx = x1 - int((x1 - x0) * 0.12)
    r  = int(bh * 0.11)
    curl = [(fx + int(r * math.cos(t * math.pi / 16 - math.pi / 2)),
             bar_y + r + int(r * math.sin(t * math.pi / 16 - math.pi / 2)))
            for t in range(17)]
    d.line(curl, fill=ink, width=1)
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


def _sig_bengali(d: "ImageDraw.Draw", bx: int, by: int,
                 bw: int, bh: int, seed: int, ink: tuple) -> None:
    """Bengali — large sweeping upward arc, closed loop, elongated trailing stroke."""
    rng = _rnd.Random(seed)
    px, py = bw // 10, bh // 8
    x0, x1 = bx + px, bx + bw - px
    cy = by + int(bh * rng.uniform(0.48, 0.56))

    # Large rising sweep (the dominant Bengali stroke)
    sweep = [(x0 + int(t / 60 * (x1 - x0) * 0.62),
              cy - int(bh * 0.38 * math.sin(t / 60 * math.pi))
              + int(bh * 0.04 * math.sin(t / 60 * math.pi * 5)))
             for t in range(61)]
    d.line(sweep, fill=ink, width=2)

    # Closed loop at sweep peak
    lx = sweep[30][0]
    ly = sweep[30][1]
    lr_x = int((x1 - x0) * 0.13)
    lr_y = int(bh * rng.uniform(0.13, 0.19))
    loop = [(lx + int(lr_x * math.cos(t * math.pi * 2 / 30)),
             ly + int(lr_y * math.sin(t * math.pi * 2 / 30)))
            for t in range(31)]
    d.line(loop, fill=ink, width=2)

    # Elongated trailing stroke
    tail_x0 = sweep[-1][0]
    tail = [(tail_x0 + int(t / 30 * (x1 - tail_x0)),
             cy + int(bh * 0.06 * math.sin(t * math.pi / 30)))
            for t in range(31)]
    d.line(tail, fill=ink, width=1)
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


def _sig_dravidian(d: "ImageDraw.Draw", bx: int, by: int,
                   bw: int, bh: int, seed: int, ink: tuple) -> None:
    """Tamil/Telugu/Kannada — compact angular zigzag, small entry loop, downward hook end."""
    rng = _rnd.Random(seed)
    px, py = bw // 10, bh // 8
    x0, x1 = bx + px, bx + bw - px
    cy = by + int(bh * 0.50)

    # Small entry circle
    lr = int(bh * 0.12)
    lx = x0 + lr + 2
    d.line([(lx + int(lr * math.cos(t * math.pi * 2 / 20)),
             cy + int(lr * 0.65 * math.sin(t * math.pi * 2 / 20)))
            for t in range(21)], fill=ink, width=2)

    # Angular zigzag body — sharp direction changes (no curves)
    n_segs = rng.randint(3, 4)
    seg_w  = (x1 - (lx + lr)) / n_segs
    cx_cur, cy_cur = lx + lr, cy
    for i in range(n_segs):
        nx = cx_cur + int(seg_w)
        amp = int(bh * rng.uniform(0.22, 0.36))
        ny  = cy + (amp if i % 2 == 0 else -amp)
        d.line([(cx_cur, cy_cur), (nx, ny)], fill=ink, width=2)
        cx_cur, cy_cur = nx, ny

    # Downward hook
    d.line([(cx_cur, cy_cur),
            (cx_cur + 5, cy_cur + int(bh * 0.22))], fill=ink, width=2)
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


def _sig_gujarati(d: "ImageDraw.Draw", bx: int, by: int,
                  bw: int, bh: int, seed: int, ink: tuple) -> None:
    """Gujarati — two forward-slanting elongated loops, rightward sweep."""
    rng = _rnd.Random(seed)
    px, py = bw // 10, bh // 8
    x0, x1 = bx + px, bx + bw - px
    cy = by + int(bh * rng.uniform(0.46, 0.54))
    slant = int(bh * 0.14)

    # Two elongated forward-slanting loops
    loop_w = int((x1 - x0) * 0.30)
    for li in range(2):
        lx   = x0 + li * (loop_w + 8)
        lr_x = int(loop_w * 0.42)
        lr_y = int(bh * rng.uniform(0.18, 0.28))
        pts  = [(lx + int(lr_x * (1 - math.cos(t * math.pi * 2 / 40)) / 2)
                 + int(slant * t / 40),
                 cy + int(lr_y * math.sin(t * math.pi * 2 / 40)))
                for t in range(41)]
        d.line(pts, fill=ink, width=2)

    # Long rightward sweep
    sx0 = x0 + 2 * (loop_w + 8)
    sweep = [(sx0 + int(t / 30 * (x1 - sx0)),
              cy + int(bh * 0.07 * math.sin(t * math.pi * 1.5 / 30)))
             for t in range(31)]
    d.line(sweep, fill=ink, width=1)
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


def _sig_malayalam(d: "ImageDraw.Draw", bx: int, by: int,
                   bw: int, bh: int, seed: int, ink: tuple) -> None:
    """Malayalam — 2–3 compact rounded loops, upward tick, short horizontal tail."""
    rng = _rnd.Random(seed)
    px, py = bw // 10, bh // 8
    x0, x1 = bx + px, bx + bw - px
    cy = by + int(bh * 0.50)

    n_loops = rng.randint(2, 3)
    total_w = int((x1 - x0) * 0.60)
    lr_x    = total_w // (n_loops * 2)
    lr_y    = int(bh * rng.uniform(0.16, 0.24))

    for li in range(n_loops):
        lx = x0 + lr_x + li * (lr_x * 2 + 5)
        d.line([(lx + int(lr_x * math.cos(t * math.pi * 2 / 30)),
                 cy + int(lr_y * math.sin(t * math.pi * 2 / 30)))
                for t in range(31)], fill=ink, width=2)

    # Upward tick
    tx = x0 + total_w + 6
    d.line([(tx, cy), (tx + 9, cy - int(bh * 0.24)),
            (tx + 13, cy - int(bh * 0.09))], fill=ink, width=1)
    # Short horizontal tail
    d.line([(tx + 13, cy - int(bh * 0.09)), (x1, cy - int(bh * 0.04))],
           fill=ink, width=1)
    d.line([(x0, by + bh - py), (x1, by + bh - py)], fill=ink, width=1)


_SIG_DRAWERS: dict[str, "callable"] = {
    "devanagari": _sig_devanagari,
    "bengali":    _sig_bengali,
    "dravidian":  _sig_dravidian,
    "gujarati":   _sig_gujarati,
    "malayalam":  _sig_malayalam,
    "latin":      _signature,         # existing algorithm — English / fallback
}


def _sig_box(d: "ImageDraw.Draw", bx: int, by: int, bw: int, bh: int,
             seed: int, ink: tuple, accent: tuple,
             label: str, signed: bool, language: str = "") -> None:
    d.rectangle([bx, by, bx + bw, by + bh], outline=accent, width=1)
    if signed:
        style = _LANG_SIG_STYLE.get(language.lower().strip(), "latin")
        _SIG_DRAWERS[style](d, bx, by, bw, bh, seed, ink)
    else:
        # Unsigned box — red diagonal cross-marks
        d.line([(bx + 8, by + 8), (bx + bw - 8, by + bh - 8)],
               fill=(220, 38, 38), width=1)
        d.line([(bx + bw - 8, by + 8), (bx + 8, by + bh - 8)],
               fill=(220, 38, 38), width=1)
        d.text((bx + bw // 2 - 28, by + bh // 2 - 8),
               "MISSING", font=_f(11, bold=True), fill=(220, 38, 38))
    d.text((bx + 4, by + bh + 4), label, font=_f(8), fill=_PRINT)
    d.text((bx + bw - 80, by + bh + 4), "Please sign above", font=_f(7), fill=accent)


# ─────────────────────────────────────────────────────────────────────────────
# Signature count by scenario
# ─────────────────────────────────────────────────────────────────────────────

def _n_sigs(fixture) -> int:
    trig = getattr(fixture, "trigger", "")
    amt  = getattr(fixture, "amount", 0)
    if "MSV" in trig or "MULTI_SIG" in trig:
        return 3          # 3 required; 3rd left unsigned (fraud)
    if amt >= 2_000_000:
        return 2          # high-value: joint signatory required
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# Outcome annotation
# ─────────────────────────────────────────────────────────────────────────────

_OC = {
    "STP_CONFIRM":     (22, 163,  74),
    "ACCEPTED":        (22, 163,  74),
    "STP_RETURN":      (220,  38,  38),
    "CTS_REJECTED":    (220,  38,  38),
    "HUMAN_REVIEW":    (202, 138,   4),
    "MISMATCH_HELD":   (202, 138,   4),
    "POST_DATED_HELD": (124,  58, 237),
}
_OL = {
    "STP_CONFIRM":     "STP CONFIRM",
    "ACCEPTED":        "ACCEPTED",
    "STP_RETURN":      "STP RETURN",
    "CTS_REJECTED":    "CTS REJECTED",
    "HUMAN_REVIEW":    "HUMAN REVIEW",
    "MISMATCH_HELD":   "MISMATCH HELD",
    "POST_DATED_HELD": "POST-DATED HELD",
}


# ─────────────────────────────────────────────────────────────────────────────
# Main cheque renderer
# ─────────────────────────────────────────────────────────────────────────────

def _build(fixture) -> "Image.Image":
    paper, accent, rule_col, wm_col = _style(fixture.bank_id)
    bank = fixture.bank_id.replace("-", " ").title()

    canvas = Image.new("RGBA", (_W, _TOTAL_H), (255, 255, 255, 255))
    d = ImageDraw.Draw(canvas)

    # ── Annotation bar ────────────────────────────────────────────────────────
    d.rectangle([0, 0, _W, _ANNO_H], fill=(14, 20, 34))
    oc = _OC.get(fixture.expected_outcome, (110, 110, 120))
    ol = _OL.get(fixture.expected_outcome, fixture.expected_outcome)
    pc = (34, 197, 94) if fixture.polarity == "POSITIVE" else (239, 68, 68)
    wf = "OUTWARD" if fixture.fixture_id.startswith("OUT") else "INWARD"

    d.text((12, 8),  fixture.fixture_id,                    font=_f(15, bold=True), fill=(255, 255, 255))
    d.text((12, 28), wf,                                    font=_f(9),             fill=(110, 145, 190))
    d.text((86, 10), "● POSITIVE" if fixture.polarity == "POSITIVE" else "● NEGATIVE",
           font=_f(10, bold=True), fill=pc)
    d.text((86, 27), f"TRIGGER: {fixture.trigger}",         font=_f(9),             fill=(130, 158, 200))
    d.text((330, 10), fixture.scenario[:65],                font=_f(10),            fill=(165, 192, 225))
    bw_b = len(ol) * 7 + 20
    bx_b = _W - bw_b - 12
    d.rounded_rectangle([bx_b, 9, _W - 12, 43], radius=4, fill=oc)
    d.text((bx_b + 8, 16), ol, font=_f(10, bold=True), fill=(255, 255, 255))

    # ── Cheque body ───────────────────────────────────────────────────────────
    B = _ANNO_H   # y-offset for body
    d.rectangle([0, B, _W, _TOTAL_H], fill=(*paper, 255))

    # Security watermark
    _watermark(canvas, bank, wm_col, B + 330, 220)

    # CTS-2010 rotated left margin text
    m_layer = Image.new("RGBA", (320, 14), (0, 0, 0, 0))
    md = ImageDraw.Draw(m_layer)
    md.text((0, 0), "MANIPAL TECHNOLOGIES LTD.  /  CTS - 2010", font=_f(9), fill=(*accent, 90))
    rotated = m_layer.rotate(90, expand=True)
    canvas.paste(rotated, (5, B + 180), mask=rotated.split()[3])

    # ── HEADER (B → B+115) ───────────────────────────────────────────────────
    d.text((_ML + 2, B + 10), bank,  font=_f(24, bold=True), fill=accent)
    d.text((_ML + 2, B + 38), f"IFSC: {fixture.bank_ifsc}  ·  CORE BANKING BRANCH",
           font=_f(10), fill=_PRINT)
    d.text((_ML + 2, B + 54), "VALID FOR THREE MONTHS FROM THE DATE OF ISSUE",
           font=_f(9, bold=True), fill=(*accent, 200))
    d.text((_ML + 2, B + 70), f"Cheque No:  {fixture.cheque_number}",
           font=_fmono(11), fill=_PRINT)

    # Language badge
    lang_txt = f"[ {fixture.language} ]"
    lw = len(lang_txt) * 7 + 10
    d.rounded_rectangle([_W // 2 - lw // 2, B + 68, _W // 2 + lw // 2, B + 84],
                         radius=3, fill=(*accent, 30))
    d.text((_W // 2 - lw // 2 + 5, B + 70), lang_txt,
           font=_f(9, bold=True), fill=accent)

    # Date box
    _date_box(d, _W - 330, B + 18, fixture.cheque_date, accent)

    # Header rule
    d.line([(_ML, B + 106), (_W - _MR, B + 106)], fill=rule_col, width=1)

    # ── PAY ZONE (B+110 → B+190) ─────────────────────────────────────────────
    YP = B + 112
    d.text((_ML, YP + 2),  "PAY",  font=_f(13, bold=True), fill=_PRINT)
    d.text((_ML, YP + 18), "पे",   font=_findic(12), fill=_PRINT)

    payee_x = _ML + 56
    amt_box_x = _W - _MR - 350          # wider box (350 px)

    d.line([(payee_x, YP + 42), (amt_box_x - 10, YP + 42)], fill=rule_col, width=1)
    # "OR BEARER" sits at the right end of the payee underline, before the amount box
    d.text((amt_box_x - 130, YP + 6),  "OR BEARER",  font=_f(10, bold=True), fill=_PRINT)
    d.text((amt_box_x - 130, YP + 20), "या धारक को", font=_findic(10), fill=_PRINT)

    # Payee name — Nirmala for Indic, Inkfree for English
    payee = fixture.payee_name
    if "/" in payee:
        p1, p2 = payee.split("/", 1)
        d.text((payee_x + 4, YP + 4),  p1.strip(), font=_payee_font(p1, 20), fill=_INK)
        d.text((payee_x + 4, YP + 24), p2.strip(), font=_payee_font(p2, 16), fill=_INK)
    else:
        d.text((payee_x + 4, YP + 8), payee[:44], font=_payee_font(payee, 22), fill=_INK)

    # ── RUPEES ZONE (B+195 → B+280) ──────────────────────────────────────────
    YR = B + 196
    d.text((_ML,      YR + 2),  "RUPEES", font=_f(13, bold=True), fill=_PRINT)
    d.text((_ML,      YR + 18), "रुपये",  font=_findic(12), fill=_PRINT)

    rup_x = _ML + 78
    d.line([(rup_x, YR + 42), (amt_box_x - 10, YR + 42)], fill=rule_col, width=1)

    words = _amount_in_words(fixture.amount)
    MAX_L = 58
    if len(words) <= MAX_L:
        d.text((rup_x + 4, YR + 10), words, font=_fhand(18), fill=_INK)
    else:
        # Wrap at word boundary
        sp = MAX_L
        while sp < len(words) and words[sp] != " ":
            sp += 1
        d.text((rup_x + 4, YR + 4),   words[:sp].strip(), font=_fhand(17), fill=_INK)
        d.line([(rup_x, YR + 54), (amt_box_x - 10, YR + 54)], fill=rule_col, width=1)
        d.text((rup_x + 4, YR + 22),  words[sp:].strip(),  font=_fhand(17), fill=_INK)

    # Amount box spanning PAY + RUPEES rows — 350 px wide for legible numbers
    ABX, ABY, ABW, ABH = amt_box_x, YP - 2, 350, 96
    # For tampered cheques the box outline is in red to flag the fraud visually
    _trig = getattr(fixture, "trigger", "")
    _is_tampered = _trig in ("ALTERATION", "WORDS_DIGITS_MISMATCH")
    _box_outline = (185, 30, 30) if _is_tampered else accent
    d.rectangle([ABX, ABY, ABX + ABW, ABY + ABH], outline=_box_outline, width=2)
    d.line([(ABX + 50, ABY + 1), (ABX + 50, ABY + ABH - 1)], fill=rule_col, width=1)
    # ₹ symbol — Nirmala UI for guaranteed U+20B9 glyph
    d.text((ABX + 5,  ABY + 8),  "₹",        font=_findic(44), fill=accent)
    d.text((ABX + 6,  ABY + 66), "अदा करें", font=_findic(11), fill=_PRINT)
    # Tampered cheques: digit box shows fraudulent inflated amount (words stay original)
    _digit_amt = _tampered_digit_amount(fixture) if _is_tampered else fixture.amount
    _digit_ink = (185, 30, 30) if _is_tampered else _PRINT   # red = different pen

    # Amount string — converted to regional numerals when the cheque language has a script
    _lang = getattr(fixture, "language", "")
    _amt_ascii = _format_inr(_digit_amt)
    amt_str = _to_regional(_amt_ascii, _lang)

    # Font: Nirmala UI for regional scripts (Courier New lacks Indic digit glyphs)
    _use_indic_font = _LANG_SCRIPT.get(_lang.lower().strip()) is not None
    _amt_font_fn = _findic if _use_indic_font else _fmono
    # Auto-scale: column = 296 px
    amt_font_sz = 42 if len(amt_str) <= 9 else 36 if len(amt_str) <= 12 else 30
    d.text((ABX + 56, ABY + 12), amt_str, font=_amt_font_fn(amt_font_sz), fill=_digit_ink)
    if _is_tampered:
        d.text((ABX + 56, ABY + 78), "WORDS != DIGITS", font=_f(9, bold=True), fill=(185, 30, 30))
    else:
        d.text((ABX + 56, ABY + 78), fixture.amount_range, font=_f(9), fill=accent)

    # Rule below Rupees zone
    d.line([(_ML, YR + 70), (_W - _MR, YR + 70)], fill=rule_col, width=1)

    # ── A/C No ZONE (B+276 → B+350) ─────────────────────────────────────────
    YA = B + 280
    d.rectangle([(_ML, YA + 2), (_ML + 76, YA + 32)], outline=_PRINT, width=1)
    d.text((_ML + 5, YA + 9), "A/C No.", font=_f(11, bold=True), fill=_PRINT)
    masked = f"****  ****  {fixture.account_number[-4:]}"
    d.text((_ML + 84, YA + 4), masked, font=_fmono(18), fill=_PRINT)
    san = f"SAN : {fixture.cheque_number}"
    d.text((_ML + 84, YA + 28), san, font=_f(10), fill=_PRINT)

    # ── LOWER BODY (B+356 → B+555) ───────────────────────────────────────────
    YL = B + 358

    # Endorsement stamp area — diagonal hatch rectangle
    ex, ey, ew, eh = _ML, YL, 290, 130
    d.rectangle([ex, ey, ex + ew, ey + eh], outline=(*accent, 70), width=1)
    for i in range(0, ew + eh, 16):
        x1h = ex + max(0, i - eh); y1h = ey + max(0, eh - i)
        x2h = ex + min(ew, i);     y2h = ey + min(eh, eh - i + ew)
        d.line([(x1h, y1h), (x2h, y2h)], fill=(*rule_col, 55), width=1)

    # "Payable at par" text
    ppx = ex + 310
    d.text((ppx, YL + 70), f"Payable at par at all branches of",
           font=_f(10), fill=_PRINT)
    d.text((ppx, YL + 86), bank, font=_f(10, bold=True), fill=_PRINT)

    # ── SIGNATURE BOXES ───────────────────────────────────────────────────────
    n    = _n_sigs(fixture)
    seed = hash(fixture.fixture_id) & 0xFFFF_FFFF
    lang = getattr(fixture, "language", "")
    SH, SW = 95, 178
    ST = YL + 8

    if n == 1:
        sx = _W - _MR - SW - 4
        _sig_box(d, sx, ST, SW, SH, seed, _INK, accent,
                 "Authorised Signatory", True, lang)

    elif n == 2:
        sx2 = _W - _MR - SW - 4
        sx1 = sx2 - SW - 16
        _sig_box(d, sx1, ST, SW, SH, seed,        _INK, accent,
                 "Joint Holder – 1", True, lang)
        _sig_box(d, sx2, ST, SW, SH, seed + 7919, _INK, accent,
                 "Joint Holder – 2", True, lang)

    else:   # 3 required; 3rd unsigned = fraud
        sx3 = _W - _MR - SW - 4
        sx2 = sx3 - SW - 12
        sx1 = sx2 - SW - 12
        _sig_box(d, sx1, ST, SW, SH, seed,        _INK, accent,
                 "Signatory – 1", True, lang)
        _sig_box(d, sx2, ST, SW, SH, seed + 7919, _INK, accent,
                 "Signatory – 2", True, lang)
        _sig_box(d, sx3, ST, SW, SH, seed + 3571, _INK, accent,
                 "Signatory – 3 (Required)", False, lang)
        d.text((sx3 + 4, ST - 14), "⚠ SIGNATURE MISSING",
               font=_f(8, bold=True), fill=(220, 38, 38))

    # ── MICR BAND ─────────────────────────────────────────────────────────────
    YM = B + 560
    d.line([(0, YM), (_W, YM)], fill=rule_col, width=1)
    d.rectangle([0, YM + 1, _W, _TOTAL_H], fill=_MICR_BG)
    micr = (f'⑆{fixture.cheque_number}⑆  '
            f'⑇{fixture.micr_line}⑇  '
            f'{fixture.bank_ifsc[:6].upper()}⑈')
    d.text((20, YM + 14), micr, font=_fmono(20), fill=_MICR_FG)

    # ── Polarity border ───────────────────────────────────────────────────────
    bdr = (34, 197, 94) if fixture.polarity == "POSITIVE" else (239, 68, 68)
    for i in range(4):
        d.rectangle([i, i, _W - 1 - i, _TOTAL_H - 1 - i], outline=bdr)

    return canvas.convert("RGB")


def crop_signature_from_image_data(image_b64: str) -> str:
    """
    Crop the signature zone from a real cheque scan (base64 data URI).

    Bbox: tightly covers the CTS signature box — lower-right quadrant.
    X from 65% (avoids body text on left), Y from 70% to 88% (avoids MICR band).
    Enhancement is background-aware: chromatic paper (Canara blue, ICICI blue,
    SBI green) is desaturated before contrast boost so the watermark doesn't
    overpower the ink; neutral paper (cream/white) gets contrast directly.
    """
    if not _PIL_OK or not image_b64:
        return ""
    try:
        _, encoded = image_b64.split(",", 1)
        img = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
        w, h = img.size

        # X from 62%: footer text "Payable at...in India." on ICICI/Axis cheques
        # ends at ~60% width — 62% clears it without clipping HDFC-style sigs.
        # Y from 58%: CTS sig ink starts at ~58-62% height; 86% stays above MICR.
        x0 = max(0, int(0.64 * w))
        y0 = max(0, int(0.58 * h))
        x1 = min(w, int(0.99 * w))
        y1 = min(h, int(0.86 * h))
        raw_crop = img.crop((x0, y0, x1, y1))

        # ── Step 1: auto-trim "Please sign above" label on the RAW crop ────────
        # Must run before enhancement: desaturation lightens the label text too,
        # reducing its dark-pixel density below the detection threshold.
        # Scan bottom 60% of crop (scan_from=0.40) to catch HDFC cheques where
        # the label sits at ~57% of crop height.
        # Fallback = no trim (e.g. 1.tiff where the sig tail merges with label).
        try:
            import numpy as _np
            _g = _np.array(raw_crop.convert("L"))
            _h, _w = _g.shape
            _dark = _g < 160
            _dens = _dark.mean(axis=1)
            _scan_from = int(_h * 0.40)
            _LABEL, _GAP = 0.025, 0.008
            _in_text, _label_top = False, None
            for _r in range(_h - 1, _scan_from - 1, -1):
                if _dens[_r] >= _LABEL:
                    _in_text = True
                elif _in_text and _dens[_r] < _GAP:
                    _label_top = _r + 1
                    break
            if _label_top is not None and _label_top > int(_h * 0.25):
                _cut = max(int(_h * 0.25), _label_top - 3)
                raw_crop = raw_crop.crop((0, 0, _w, _cut))
        except Exception:
            pass

        # ── Step 2: background-aware enhancement ────────────────────────────────
        crop = raw_crop
        try:
            from PIL import ImageEnhance, ImageStat

            stat = ImageStat.Stat(crop)
            r_mean, g_mean, b_mean = stat.mean[:3]
            gray_est = (r_mean + g_mean + b_mean) / 3
            chroma = max(
                abs(r_mean - gray_est),
                abs(g_mean - gray_est),
                abs(b_mean - gray_est),
            )
            is_chromatic = chroma > 12

            if is_chromatic:
                gray = crop.convert("L").convert("RGB")
                crop = Image.blend(gray, crop, alpha=0.10)
                crop = ImageEnhance.Contrast(crop).enhance(1.8)
                crop = ImageEnhance.Sharpness(crop).enhance(1.1)
            else:
                crop = ImageEnhance.Contrast(crop).enhance(1.5)
                crop = ImageEnhance.Sharpness(crop).enhance(1.2)
        except Exception:
            pass

        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _crop_sig_from_canvas(img: "Image.Image", fixture) -> str:
    """
    Crop the actual ink signature region(s) from the full-res PIL canvas.

    Mirrors _sync_crop_signature() logic in modules/cts/workflows/activities/signature.py:
    same PIL crop, same padding formula, same Otsu binarisation + morphological
    thinning — no network download needed because we have the canvas in memory.

    Pixel positions are the same constants used by _build() when it drew the boxes.
    """
    try:
        n  = _n_sigs(fixture)
        SH, SW = 95, 178
        ST = _ANNO_H + 358 + 8          # B=52, YL=B+358=410, ST=YL+8=418

        sx_right = _W - _MR - SW - 4   # rightmost sig box x-origin (1182)
        if n == 1:
            sx_left = sx_right
        elif n == 2:
            sx_left = sx_right - SW - 16
        else:
            sx_left = sx_right - 2 * (SW + 12)

        w, h = img.size
        pad  = max(6, int(min(w, h) * 0.02))   # same formula as _sync_crop_signature
        crop = img.crop((
            max(0, sx_left  - pad),
            max(0, ST       - pad),
            min(w, sx_right + SW + pad),
            min(h, ST + SH  + pad),
        ))

        # Otsu binarisation + morphological thinning — identical to
        # _apply_morphological_normalisation() in signature.py
        try:
            import cv2
            import numpy as np
            gray = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
            try:
                thinned = cv2.ximgproc.thinning(
                    binary, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN
                )
            except AttributeError:
                thinned = binary
            rgb_arr = cv2.cvtColor(cv2.bitwise_not(thinned), cv2.COLOR_GRAY2RGB)
            crop = Image.fromarray(rgb_arr)
        except ImportError:
            pass   # cv2 not installed — plain PIL crop is still useful

        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def generate_cheque_image(fixture, fixture_index: int = 0) -> tuple[str, str]:
    """
    Generate a synthetic CTS cheque image for the given fixture.

    Returns (cheque_b64, sig_crop_b64):
      cheque_b64   — full cheque downsampled to 50 % (700×350), JPEG q70
      sig_crop_b64 — signature region cropped from the live canvas using the
                     same pixel positions drawn by _build(), same Otsu/thinning
                     normalisation as _sync_crop_signature() in signature.py.
                     Empty string if PIL is unavailable.

    fixture_index accepted for API compatibility but unused.
    """
    if not _PIL_OK:
        return "", ""
    try:
        img      = _build(fixture)                  # full-res 1400×700 PIL RGB
        sig_b64  = _crop_sig_from_canvas(img, fixture)

        w, h = img.size
        img  = img.resize((w // 2, h // 2), Image.LANCZOS)
        buf  = io.BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=True)
        cheque_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return cheque_b64, sig_b64
    except Exception:
        return "", ""
