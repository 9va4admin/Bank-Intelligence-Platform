"""scripts/train_signature_embedder.py end to end on toy signatures: trains from genuine specimens, evaluates on writers it did not train on,
and writes a checkpoint whose model card says NOT promoted."""
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch")
from PIL import Image, ImageDraw  # noqa: E402

from modules.cts.signature_training.augment import augment  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]


def _toy(seed, size=96):
    rng = random.Random(seed)
    img = Image.new("L", (size, size // 2), 255)
    ImageDraw.Draw(img).line([(rng.randint(2, size - 2), rng.randint(2, size // 2 - 2)) for _ in range(7)], fill=20, width=2)
    return img


def _dataset(tmp_path, writers=10, specimens=5):
    rows = ["path,writer_id,label"]
    for w in range(writers):
        for s in range(specimens):
            f = tmp_path / f"w{w}_{s}.png"
            augment(_toy(w), random.Random(w * 100 + s)).save(f)
            rows.append(f"{f.name},W{w},GENUINE")
    m = tmp_path / "m.csv"
    m.write_text("\n".join(rows) + "\n")
    return m


def _run(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, "scripts/train_signature_embedder.py", "--manifest", str(_dataset(tmp_path)), "--out", str(tmp_path / "sig.pt"),
         "--epochs", "1", "--batch-size", "8", "--size", "64", "--init", "none", "--holdout-fraction", "0.3", "--k-enrol", "2", *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=600)


def test_trains_evaluates_on_held_out_writers_and_does_not_promote(tmp_path):
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-800:]
    card = json.loads((tmp_path / "sig.card.json").read_text())
    assert card["promoted"] is False
    held_out = card["evaluation"]["writers_evaluated"]
    assert held_out == 3 and card["trained_on"]["n_writers"] == 7          # 30% of 10 writers held out, never trained on
    assert "RANDOM_FORGERY" in card["evaluation"]["by_kind"]
    assert "held-out" in proc.stdout and "NOT promoted" in proc.stdout


def test_a_dataset_too_small_to_hold_out_writers_trains_but_says_it_could_not_evaluate(tmp_path):
    rows = ["path,writer_id,label"]
    for w in range(3):
        f = tmp_path / f"w{w}.png"
        _toy(w).save(f)
        rows.append(f"{f.name},W{w},GENUINE")
    m = tmp_path / "m.csv"
    m.write_text("\n".join(rows) + "\n")
    proc = subprocess.run(
        [sys.executable, "scripts/train_signature_embedder.py", "--manifest", str(m), "--out", str(tmp_path / "s.pt"), "--epochs", "1",
         "--batch-size", "4", "--size", "64", "--init", "none", "--k-enrol", "2"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-800:]
    card = json.loads((tmp_path / "s.card.json").read_text())
    assert card["evaluation"] is None and "could not be evaluated" in proc.stdout
