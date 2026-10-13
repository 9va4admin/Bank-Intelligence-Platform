"""Image quality assessment (return reason code 39, "image not clear, present again with paper").

Thresholds were calibrated on 70 real KBL scans: genuine scans measured sharpness >= 571, width >= 784,
contrast >= 98; the same scans blurred (sigma 2 and 4) measured sharpness <= 105. Under-exposed but legible
scans exist in the real data (mean brightness ~76) and must NOT fail.
"""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from modules.cts.preprocessing.image_quality import assess_image_quality, IQAThresholds


def _png(img) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _cheque_like(w=800, h=360, dark=False):
    rng = np.random.default_rng(3)
    img = Image.new("L", (w, h), 70 if dark else 235)
    d = ImageDraw.Draw(img)
    for y in range(30, h - 30, 28):                      # text-like strokes
        x = 20
        while x < w - 40:
            seg = int(rng.integers(8, 40))
            d.rectangle([x, y, x + seg, y + int(rng.integers(3, 9))], fill=20 if not dark else 5)
            x += seg + int(rng.integers(6, 18))
    return img


def test_a_clear_scan_passes():
    r = assess_image_quality(_png(_cheque_like()))
    assert r.outcome == "PASS", r


def test_an_under_exposed_but_legible_scan_passes():
    r = assess_image_quality(_png(_cheque_like(dark=True)))
    assert r.outcome == "PASS", r


def test_a_blurred_scan_fails_on_sharpness():
    blurred = _cheque_like().filter(ImageFilter.GaussianBlur(4))
    r = assess_image_quality(_png(blurred))
    assert r.outcome == "FAIL" and r.reason == "image_not_sharp"


def test_a_tiny_image_fails_on_resolution():
    r = assess_image_quality(_png(_cheque_like(w=400, h=180)))
    assert r.outcome == "FAIL" and r.reason == "resolution_too_low"


def test_a_blank_page_fails():
    r = assess_image_quality(_png(Image.new("L", (800, 360), 240)))
    assert r.outcome == "FAIL" and r.reason in ("blank_or_no_content", "image_not_sharp")


def test_unreadable_bytes_fail_safely_never_raise():
    r = assess_image_quality(b"this is not an image")
    assert r.outcome == "FAIL" and r.reason == "unreadable_image"


def test_metrics_are_reported_for_the_audit_trail():
    r = assess_image_quality(_png(_cheque_like()))
    assert {"width", "height", "sharpness", "contrast"} <= set(r.metrics)


def test_thresholds_are_configurable():
    strict = IQAThresholds(min_width=2000)
    r = assess_image_quality(_png(_cheque_like()), strict)
    assert r.outcome == "FAIL" and r.reason == "resolution_too_low"
