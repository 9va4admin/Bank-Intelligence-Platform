"""Synthetic forgeries: distort a genuine signature the way an imitation differs from the original (proportions, slant, local stroke shape,
pen thickness, hesitant tremor), so a bank with no forged examples can still give the embedder hard negatives."""
import random

import pytest

pytest.importorskip("scipy")
from PIL import Image, ImageDraw  # noqa: E402

from modules.cts.signature_training.synthetic_forgery import synthetic_forgery  # noqa: E402


def _signature(seed=1, size=(240, 120)):
    rng = random.Random(seed)
    img = Image.new("L", size, 255)
    ImageDraw.Draw(img).line([(rng.randint(5, size[0] - 5), rng.randint(5, size[1] - 5)) for _ in range(8)], fill=20, width=3)
    return img


def _diff(a, b):
    pa, pb = list(a.getdata()), list(b.getdata())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


def test_deterministic_per_seed_and_different_between_seeds():
    base = _signature()
    a = synthetic_forgery(base, random.Random(1))
    assert list(a.getdata()) == list(synthetic_forgery(base, random.Random(1)).getdata())
    assert list(a.getdata()) != list(synthetic_forgery(base, random.Random(2)).getdata())


def test_keeps_the_mode_differs_from_the_original_and_keeps_the_ink():
    base = _signature()
    for s in range(10):
        f = synthetic_forgery(base, random.Random(s))
        assert f.mode == "L" and _diff(base, f) > 0.5 and min(f.getdata()) < 200


def test_stronger_distortion_departs_further_from_the_original():
    base = _signature()
    weak = sum(_diff(base, synthetic_forgery(base, random.Random(s), strength=0.3)) for s in range(12)) / 12
    strong = sum(_diff(base, synthetic_forgery(base, random.Random(s), strength=1.5)) for s in range(12)) / 12
    assert strong > weak


def test_distortion_does_not_paint_a_white_border_on_a_gray_page():
    """A warp that fills with white leaves a visible edge a model can learn instead of the forgery itself (seen in the first montage)."""
    page = Image.new("L", (240, 120), 200)
    ImageDraw.Draw(page).line([(10, 100), (120, 20), (230, 90)], fill=30, width=3)
    for s in range(8):
        f = synthetic_forgery(page, random.Random(s), strength=1.4)
        border = [f.getpixel((x, y)) for x in range(f.width) for y in (0, f.height - 1)] + [f.getpixel((x, y)) for y in range(f.height) for x in (0, f.width - 1)]
        assert max(border) < 215, f"white border pixels at seed {s}: {max(border)}"      # page is 200; white would be 255
