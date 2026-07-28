"""
Standalone sig detector debugger — run without any services.

Usage:
    python debug_sig.py path/to/cheque.jpg

Saves (JPEG, max 1400 px wide):
    debug_zone.jpg        — raw zone crop
    debug_ink.jpg         — local-contrast ink mask
    debug_rows.jpg        — qualifying rows highlighted in green
    debug_result.jpg      — final bbox drawn on original image

Prints threshold, row count, cluster count to console.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── import detector functions from the service ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from apps.sig_detector.main import _detect_pixel

CONTRAST_THRESH = 35   # must match _detect_pixel in main.py
BLUR_RADIUS     = 15   # must match _detect_pixel in main.py

MAX_W = 1400           # max output image width (keeps file sizes small)


def _save(img: Image.Image, path: str, quality: int = 82) -> None:
    if img.width > MAX_W:
        scale = MAX_W / img.width
        img = img.resize((MAX_W, int(img.height * scale)), Image.LANCZOS)
    img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    print(f"  Saved {path}  ({img.width}×{img.height})")


def debug(img_path: str) -> None:
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size
    print(f"\n=== {Path(img_path).name} ===")
    print(f"Image size: {iw} × {ih}")

    # Zone
    zy1 = int(ih * 0.55);  zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52);  zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size
    _save(zone, "debug_zone.jpg")
    print(f"Zone:  x=[{zx1},{zx2}]  y=[{zy1},{zy2}]  size={zw}×{zh}")

    # Local-contrast ink mask (mirrors _detect_pixel in main.py)
    gray_raw = np.array(zone.convert("L"))
    blurred  = np.array(zone.convert("L").filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS)))
    contrast = blurred.astype(int) - gray_raw.astype(int)
    ink = (contrast > CONTRAST_THRESH).astype(np.uint8)

    # For display: show contrast as a grey image (clamp 0-80 → 0-255)
    contrast_vis = np.clip(contrast, 0, 80) * 3
    _save(Image.fromarray(contrast_vis.astype(np.uint8), mode="L"), "debug_ink.jpg")

    mean_contrast = contrast[contrast > 0].mean() if (contrast > 0).any() else 0
    print(f"Contrast thresh={CONTRAST_THRESH}  mean(positive)={mean_contrast:.1f}")

    # Qualifying rows (mirrors main.py guards)
    MIN_SPAN    = max(8, int(zw * 0.05))
    MAX_DENSITY = 0.40
    MAX_RUNS    = 15
    MERGE_GAP   = 10
    MIN_ROWS    = 2
    RIGHT_FRINGE = max(4, int(zw * 0.08))   # Guard E: rightmost 8% = barcode fringe

    sig_rows = []
    reject_span = reject_density = reject_runs = reject_fringe = 0
    for y in range(zh):
        o_xs = np.where(ink[y])[0]
        if len(o_xs) == 0:
            continue
        span    = int(o_xs[-1]) - int(o_xs[0])
        density = len(o_xs) / zw
        if span < MIN_SPAN:
            reject_span += 1; continue
        if density > MAX_DENSITY:
            reject_density += 1; continue
        runs = 1
        for i in range(1, len(o_xs)):
            if int(o_xs[i]) - int(o_xs[i-1]) > 3:
                runs += 1
        if runs > MAX_RUNS:
            reject_runs += 1; continue

        # Guard D: ink must be DENSE within its span (security print letters
        # scatter a few blobs across 1100 px → 2-4 % span density; signature
        # strokes are concentrated → 15-50 % span density)
        span_density = len(o_xs) / (span + 1)
        if span_density < 0.08:
            continue

        # Guard E: clip barcode / right-margin ink from the right end of every row.
        # Barcode stripes overlap signature y-positions, so a single row can have
        # ink at the signature location AND the barcode location.  Strip any ink
        # in the rightmost RIGHT_FRINGE pixels before recording right_x.
        fringe_boundary = zw - RIGHT_FRINGE
        o_xs_core = o_xs[o_xs < fringe_boundary]
        if len(o_xs_core) == 0:
            reject_fringe += 1; continue   # entire row is fringe/barcode

        sig_rows.append((y, int(o_xs[0]), int(o_xs_core[-1])))

    print(f"Rows with ink: {(ink.sum(axis=1)>0).sum()}")
    print(f"Qualifying rows: {len(sig_rows)}  "
          f"(rejected: span={reject_span}, density={reject_density}, "
          f"runs={reject_runs}, fringe={reject_fringe})")

    # Draw qualifying rows on zone
    zone_dbg = zone.copy()
    draw = ImageDraw.Draw(zone_dbg)
    for (y, lx, rx) in sig_rows:
        draw.line([(lx, y), (rx, y)], fill=(0, 220, 0), width=1)
    _save(zone_dbg, "debug_rows.jpg")

    if not sig_rows:
        print("→ No qualifying rows — returning []")
        return

    # Clusters
    clusters = []
    cur = [sig_rows[0]]
    for i in range(1, len(sig_rows)):
        if sig_rows[i][0] - sig_rows[i-1][0] <= MERGE_GAP:
            cur.append(sig_rows[i])
        else:
            clusters.append(cur); cur = [sig_rows[i]]
    clusters.append(cur)

    qualifying = [c for c in clusters if len(c) >= MIN_ROWS]
    if not qualifying:
        qualifying = [max(clusters, key=len)]
        print(f"⚠ No cluster with ≥{MIN_ROWS} rows — using largest ({len(qualifying[0])} rows)")

    print(f"Clusters: {len(clusters)}  qualifying: {len(qualifying)}")
    best = max(qualifying, key=len)
    print(f"Best cluster: rows {best[0][0]}–{best[-1][0]}  "
          f"({len(best)} rows)  y_zone={best[-1][0]}/{zh} ({best[-1][0]/zh*100:.0f}%)")

    # Trim far-left outlier rows (border lines, background text)
    lefts_s = sorted(r[1] for r in best)
    gap_thresh = int(zw * 0.15)
    max_gap = gap_idx = 0
    for i in range(len(lefts_s) - 1):
        g = lefts_s[i + 1] - lefts_s[i]
        if g > max_gap:
            max_gap, gap_idx = g, i + 1
    left = lefts_s[gap_idx] if (len(lefts_s) >= 4 and max_gap > gap_thresh) else lefts_s[0]
    if len(lefts_s) >= 4 and max_gap > gap_thresh:
        print(f"  ↳ left trimmed: largest gap={max_gap}px at idx={gap_idx}  "
              f"raw_min={lefts_s[0]}  trimmed_left={left}")

    # Trim far-right outlier rows (barcode stripes at zone right edge)
    rights_s = sorted(r[2] for r in best)
    r_gap_thresh = int(zw * 0.15)
    r_max_gap = r_max_gap_idx = 0
    for i in range(len(rights_s) - 1):
        g = rights_s[i + 1] - rights_s[i]
        if g > r_max_gap:
            r_max_gap, r_max_gap_idx = g, i + 1
    if (len(rights_s) >= 4 and r_max_gap > r_gap_thresh
            and r_max_gap_idx > len(rights_s) // 2):
        right = rights_s[r_max_gap_idx - 1]
        print(f"  ↳ right trimmed: largest gap={r_max_gap}px at idx={r_max_gap_idx}  "
              f"raw_max={rights_s[-1]}  trimmed_right={right}")
    else:
        right = rights_s[-1]

    top    = min(r[0] for r in best)
    bottom = max(r[0] for r in best) + 1

    abs_x1 = (zx1+left)/iw;  abs_y1 = (zy1+top)/ih
    abs_x2 = (zx1+right)/iw; abs_y2 = (zy1+bottom)/ih
    result = [round(abs_x1,4), round(abs_y1,4), round(abs_x2,4), round(abs_y2,4)]
    print(f"BBox (normalised): {result}")

    img_draw = img.copy()
    draw2 = ImageDraw.Draw(img_draw)
    draw2.rectangle([zx1, zy1, zx2, zy2], outline=(100,100,255), width=3)
    draw2.rectangle(
        [int(abs_x1*iw), int(abs_y1*ih), int(abs_x2*iw), int(abs_y2*ih)],
        outline=(0,220,0), width=4
    )
    _save(img_draw, "debug_result.jpg", quality=85)

    # Also call the real detector to confirm
    det = _detect_pixel(img)
    print(f"\n_detect_pixel() returned: {det}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_sig.py <cheque_image.jpg>")
        sys.exit(1)
    debug(sys.argv[1])
