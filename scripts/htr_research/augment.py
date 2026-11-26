"""Small, reproducible changes to a training image so the model sees more hands than the few writers in the data (used for training only, never for validation or test)."""
from __future__ import annotations

import random

from PIL import Image, ImageEnhance, ImageFilter


def augment_image(image: Image.Image, rng: random.Random, *, strength: float = 1.0) -> Image.Image:
    """Slight width change, a few degrees of tilt and slant, a touch of blur, and a little brightness and contrast change. strength 0 returns the image unchanged;
    1 is the usual amount. The ink is never erased: every change is small."""
    gray = image.convert("L")
    if strength <= 0:
        return gray
    width = max(4, round(gray.width * (1 + rng.uniform(-0.08, 0.08) * strength)))
    out = gray.resize((width, gray.height), Image.BICUBIC)
    out = out.rotate(rng.uniform(-3.0, 3.0) * strength, resample=Image.BICUBIC, fillcolor=255)
    shear = rng.uniform(-0.15, 0.15) * strength
    out = out.transform(out.size, Image.AFFINE, (1, shear, -shear * out.height / 2, 0, 1, 0), resample=Image.BICUBIC, fillcolor=255)
    blur = rng.uniform(0.0, 0.8) * strength
    if blur > 0.05:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    out = ImageEnhance.Contrast(out).enhance(1 + rng.uniform(-0.2, 0.2) * strength)
    return ImageEnhance.Brightness(out).enhance(1 + rng.uniform(-0.12, 0.12) * strength)
