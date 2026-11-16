"""Capture-variation augmentation: what changes between two scans of the SAME signature (crop, tilt, ink thickness, contrast, noise,
blur, JPEG, printed lines behind the ink). Training teaches the embedder that these differences are not a different writer.
Independent of the re-scan variants used by the evaluation, so a result is not graded on the augmentation it was trained on."""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


def augment(img: Image.Image, rng: random.Random) -> Image.Image:
    import numpy as np

    img = img.convert("L")
    w, h = img.size
    # crop jitter: keep 80-100% of each side at a random offset (the detector's box is never exactly the same twice)
    cw, ch = int(w * rng.uniform(0.8, 1.0)), int(h * rng.uniform(0.8, 1.0))
    x0, y0 = rng.randint(0, w - cw), rng.randint(0, h - ch)
    img = img.crop((x0, y0, x0 + cw, y0 + ch))
    # tilt and slant
    img = img.rotate(rng.uniform(-5, 5), expand=True, fillcolor=255)
    shear = rng.uniform(-0.1, 0.1)
    img = img.transform(img.size, Image.AFFINE, (1, shear, -shear * img.height / 2, 0, 1, 0), fillcolor=255)
    # pen thickness
    if rng.random() < 0.3:
        img = img.filter(ImageFilter.MinFilter(3) if rng.random() < 0.5 else ImageFilter.MaxFilter(3))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.7, 1.3))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.85, 1.1))
    # printed lines / stamps behind the ink
    if rng.random() < 0.5:
        d = ImageDraw.Draw(img)
        for _ in range(rng.randint(1, 3)):
            shade = rng.randint(150, 220)
            x1, y1 = rng.randint(0, img.width), rng.randint(0, img.height)
            x2, y2 = rng.randint(0, img.width), rng.randint(0, img.height)
            d.line((x1, y1, x2, y2), fill=shade, width=rng.randint(1, 3))
    if rng.random() < 0.4:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.0)))
    arr = np.asarray(img, dtype="float32")
    arr = arr + np.random.default_rng(rng.randint(0, 2**31 - 1)).normal(0, rng.uniform(0, 9), arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    if rng.random() < 0.5:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=rng.randint(50, 95))
        img = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    return img
