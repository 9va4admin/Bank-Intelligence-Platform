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

    best_start = best_len = 0
    cur_start  = cur_len  = 0
    in_gap = False
    for y, has_ink in enumerate(ink_rows):
        if not has_ink:
            if not in_gap:
                cur_start, cur_len, in_gap = y, 0, True
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start = cur_len, cur_start
        else:
            in_gap = False

    sig_bottom = zh
    if best_len >= 1:
        ink_above = ink_rows[:best_start].sum()
        if ink_above >= 6:
            sig_bottom = best_start

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
    _, binary = cv2.threshold(gray, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    cw, ch = crop.width, crop.height
    name_zone_y = ch * 0.72

    # Pass 1: largest non-rule blob
    max_area = 0
    for i in range(1, num_labels):
        area   = int(stats[i, cv2.CC_STAT_AREA])
        comp_w = int(stats[i, cv2.CC_STAT_WIDTH])
        comp_h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if comp_w > cw * 0.50 and comp_h < 8:
            continue
        if area > max_area:
            max_area = area

    keep_upper = max(150, int(max_area * 0.15))
    keep_lower = max(150, int(max_area * 0.45))

    if verbose:
        print(f"\n  Crop size : {cw} x {ch} px")
        print(f"  name_zone_y boundary : y >= {name_zone_y:.1f} px")
        print(f"  Largest blob : {max_area} px")
        print(f"  keep_upper (y<{name_zone_y:.0f}) : >= {keep_upper} px")
        print(f"  keep_lower (y>={name_zone_y:.0f}) : >= {keep_lower} px")
        print(f"\n  {'Blob':>4}  {'area':>6}  {'centroid_y':>10}  {'zone':>8}  {'threshold':>10}  {'action':>8}")
        print(f"  {'----':>4}  {'------':>6}  {'----------':>10}  {'--------':>8}  {'----------':>10}  {'--------':>8}")

    output = np.full_like(arr, 255)
    for i in range(1, num_labels):
        area      = int(stats[i, cv2.CC_STAT_AREA])
        comp_w    = int(stats[i, cv2.CC_STAT_WIDTH])
        comp_h    = int(stats[i, cv2.CC_STAT_HEIGHT])
        cy        = float(centroids[i][1])

        if comp_w > cw * 0.50 and comp_h < 8:
            if verbose:
                print(f"  {i:>4}  {area:>6}  {cy:>10.1f}  {'RULE':>8}  {'—':>10}  {'DISCARD':>8}")
            continue

        zone_name = "lower" if cy >= name_zone_y else "upper"
        threshold = keep_lower if cy >= name_zone_y else keep_upper
        action    = "KEEP" if area >= threshold else "REMOVE"

        if verbose:
            print(f"  {i:>4}  {area:>6}  {cy:>10.1f}  {zone_name:>8}  {threshold:>10}  {action:>8}")

        if area >= threshold:
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
