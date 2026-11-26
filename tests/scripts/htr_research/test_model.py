"""Image preparation, the small CRNN + CTC model, decoding and error rates, and a real learning check on synthetic digit images (CPU, a few seconds)."""
import random

import pytest
import torch
from PIL import Image, ImageDraw, ImageFont

from htr_research.crnn import CRNN, cer_wer, ctc_greedy_decode, edit_distance
from htr_research.dataset import Sample, build_charset
from htr_research.preprocess import collate, prepare_image
from htr_research.train import evaluate, train

HEIGHT, MAX_W = 32, 160


# ---------------------------------------------------------------- image preparation

def test_an_image_becomes_a_fixed_height_grayscale_tensor_with_ink_high_and_the_aspect_kept():
    img = Image.new("RGB", (100, 50), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((10, 10, 30, 40), fill=(0, 0, 0))
    t = prepare_image(img, height=HEIGHT, max_width=MAX_W)
    assert t.shape == (1, HEIGHT, 64) and t.dtype == torch.float32                     # 100x50 at height 32 is 64 wide
    assert t.max() == pytest.approx(1.0, abs=0.02) and t.min() == pytest.approx(0.0, abs=0.02)
    assert t[0, :, :4].max() < 0.05                                                    # white background is near zero, the black ink is near one


def test_very_wide_and_very_narrow_images_are_kept_within_bounds():
    wide = prepare_image(Image.new("L", (4000, 100), 255), height=HEIGHT, max_width=MAX_W)
    assert wide.shape == (1, HEIGHT, MAX_W)                                            # shrunk to the cap, not cropped
    narrow = prepare_image(Image.new("L", (3, 100), 255), height=HEIGHT, max_width=MAX_W)
    assert narrow.shape[1] == HEIGHT and narrow.shape[2] >= 4                           # never narrower than the model can use


def test_a_batch_is_padded_to_the_widest_image_with_the_lengths_the_loss_needs():
    a, b = torch.rand(1, HEIGHT, 40), torch.rand(1, HEIGHT, 64)
    images, targets, input_lengths, target_lengths = collate([(a, [1, 2, 3]), (b, [4])])
    assert images.shape == (2, 1, HEIGHT, 64) and images[0, :, :, 40:].abs().sum() == 0
    assert targets.tolist() == [1, 2, 3, 4] and target_lengths.tolist() == [3, 1]
    assert input_lengths.tolist() == [10, 16]                                          # width / 4: the model shortens the width by 4


# ---------------------------------------------------------------- model, decoding, error rates

def test_the_model_turns_an_image_batch_into_one_score_row_per_four_pixels_of_width():
    model = CRNN(num_classes=12, height=HEIGHT)
    out = model(torch.rand(3, 1, HEIGHT, 64))
    assert out.shape == (16, 3, 12)                                                    # (time steps, batch, classes)


def test_greedy_decoding_merges_repeats_and_drops_blanks():
    # classes: 0 blank, 1 a, 2 b. Best path per step: a a blank a b b -> "a a b" after merging repeats and removing the blank
    path = [1, 1, 0, 1, 2, 2]
    logits = torch.full((6, 1, 3), -10.0)
    for t, c in enumerate(path):
        logits[t, 0, c] = 10.0
    assert ctc_greedy_decode(logits) == [[1, 1, 2]]
    assert ctc_greedy_decode(torch.full((4, 1, 3), 0.0).index_fill(2, torch.tensor([0]), 5.0)) == [[]]      # all blank


def test_edit_distance_and_the_error_rates_count_characters_and_whole_words():
    assert edit_distance("kitten", "sitting") == 3 and edit_distance("", "abc") == 3 and edit_distance("abc", "abc") == 0
    cer, wer = cer_wer(["abc", "abx", ""], ["abc", "abc", "abc"])
    assert cer == pytest.approx((0 + 1 + 3) / 9) and wer == pytest.approx(2 / 3)
    assert cer_wer([], []) == (0.0, 0.0)


# ---------------------------------------------------------------- it really learns

def synthetic_samples(tmp_path, n, seed):
    rng = random.Random(seed)
    font = ImageFont.load_default(size=26)
    samples = []
    for k in range(n):
        text = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 3)))
        img = Image.new("L", (24 * len(text) + 16, 40), 255)
        ImageDraw.Draw(img).text((8, 4), text, fill=0, font=font)
        path = tmp_path / f"s{seed}_{k}.png"
        img.save(path)
        samples.append(Sample(path, text, k))
    return samples


def test_training_lowers_the_loss_and_the_model_reads_digits_it_was_trained_on(tmp_path):
    torch.manual_seed(0)
    samples = synthetic_samples(tmp_path, 160, seed=1)
    charset = build_charset(["0123456789"])
    before = evaluate(CRNN(num_classes=charset.size, height=HEIGHT), samples[:40], charset, height=HEIGHT, max_width=MAX_W, batch_size=20)
    result = train(samples, charset, steps=240, batch_size=16, lr=2e-3, seed=0, height=HEIGHT, max_width=MAX_W, device="cpu", workers=0, log_every=40)
    after = evaluate(result.model, samples[:40], charset, height=HEIGHT, max_width=MAX_W, batch_size=20)
    assert result.losses[-1] < 0.5 * result.losses[0]
    assert after["cer"] < before["cer"] and after["cer"] < 0.4                  # measured: about 0.17 after 240 steps, 0.01 after 320
    assert result.images_per_second > 0 and result.seconds > 0
