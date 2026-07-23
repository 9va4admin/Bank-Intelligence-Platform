"""
Standalone CLI tool — signature extraction + denoising.

Usage:
    python tools/sig_clean.py path/to/cheque.jpg

Output:
    <same-dir>/sig_clean.png   — denoised signature crop
    prints blob stats so you can see exactly what was kept / removed

No FastAPI, no HF token, no Docker needed.
"""
import sys
import io
from pathlib import Path

try:
    import numpy as np
    import cv2
    from PIL import Image
except ImportError as e:
    sys.exit(f"Missing dependency: {e}\nRun: pip install pillow numpy opencv-python")

# ── 1. Pixel sig detector (mirrors apps/sig_detector/main.py) ──────────────

def _ink_threshold(arr: np.ndarray) -> int:
    p10 = int(np.percentile(arr.flatten(), 10))
    return max(60, min(150, p10 + 28))


def _detect_pixel(img: Image.Image) -> list[dict]:
    """Find signature bbox via ink-row density profiling."""
    iw, ih = img.size
    zy1 = int(ih * 0.52)
    zy2 = int(ih * 0.90)
    zx1 = int(iw * 0.52)
    zx2 = iw
    zone = img.crop((zx1, zy1, zx2, zy2))
    zw, zh = zone.size

    gray = np.array(zone.convert("L"))
    thr  = _ink_threshold(gray)
    ink  = (gray < thr).astype(np.uint8)

    row_density = ink.sum(axis=1) / zw
    ink_rows    = row_density > 0.01

    # Gap >= 5 blank rows where < 30% of total ink remains below.
    total_ink2    = max(1, int(ink_rows.sum()))
    ink_rows_seen2 = 0
    gap_start2     = None
    gap_len2       = 0
    sig_bottom     = zh

    for y, has_ink in enumerate(ink_rows):
        if has_ink:
            ink_rows_seen2 += 1
            gap_start2 = None
            gap_len2   = 0
        else:
            if gap_start2 is None:
                gap_start2 = y
                gap_len2   = 0
            gap_len2 += 1
            if ink_rows_seen2 >= 4 and gap_len2 >= 5:
                ink_below2 = int(ink_rows[y + 1:].sum())
                if ink_below2 / total_ink2 < 0.30:
                    sig_bottom = gap_start2
                    break

    ink_above = ink[:sig_bottom, :]
    coords = np.argwhere(ink_above)
    if coords.size == 0:
        return []

    top    = int(coords[:, 0].min())
    bottom = int(coords[:, 0].max()) + 1
    left   = int(coords[:, 1].min())
    right  = int(coords[:, 1].max()) + 1
    if bottom - top < 5 or right - left < 10:
        return []

    return [{"bbox": [
        (zx1 + left)   / iw,
        (zy1 + top)    / ih,
        (zx1 + right)  / iw,
        (zy1 + bottom) / ih,
    ], "confidence": 0.80}]


# ── 2. Denoiser (mirrors apps/api/routers/demo_cloud_extract.py) ───────────

def _denoise(crop: Image.Image, verbose: bool = True) -> Image.Image:
    arr  = np.array(crop.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    cw, ch = crop.width, crop.height

    # ── Stage 1: row-density gap detection (hard cut) ────────────────────
    ink_mask    = (gray < 180).astype(np.uint8)
    row_density = ink_mask.sum(axis=1) / max(cw, 1)
    ink_rows    = row_density > 0.005

    # Gap >= 5 blank rows where < 30% of total ink remains below.
    total_ink = max(1, int(ink_rows.sum()))
    ink_rows_seen = 0
    gap_start_cur = None
    gap_len_cur   = 0
    cut_row       = ch

    for y, has_ink in enumerate(ink_rows):
        if has_ink:
            ink_rows_seen += 1
            gap_start_cur = None
            gap_len_cur   = 0
        else:
            if gap_start_cur is None:
                gap_start_cur = y
                gap_len_cur   = 0
            gap_len_cur += 1
            if ink_rows_seen >= 4 and gap_len_cur >= 5:
                ink_below = int(ink_rows[y + 1:].sum())
                if ink_below / total_ink < 0.30:
                    cut_row = gap_start_cur
                    break

    gap_cut = cut_row < ch
    if gap_cut:
        arr[cut_row:, :] = 255
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    if verbose:
        print(f"\n  Crop size : {cw} x {ch} px")
        if gap_cut:
            print(f"  Gap detected  : row {cut_row} (len {gap_len_cur}) — blanked below")
        else:
            print(f"  Gap detection : no clear gap found, using component filter only")

    # ── Stage 2: connected-component noise filter ─────────────────────────
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    max_area = 0
    for i in range(1, num_labels):
        area   = int(stats[i, cv2.CC_STAT_AREA])
        comp_w = int(stats[i, cv2.CC_STAT_WIDTH])
        comp_h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if comp_w > cw * 0.50 and comp_h < 8:
            continue
        if area > max_area:
            max_area = area

    keep_min = max(80, int(max_area * 0.12))

    if verbose:
        print(f"  Largest blob : {max_area} px  |  keep_min : >= {keep_min} px")
        print(f"\n  {'Blob':>4}  {'area':>6}  {'centroid_y':>10}  {'action':>8}")
        print(f"  {'----':>4}  {'------':>6}  {'----------':>10}  {'--------':>8}")

    output = np.full_like(arr, 255)
    for i in range(1, num_labels):
        area   = int(stats[i, cv2.CC_STAT_AREA])
        comp_w = int(stats[i, cv2.CC_STAT_WIDTH])
        comp_h = int(stats[i, cv2.CC_STAT_HEIGHT])
        cy     = float(centroids[i][1])

        if comp_w > cw * 0.50 and comp_h < 8:
            if verbose:
                print(f"  {i:>4}  {area:>6}  {cy:>10.1f}  {'RULE/DISCARD':>8}")
            continue

        action = "KEEP" if area >= keep_min else "REMOVE"
        if verbose:
            print(f"  {i:>4}  {area:>6}  {cy:>10.1f}  {action:>8}")

        if area >= keep_min:
            mask = labels == i
            output[mask] = arr[mask]

    return Image.fromarray(output.astype(np.uint8))


# ── 3. CLI entry point ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python tools/sig_clean.py <cheque_image_path>")

    src = Path(sys.argv[1])
    if not src.exists():
        sys.exit(f"File not found: {src}")

    print(f"Input : {src}")
    img = Image.open(src).convert("RGB")
    iw, ih = img.size
    print(f"Image size: {iw} x {ih} px")

    # Detect
    detections = _detect_pixel(img)
    if not detections:
        sys.exit("No signature region detected.")

    bbox = detections[0]["bbox"]
    x1, y1, x2, y2 = bbox
    print(f"\nDetected bbox (normalised): x1={x1:.3f} y1={y1:.3f} x2={x2:.3f} y2={y2:.3f}")

    cx1 = max(0,  int((x1 - 0.01) * iw))
    cy1 = max(0,  int((y1 - 0.008) * ih))
    cx2 = min(iw, int((x2 + 0.01) * iw))
    cy2 = min(ih, int((y2 + 0.008) * ih))
    crop = img.crop((cx1, cy1, cx2, cy2))
    print(f"Crop pixel box: ({cx1},{cy1}) to ({cx2},{cy2})")

    # Save raw crop for comparison
    raw_out = src.parent / "sig_raw_crop.png"
    crop.save(raw_out)
    print(f"\nRaw crop saved : {raw_out}")

    # Denoise
    print("\nRunning denoiser...")
    clean = _denoise(crop, verbose=True)

    out = src.parent / "sig_clean.png"
    clean.save(out)
    print(f"\nClean sig saved: {out}")


if __name__ == "__main__":
    main()
