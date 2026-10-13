"""
Image quality assessment for inward cheque images.

Maps to return reason code 39 ("Image not clear, present again with paper"): a drawee bank can only
return what it can show was unreadable, so every FAIL carries the measured numbers for the audit trail.

Deterministic, model-free, no GPU: Pillow + numpy only.

Calibration (70 real KBL scans, 2026-10-13): genuine scans measured sharpness >= 571, width >= 784,
contrast (p99-p1) >= 98; the same scans Gaussian-blurred (sigma 2 / 4) measured sharpness <= 105 (so a
threshold of 300 separates them with a wide margin both ways). Under-exposed but legible scans exist in
the real data (mean brightness ~76) and must not fail, so brightness is deliberately NOT a criterion.
Thresholds are Layer 3 config (cts.iqa_*), these are the defaults.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter


@dataclass(frozen=True)
class IQAThresholds:
    min_width: int = 700             # CTS-2010 grey is 100 dpi: a cheque is ~8 in wide -> ~800 px
    min_height: int = 300
    min_sharpness: float = 300.0     # variance of the Laplacian
    min_contrast: float = 60.0       # 99th - 1st percentile of grey levels
    min_std: float = 10.0            # blank page guard


@dataclass
class IQAResult:
    outcome: str                     # "PASS" | "FAIL"
    reason: str | None = None        # unreadable_image | resolution_too_low | blank_or_no_content | image_not_sharp | low_contrast
    metrics: dict = field(default_factory=dict)


def assess_image_quality(image_bytes: bytes, thresholds: IQAThresholds | None = None) -> IQAResult:
    t = thresholds or IQAThresholds()
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        grey = img.convert("L")
    except Exception:
        return IQAResult("FAIL", "unreadable_image")

    g = np.asarray(grey, dtype=np.float32)
    lap = np.asarray(
        grey.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)), dtype=np.float32
    ) - 128.0
    p1, p99 = np.percentile(g, [1, 99])
    metrics = {
        "width": int(img.width), "height": int(img.height),
        "sharpness": round(float(lap.var()), 1), "contrast": round(float(p99 - p1), 1),
        "std": round(float(g.std()), 1), "mean_brightness": round(float(g.mean()), 1),
    }

    if img.width < t.min_width or img.height < t.min_height:
        return IQAResult("FAIL", "resolution_too_low", metrics)
    if metrics["std"] < t.min_std:
        return IQAResult("FAIL", "blank_or_no_content", metrics)
    if metrics["sharpness"] < t.min_sharpness:
        return IQAResult("FAIL", "image_not_sharp", metrics)
    if metrics["contrast"] < t.min_contrast:
        return IQAResult("FAIL", "low_contrast", metrics)
    return IQAResult("PASS", None, metrics)
