#!/usr/bin/env python3
"""ASTRA Demo - Cheque Image Generator

Generates synthetic bank-grade cheque images for all 50 demo customers.
Each cheque gets: front scan (PNG) + signature specimen (PNG).
Category C/D/E cheques have visible fraud artifacts — the core Vision LLM demo.

Requires: pip install Pillow
Run after: python demo/generate_seed_data.py
"""

import json
import math
import random
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
SEED_DIR = ROOT / "seed"
IMG_DIR = SEED_DIR / "images"
SIG_DIR = SEED_DIR / "signatures"

# Cheque canvas: standard Indian cheque ~8.5" x 3.5" at 188 dpi
CHQ_W, CHQ_H = 1600, 640
MICR_H = 80  # bottom MICR band height

# ----- colour constants -------------------------------------------------- #

WHITE = (255, 255, 255)
BLACK = (10, 10, 10)
OFF_WHITE = (248, 246, 238)          # aged paper
MICR_BG = (240, 240, 240)
LINE_GRAY = (170, 170, 170)
TEXT_DARK = (20, 20, 40)
TEXT_MED = (80, 80, 100)
RED_STAMP = (185, 28, 28)
TIPPEX = (245, 242, 230)             # correction-fluid colour
INK_FAINT = (160, 165, 190)         # faded original ink
INK_FRAUD = (15, 15, 60)            # over-written ink


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


# ----- font helpers ------------------------------------------------------- #

def _try_font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return None


def get_font(size: int, bold: bool = False, mono: bool = False):
    if mono:
        candidates = [
            "C:/Windows/Fonts/cour.ttf",
            "C:/Windows/Fonts/courbd.ttf",
            "courier.ttf",
            "LiberationMono-Regular.ttf",
        ]
    elif bold:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
            "arialbd.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/DejaVuSans.ttf",
            "arial.ttf",
        ]
    f = _try_font(candidates, size)
    return f if f else ImageFont.load_default()


# ----- signature generator ----------------------------------------------- #

def _draw_signature(draw: ImageDraw.ImageDraw, cx: int, cy: int, name: str,
                    seed: int = 0, mismatch: bool = False) -> None:
    """Draw a handwriting-style signature from a name string."""
    rng = random.Random(seed)
    w, h = 160, 60
    x0, y0 = cx - w // 2, cy - h // 2

    # Baseline
    base_y = y0 + int(h * 0.65)

    # Ink colour — slightly blue-black like a pen
    ink = (10, 10, 80) if not mismatch else (60, 10, 10)

    # Build control points from name characters
    initials = [c for c in name if c.isupper()][:3]
    if not initials:
        initials = list(name[:2].upper())

    # First letter loop
    pts = []
    steps = 24
    letter = initials[0] if initials else "S"
    amp = h * 0.35
    freq = 2.5 + rng.uniform(-0.5, 0.5) if not mismatch else 3.8
    for i in range(steps):
        t = i / (steps - 1)
        px = int(x0 + t * w * 0.45)
        py = int(base_y - amp * math.sin(freq * math.pi * t) * (1 - t * 0.4))
        pts.append((px, py))

    # Continuation tail
    tail_start_x = pts[-1][0]
    tail_pts = []
    for i in range(16):
        t = i / 15
        px = int(tail_start_x + t * (w * 0.55))
        wave = 8 if not mismatch else 15
        py = int(base_y - wave * math.sin(math.pi * t * 2) + rng.randint(-2, 2))
        tail_pts.append((px, py))

    all_pts = pts + tail_pts

    # Draw as polyline with slight width variation
    for i in range(len(all_pts) - 1):
        lw = rng.randint(1, 3)
        draw.line([all_pts[i], all_pts[i + 1]], fill=ink, width=lw)

    # Underline flourish
    y_under = base_y + 6
    draw.line([(x0 + 5, y_under), (x0 + w - 10, y_under)], fill=ink, width=1)


def generate_signature_specimen(customer_id: str, name: str, out_path: Path,
                                 mismatch: bool = False) -> None:
    seed = sum(ord(c) for c in customer_id)
    img = Image.new("RGB", (200, 80), color=WHITE)
    draw = ImageDraw.Draw(img)
    _draw_signature(draw, 100, 40, name, seed=seed, mismatch=mismatch)
    img.convert("L").save(out_path)


# ----- cheque layout drawing --------------------------------------------- #

def draw_base_cheque(bank: dict, cheque: dict) -> Image.Image:
    """Render a clean cheque with all standard fields."""
    img = Image.new("RGB", (CHQ_W, CHQ_H), OFF_WHITE)
    draw = ImageDraw.Draw(img)

    primary = hex_to_rgb(bank["color_primary"])
    accent = hex_to_rgb(bank["color_accent"])

    # ---------- header band ------------------------------------------ #
    header_h = 105
    draw.rectangle([(0, 0), (CHQ_W, header_h)], fill=primary)

    # Bank name
    fn_bank = get_font(26, bold=True)
    draw.text((22, 12), bank["name"], font=fn_bank, fill=WHITE)

    # Tagline / branch
    fn_branch = get_font(15)
    draw.text((22, 46), bank["branch"], font=fn_branch, fill=(*accent,))
    draw.text((22, 68),
              f"IFSC: {bank['ifsc_prefix']}0000001  |  MICR: {bank['micr_code']}",
              font=fn_branch, fill=(200, 200, 200))

    # CTS 2010 badge (upper-right)
    draw.rectangle([(CHQ_W - 130, 10), (CHQ_W - 10, 40)], outline=accent, width=2)
    draw.text((CHQ_W - 122, 16), "CTS 2010", font=get_font(14, bold=True), fill=(*accent,))

    # A/c Payee box
    draw.rectangle([(CHQ_W - 165, 48), (CHQ_W - 10, 96)],
                   outline=(*accent,), width=1, fill=(*primary, 180))
    draw.text((CHQ_W - 158, 58), "A/C PAYEE", font=get_font(13, bold=True), fill=WHITE)
    draw.text((CHQ_W - 158, 76), "NOT NEGOTIABLE", font=get_font(11), fill=(200, 200, 200))

    # ---------- date box --------------------------------------------- #
    date_x, date_y = CHQ_W - 280, header_h + 18
    draw.text((date_x - 50, date_y + 3), "Date:", font=get_font(15, bold=True),
              fill=TEXT_DARK)
    # Date boxes: D D / M M / Y Y Y Y
    bw, bh = 26, 28
    gap = 4
    dx = date_x
    for i, char in enumerate("DD/MM/YYYY"):
        if char == "/":
            draw.text((dx + 3, date_y), "/", font=get_font(18, bold=True), fill=TEXT_DARK)
            dx += 14
        else:
            draw.rectangle([(dx, date_y), (dx + bw, date_y + bh)],
                           outline=LINE_GRAY, width=1)
            dx += bw + gap

    # Write actual date digits into boxes
    date_str = cheque["cheque_date"]   # dd-mm-yyyy
    parts = date_str.split("-")
    if len(parts) == 3:
        date_digits = parts[0] + parts[1] + parts[2]
    else:
        date_digits = "12052026"

    dx = date_x
    digit_idx = 0
    fn_date = get_font(17, bold=True)
    for char in "DD/MM/YYYY":
        if char == "/":
            dx += 14
        else:
            if digit_idx < len(date_digits):
                draw.text((dx + 6, date_y + 4), date_digits[digit_idx],
                          font=fn_date, fill=TEXT_DARK)
                digit_idx += 1
            dx += bw + gap

    # ---------- pay line --------------------------------------------- #
    pay_y = header_h + 70
    draw.text((22, pay_y), "Pay:", font=get_font(15, bold=True), fill=TEXT_DARK)
    draw.line([(78, pay_y + 18), (CHQ_W - 20, pay_y + 18)], fill=LINE_GRAY, width=1)
    # Payee name
    fn_pay = get_font(19, bold=False)
    payee = cheque.get("payee_name", "")
    draw.text((82, pay_y - 2), payee, font=fn_pay, fill=TEXT_DARK)

    # ---------- amount words line ------------------------------------- #
    words_y = header_h + 125
    draw.text((22, words_y), "Rupees:", font=get_font(15, bold=True), fill=TEXT_DARK)
    draw.line([(102, words_y + 18), (CHQ_W - 20, words_y + 18)],
              fill=LINE_GRAY, width=1)
    fn_words = get_font(18)
    words = cheque.get("amount_words", "")
    draw.text((106, words_y - 1), words + " Only", font=fn_words, fill=TEXT_DARK)

    # ---------- Rs. figure box --------------------------------------- #
    rs_x, rs_y = 22, header_h + 175
    draw.text((rs_x, rs_y), "Rs.", font=get_font(17, bold=True), fill=TEXT_DARK)
    fig_box_x = rs_x + 40
    draw.rectangle([(fig_box_x, rs_y - 2), (fig_box_x + 220, rs_y + 32)],
                   outline=LINE_GRAY, width=1)
    amount = cheque.get("amount_figures", 0)
    fn_amount = get_font(22, bold=True)
    draw.text((fig_box_x + 8, rs_y + 1), f"{amount:,.2f}", font=fn_amount, fill=TEXT_DARK)

    # ---------- cheque number ---------------------------------------- #
    draw.text((22, header_h + 225),
              f"Cheque No: {cheque.get('serial_number', '')}",
              font=get_font(13), fill=TEXT_MED)
    draw.text((22, header_h + 244),
              f"A/c: {cheque.get('presentee_account', '')}",
              font=get_font(13), fill=TEXT_MED)

    # ---------- signature area --------------------------------------- #
    sig_box_x = CHQ_W - 280
    sig_box_y = header_h + 155
    draw.rectangle([(sig_box_x, sig_box_y), (CHQ_W - 22, sig_box_y + 95)],
                   outline=LINE_GRAY, width=1)
    draw.text((sig_box_x + 10, sig_box_y + 75), "Authorised Signature",
              font=get_font(12), fill=TEXT_MED)

    # ---------- MICR band -------------------------------------------- #
    micr_top = CHQ_H - MICR_H
    draw.rectangle([(0, micr_top), (CHQ_W, CHQ_H)], fill=MICR_BG)
    draw.line([(0, micr_top), (CHQ_W, micr_top)], fill=LINE_GRAY, width=1)

    micr_raw = cheque.get("micr_line", "")
    # Replace MICR special Unicode chars with readable equivalents
    micr_display = (micr_raw
                    .replace("⑈", " [AMOUNT] ")
                    .replace("⑆", " [BSB] ")
                    .replace("⑉", " [ONUS] "))
    fn_micr = get_font(20, mono=True)
    draw.text((40, micr_top + 22), micr_display, font=fn_micr, fill=(40, 40, 40))

    # Horizontal border lines
    draw.rectangle([(2, 2), (CHQ_W - 2, CHQ_H - 2)], outline=LINE_GRAY, width=2)

    return img


def apply_cat_c_overwrite(img: Image.Image, cheque: dict) -> Image.Image:
    """Overwritten amount (Cat C): show original amount in faded ink,
    Tipp-Ex rectangle over it, fraud amount in fresh dark ink on top."""
    draw = ImageDraw.Draw(img)
    header_h = 105

    fig_box_x = 62
    rs_y = header_h + 175

    orig_amount = cheque.get("ocr_vs_vision", {}).get("vision_reads_original_amount", 0)
    fraud_amount = cheque.get("amount_figures", 0)

    # Erase the clean amount drawn by base function
    draw.rectangle([(fig_box_x, rs_y - 2), (fig_box_x + 220, rs_y + 32)],
                   fill=OFF_WHITE, outline=LINE_GRAY, width=1)

    # 1) faint original writing underneath
    fn_faint = get_font(22, bold=True)
    draw.text((fig_box_x + 8, rs_y + 1), f"{orig_amount:,.2f}",
              font=fn_faint, fill=INK_FAINT)

    # 2) Tipp-Ex band over the original — slightly imperfect rectangle
    tippex_y1 = rs_y - 1
    tippex_y2 = rs_y + 30
    draw.rectangle([(fig_box_x + 4, tippex_y1), (fig_box_x + 210, tippex_y2)],
                   fill=TIPPEX)
    # Rough edges
    for offset in range(0, 8):
        alpha = 255 - offset * 25
        draw.line(
            [(fig_box_x + 4, tippex_y1 - offset),
             (fig_box_x + 210, tippex_y1 - offset)],
            fill=(*TIPPEX, alpha) if len(TIPPEX) == 4 else TIPPEX,
            width=1,
        )

    # 3) fraud amount in fresh dark ink
    fn_fraud = get_font(22, bold=True)
    draw.text((fig_box_x + 8, rs_y + 1), f"{fraud_amount:,.2f}",
              font=fn_fraud, fill=INK_FRAUD)

    # Annotation (Vision LLM would detect this)
    fn_ann = get_font(11)
    draw.text((fig_box_x, rs_y + 38),
              "^ ink layer anomaly (Vision LLM detects overwrite)",
              font=fn_ann, fill=(180, 60, 60))

    return img


def apply_cat_d_date_tamper(img: Image.Image, cheque: dict) -> Image.Image:
    """Tampered date (Cat D): year digits show Tipp-Ex + re-written year."""
    draw = ImageDraw.Draw(img)
    header_h = 105

    orig_year = str(cheque.get("ocr_vs_vision", {}).get("original_year", "2024"))
    new_year = str(cheque.get("ocr_vs_vision", {}).get("new_year", "2026"))

    date_x = CHQ_W - 280
    date_y = header_h + 18
    bw, bh = 26, 28
    gap = 4

    # Calculate position of year digits (positions 4-7 in "DD/MM/YYYY")
    # skip: DD (2 boxes) + / (14px) + MM (2 boxes) + / (14px) = year starts here
    year_x_start = date_x + 2 * (bw + gap) + 14 + 2 * (bw + gap) + 14

    # Tipp-Ex over year area
    yr_w = 4 * (bw + gap)
    draw.rectangle(
        [(year_x_start - 2, date_y - 2), (year_x_start + yr_w, date_y + bh + 2)],
        fill=TIPPEX,
    )

    # Faint original year underneath
    fn_y = get_font(17, bold=True)
    for i, d in enumerate(orig_year):
        draw.text((year_x_start + i * (bw + gap) + 6, date_y + 4),
                  d, font=fn_y, fill=INK_FAINT)

    # Re-drawn new year in fresh ink
    for i, d in enumerate(new_year):
        draw.text((year_x_start + i * (bw + gap) + 6, date_y + 4),
                  d, font=fn_y, fill=INK_FRAUD)

    # Annotation
    fn_ann = get_font(11)
    draw.text((date_x - 50, date_y + 35),
              "^ correction fluid + re-ink detected by Vision LLM",
              font=fn_ann, fill=(180, 60, 60))

    return img


def apply_cat_e_cancelled(img: Image.Image) -> Image.Image:
    """CANCELLED stamp (Cat E): red diagonal text overlay across the face."""
    draw = ImageDraw.Draw(img)

    # Red border
    draw.rectangle([(4, 4), (CHQ_W - 4, CHQ_H - MICR_H - 4)],
                   outline=RED_STAMP, width=3)

    # Two diagonal lines
    draw.line([(30, 30), (CHQ_W - 30, CHQ_H - MICR_H - 30)],
              fill=(*RED_STAMP, 180), width=3)
    draw.line([(CHQ_W - 30, 30), (30, CHQ_H - MICR_H - 30)],
              fill=(*RED_STAMP, 180), width=3)

    # Big "CANCELLED" text at angle — draw on overlay then paste
    overlay = Image.new("RGBA", (CHQ_W, CHQ_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fn_cancel = get_font(88, bold=True)
    od.text((180, 190), "CANCELLED", font=fn_cancel,
            fill=(*RED_STAMP, 160))
    rotated = overlay.rotate(18, expand=False)
    img = img.convert("RGBA")
    img.alpha_composite(rotated)
    img = img.convert("RGB")

    # Annotation
    draw2 = ImageDraw.Draw(img)
    fn_ann = get_font(12)
    draw2.text((22, CHQ_H - MICR_H - 28),
               "VOID INSTRUMENT — OCR reads text fields as valid; Vision LLM detects stamp overlay",
               font=fn_ann, fill=RED_STAMP)

    return img


def apply_cat_h_quality(img: Image.Image) -> Image.Image:
    """CTS quality issue (Cat H): skew + blur + noise."""
    # Slight rotation (skew)
    img = img.rotate(2.5, fillcolor=WHITE, expand=False)
    # Blur
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    # Reduce contrast slightly (brightness noise)
    from PIL import ImageEnhance
    img = ImageEnhance.Contrast(img).enhance(0.85)
    return img


def write_signature_in_box(img: Image.Image, cheque: dict,
                            mismatch: bool = False) -> Image.Image:
    """Draw customer signature inside the signature box."""
    draw = ImageDraw.Draw(img)
    header_h = 105
    sig_box_x = CHQ_W - 280
    sig_box_y = header_h + 155
    cx = sig_box_x + 129
    cy = sig_box_y + 38

    seed = sum(ord(c) for c in cheque.get("customer_id", "X"))
    _draw_signature(draw, cx, cy, cheque.get("customer_name", "X"),
                    seed=seed, mismatch=mismatch)
    return img


# ----- per-category processing ------------------------------------------- #

CATEGORY_MISMATCH_SIG = {"I"}
CATEGORY_NO_PRESENTEE = {"C", "D", "E", "F", "G", "H"}


def process_cheque(cheque: dict, bank: dict, out_dir: Path) -> None:
    cat = cheque.get("category", "A")
    cheque_id = cheque["cheque_id"]

    img = draw_base_cheque(bank, cheque)

    # Category-specific fraud overlays
    if cat == "C":
        img = apply_cat_c_overwrite(img, cheque)
    elif cat == "D":
        img = apply_cat_d_date_tamper(img, cheque)
    elif cat == "E":
        img = apply_cat_e_cancelled(img)
    elif cat == "H":
        img = apply_cat_h_quality(img)

    # Write signature
    is_sig_mismatch = cat == "I"
    img = write_signature_in_box(img, cheque, mismatch=is_sig_mismatch)

    # Save colour version
    img.save(out_dir / f"{cheque_id}.png")

    # Save grayscale (BW scan simulation)
    bw = img.convert("L")
    bw.save(out_dir / f"{cheque_id}_bw.png")


# ----- main --------------------------------------------------------------- #

def main():
    # Load seed data
    banks_map = {b["bank_id"]: b for b in
                 json.loads((SEED_DIR / "banks.json").read_text(encoding="utf-8"))}
    cheques = json.loads((SEED_DIR / "cheques.json").read_text(encoding="utf-8"))
    customers = json.loads((SEED_DIR / "customers.json").read_text(encoding="utf-8"))
    cust_map = {c["customer_id"]: c for c in customers}

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    SIG_DIR.mkdir(parents=True, exist_ok=True)

    print("ASTRA Demo - Image Generator")
    print("=" * 50)

    # 1. Generate cheque images
    print(f"Generating {len(cheques)} cheque images...")
    cats_done = {}
    for chq in cheques:
        bank_id = chq["presentee_bank_id"]
        bank = banks_map[bank_id]
        process_cheque(chq, bank, IMG_DIR)
        cat = chq["category"]
        cats_done[cat] = cats_done.get(cat, 0) + 1

    for cat in sorted(cats_done):
        print(f"  Cat {cat}: {cats_done[cat]} images")
    print(f"  [OK] Cheque images -> {IMG_DIR}")

    # 2. Generate signature specimens
    print(f"Generating {len(customers)} signature specimens...")
    for cust in customers:
        cid = cust["customer_id"]
        name = cust["name"]
        # Standard specimen
        generate_signature_specimen(cid, name, SIG_DIR / f"{cid}.png", mismatch=False)
        # For Cat I customers also save an "alternate" (what appears on the cheque)
        if cust.get("category") == "I":
            generate_signature_specimen(
                cid + "_mismatch", name, SIG_DIR / f"{cid}_on_cheque.png",
                mismatch=True
            )

    print(f"  [OK] Signatures -> {SIG_DIR}")

    # 3. Build image manifest (maps cheque_id to image paths)
    manifest = {}
    for chq in cheques:
        cid = chq["cheque_id"]
        manifest[cid] = {
            "cheque_image": f"images/{cid}.png",
            "cheque_image_bw": f"images/{cid}_bw.png",
            "signature_specimen": f"signatures/{chq['customer_id']}.png",
            "category": chq["category"],
            "bank_id": chq["presentee_bank_id"],
        }
    (SEED_DIR / "image_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("  [OK] image_manifest.json")

    total = len(cheques) * 2 + len(customers)
    print(f"\nDone -- {total} image files generated in demo/seed/")
    print("Next: docker-compose up (see demo/docker/)")


if __name__ == "__main__":
    main()
