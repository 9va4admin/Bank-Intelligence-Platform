"""Training-time image variation: small, reproducible changes so the model sees more hands than the few writers in the data."""
import random

from PIL import Image, ImageDraw

from htr_research.augment import augment_image


def sample_image():
    img = Image.new("L", (120, 48), 255)
    ImageDraw.Draw(img).rectangle((20, 10, 60, 38), fill=0)
    return img


def test_same_seed_gives_the_same_image_and_different_seeds_differ():
    a = augment_image(sample_image(), random.Random(1))
    b = augment_image(sample_image(), random.Random(1))
    c = augment_image(sample_image(), random.Random(2))
    assert list(a.getdata()) == list(b.getdata())
    assert list(a.getdata()) != list(c.getdata())


def test_the_image_is_changed_but_stays_a_grayscale_picture_of_similar_size():
    out = augment_image(sample_image(), random.Random(3))
    assert out.mode == "L"
    assert abs(out.width - 120) <= 12 and abs(out.height - 48) <= 6
    assert list(out.getdata()) != list(sample_image().getdata())


def test_the_ink_is_not_lost():
    for seed in range(20):
        out = augment_image(sample_image(), random.Random(seed))
        dark = sum(1 for p in out.getdata() if p < 128)
        assert dark > 400, seed          # the original has about 1,200 dark pixels; small changes must not erase them


def test_strength_zero_leaves_the_image_unchanged():
    out = augment_image(sample_image(), random.Random(4), strength=0.0)
    assert list(out.getdata()) == list(sample_image().getdata())
