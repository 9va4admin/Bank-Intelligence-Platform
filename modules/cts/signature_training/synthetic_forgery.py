"""Synthetic skilled-forgery negatives made from a GENUINE signature, for banks that have no forged examples.

An imitation keeps the overall look but differs in proportions and slant, in the local shape of strokes, in pen thickness, and in a slight
hesitant tremor. Each of those is applied here at a random strength. The output is a hard negative (close to the original, not the same),
not a claim to reproduce a real forger. Whether training on these helps against real forgeries is measured, not assumed:
on CEDAR with the paper removed (scripts/experiments/signature_cedar_pairs.py, CLEAN=1) it did NOT help (skilled-forgery EER about 20%, no better
than training on genuine signatures alone). Kept as an experiment tool; it is not wired into the production trainer.
"""
from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import gaussian_filter, map_coordinates


def _smooth_field(shape: tuple[int, int], sigma: float, amplitude: float, rng: random.Random) -> tuple[np.ndarray, np.ndarray]:
    gen = np.random.default_rng(rng.randint(0, 2**31 - 1))
    fields = []
    for _ in range(2):
        f = gaussian_filter(gen.uniform(-1, 1, shape), sigma)
        f = f / (np.abs(f).max() + 1e-9) * amplitude
        fields.append(f)
    return fields[0], fields[1]


def synthetic_forgery(img: Image.Image, rng: random.Random, strength: float = 1.0) -> Image.Image:
    """strength ~ 0.3 (mild) .. 1.5 (heavy); 1.0 is the default imitation-sized distortion."""
    img = img.convert("L")
    w, h = img.size
    m = min(w, h)
    bg = int(np.median(np.asarray(img)))        # fill with the page colour, never white: a white edge is a shortcut the model could learn

    # proportions, slant, small rotation (the forger gets the layout roughly right, not exactly)
    sx, sy = 1 + rng.uniform(-0.12, 0.12) * strength, 1 + rng.uniform(-0.12, 0.12) * strength
    shear, rot = rng.uniform(-0.18, 0.18) * strength, rng.uniform(-4, 4) * strength
    img = img.resize((max(8, int(w * sx)), max(8, int(h * sy))))
    img = img.rotate(rot, expand=True, fillcolor=bg)
    img = img.transform(img.size, Image.AFFINE, (1, shear, -shear * img.height / 2, 0, 1, 0), fillcolor=bg)

    # local stroke shape: smooth elastic displacement
    arr = np.asarray(img, dtype="float32")
    dy, dx = _smooth_field(arr.shape, sigma=0.09 * m, amplitude=0.07 * m * strength, rng=rng)
    yy, xx = np.meshgrid(np.arange(arr.shape[0]), np.arange(arr.shape[1]), indexing="ij")
    arr = map_coordinates(arr, [yy + dy, xx + dx], order=1, mode="constant", cval=float(bg))

    # hesitant tremor: small fast wobble
    if rng.random() < 0.6:
        ty, tx = _smooth_field(arr.shape, sigma=2.0, amplitude=1.6 * strength, rng=rng)
        arr = map_coordinates(arr, [yy + ty, xx + tx], order=1, mode="constant", cval=float(bg))

    out = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    # pen thickness differs from the original
    r = rng.random()
    if r < 0.35:
        out = out.filter(ImageFilter.MinFilter(3))
    elif r < 0.6:
        out = out.filter(ImageFilter.MaxFilter(3))
    return out
