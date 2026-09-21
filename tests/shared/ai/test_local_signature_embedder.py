"""LocalSignatureEmbedder — CPU embedder for the signature vault.

GENERIC backbone (ImageNet ResNet-18), NOT the custom-trained Siamese network
the architecture specifies (no such artifact exists in this repo). It lets the
extract -> embed -> store -> compare-at-runtime path run for real.
"""
import io
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw


def _sig(seed: int, w=300, h=120) -> bytes:
    rng = np.random.default_rng(seed)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    pts = [(int(x), int(y)) for x, y in zip(np.cumsum(rng.integers(5, 30, 12)) % w,
                                            rng.integers(10, h - 10, 12))]
    d.line(pts, fill=0, width=3)
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def emb():
    from shared.ai.local_signature_embedder import LocalSignatureEmbedder
    return LocalSignatureEmbedder()


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


@pytest.mark.asyncio
async def test_embedding_is_unit_length_512d(emb):
    v = await emb.embed(_sig(1), bank_id="kbl")
    assert len(v) == 512 and math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-4)


@pytest.mark.asyncio
async def test_same_image_is_deterministic(emb):
    a = await emb.embed(_sig(1), bank_id="kbl")
    b = await emb.embed(_sig(1), bank_id="kbl")
    assert _cos(a, b) > 0.9999


@pytest.mark.asyncio
async def test_different_signatures_score_lower_than_identical(emb):
    a = await emb.embed(_sig(1), bank_id="kbl")
    c = await emb.embed(_sig(7), bank_id="kbl")
    assert _cos(a, c) < 0.999


@pytest.mark.asyncio
async def test_undecodable_bytes_raise_value_error(emb):
    with pytest.raises(ValueError):
        await emb.embed(b"not an image", bank_id="kbl")
