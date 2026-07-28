"""
Standalone sig detector debugger — run without any services.

Usage:
    python debug_sig.py path/to/cheque.jpg

Saves:
    debug_zone.png        — raw zone crop
    debug_ink.png         — ink mask at computed threshold
    debug_rows.png        — qualifying rows highlighted in green
    debug_result.png      — final bbox drawn on original image

Prints threshold, row count, cluster count to console.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── import detector functions from the service ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from apps.sig_detector.main import _ink_threshold, _detect_pixel


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
    zone.save("debug_zone.png")
    print(f"Zone:  x=[{zx1},{zx2}]  y=[{zy1},{zy2}]  size={zw}×{zh}")

    # Ink mask
    gray_img = zone.convert("L").filter(ImageFilter.MedianFilter(size=3))
    gray = np.array(gray_img)
    thr = _ink_threshold(gray)
    p3  = int(np.percentile(gray.flatten(), 3))
    print(f"p3={p3}  threshold={thr}  MIN_SPAN={max(8,int(zw*0.05))}")

    ink = (gray < thr).astype(np.uint8)
    ink_img = Image.fromarray(ink * 255, mode="L")
    ink_img.save("debug_ink.png")

    # Qualifying rows
    MIN_SPAN    = max(8, int(zw * 0.05))   # match main.py: 5 %
    MAX_DENSITY = 0.40
    MAX_RUNS    = 15
    MERGE_GAP   = 15
    MIN_ROWS    = 2

    sig_rows = []
    reject_span = reject_density = reject_runs = 0
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
        sig_rows.append((y, int(o_xs[0]), int(o_xs[-1])))

    print(f"Rows with ink: {(ink.sum(axis=1)>0).sum()}")
    print(f"Qualifying rows: {len(sig_rows)}  "
          f"(rejected: span={reject_span}, density={reject_density}, runs={reject_runs})")

    # Draw qualifying rows on zone
    zone_dbg = zone.copy()
    draw = ImageDraw.Draw(zone_dbg)
    for (y, lx, rx) in sig_rows:
        draw.line([(lx, y), (rx, y)], fill=(0, 220, 0), width=1)
    zone_dbg.save("debug_rows.png")

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

    left   = min(r[1] for r in best)
    top    = min(r[0] for r in best)
    right  = max(r[2] for r in best)
    bottom = max(r[0] for r in best) + 1

    # Draw on original
    abs_x1 = (zx1+left)/iw;  abs_y1 = (zy1+top)/ih
    abs_x2 = (zx1+right)/iw; abs_y2 = (zy1+bottom)/ih
    result = [round(abs_x1,4), round(abs_y1,4), round(abs_x2,4), round(abs_y2,4)]
    print(f"BBox (normalised): {result}")

    img_draw = img.copy()
    draw2 = ImageDraw.Draw(img_draw)
    draw2.rectangle([zx1, zy1, zx2, zy2], outline=(100,100,255), width=2)  # zone (blue)
    draw2.rectangle(
        [int(abs_x1*iw), int(abs_y1*ih), int(abs_x2*iw), int(abs_y2*ih)],
        outline=(0,220,0), width=3  # bbox (green)
    )
    img_draw.save("debug_result.png")
    print("Saved: debug_zone.png  debug_ink.png  debug_rows.png  debug_result.png")

    # Also call the real detector to confirm
    det = _detect_pixel(img)
    print(f"\n_detect_pixel() returned: {det}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_sig.py <cheque_image.jpg>")
        sys.exit(1)
    debug(sys.argv[1])
