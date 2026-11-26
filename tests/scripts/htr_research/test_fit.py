"""The proper training run: whole data every epoch, the full validation split after each epoch, early stopping, best checkpoint, resume, and one final score on the full test split."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from htr_research.dataset import build_charset, load_splits
from htr_research.fit import FitConfig, bootstrap_ci, final_test, fit

from .digits import make_digit_dataset

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = str(ROOT / "scripts" / "htr_research" / "train_full.py")


def cfg(**kw):
    base = dict(max_epochs=2, patience=3, lr=0.003, batch_size=8, seed=1, height=32, max_width=160, workers=0, device="cpu", augment=False)
    base.update(kw)
    return FitConfig(**base)


@pytest.fixture()
def data(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    make_digit_dataset(root)
    splits = load_splits(root, "ids")
    charset = build_charset([s.text for s in splits["train"]] + [s.text for s in splits["val"]])
    return splits, charset


def test_load_splits_returns_every_split(data):
    splits, _ = data
    assert {k: len(v) for k, v in splits.items()} == {"train": 21, "val": 9, "test": 11}


def test_every_epoch_uses_all_training_images_and_all_validation_images(tmp_path, data):
    splits, charset = data
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg())
    assert [h["train_images"] for h in out["history"]] == [21, 21]          # 21 is not a multiple of the batch size 8: the last partial batch is still used
    assert all(h["val_n"] == 9 for h in out["history"])


def test_it_keeps_the_best_and_the_latest_checkpoint_and_a_history(tmp_path, data):
    splits, charset = data
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg())
    assert (tmp_path / "run" / "best.pt").exists() and (tmp_path / "run" / "last.pt").exists()
    h = out["history"][0]
    assert {"epoch", "train_loss", "val_cer", "val_wer", "lr", "seconds"} <= set(h)
    assert out["best_epoch"] in (1, 2)
    assert out["best_val_cer"] == min(x["val_cer"] for x in out["history"])


def test_it_stops_early_when_validation_stops_improving(tmp_path, data):
    splits, charset = data
    # min_delta is huge, so after the first epoch nothing counts as an improvement; patience 1 stops the run after epoch 2
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg(max_epochs=6, patience=1, min_delta=10.0))
    assert len(out["history"]) == 2 and out["stopped"] == "no improvement"


def test_it_stops_when_the_time_budget_is_spent(tmp_path, data):
    splits, charset = data
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg(max_epochs=6, max_hours=1e-9))
    assert len(out["history"]) == 1 and out["stopped"] == "time budget"


def test_it_resumes_after_an_interruption(tmp_path, data):
    splits, charset = data
    fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg(max_epochs=1))
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg(max_epochs=2), resume=True)
    assert [h["epoch"] for h in out["history"]] == [1, 2]


def test_final_test_scores_every_test_image_with_intervals_and_keeps_the_predictions(tmp_path, data):
    splits, charset = data
    out = fit(splits["train"], splits["val"], charset, out_dir=tmp_path / "run", cfg=cfg())
    test = final_test(tmp_path / "run" / "best.pt", splits["test"], known_words={s.text for s in splits["train"]}, cfg=cfg(), out_dir=tmp_path / "run")
    assert test["n"] == 11
    assert 0.0 <= test["cer_ci"][0] <= test["cer"] <= test["cer_ci"][1] <= 1.5
    assert 0.0 <= test["wer_ci"][0] <= test["wer"] <= test["wer_ci"][1] <= 1.0
    rows = (tmp_path / "run" / "test_predictions.tsv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 11 + 1 and rows[0].split("\t")[:3] == ["path", "reference", "prediction"]


def test_bootstrap_interval_is_tight_when_all_right_and_contains_the_rate_otherwise():
    assert bootstrap_ci([1.0] * 50, seed=1) == (1.0, 1.0)
    lo, hi = bootstrap_ci([1.0] * 50 + [0.0] * 50, seed=1)
    assert lo < 0.5 < hi and hi - lo < 0.3
    assert bootstrap_ci([1.0, 0.0] * 20, seed=7) == bootstrap_ci([1.0, 0.0] * 20, seed=7)


def test_the_command_trains_validates_every_epoch_and_scores_the_full_test_split(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    make_digit_dataset(root)
    out = tmp_path / "run"
    done = subprocess.run([sys.executable, SCRIPT, "--root", str(root), "--layout", "ids", "--out-dir", str(out), "--expected-counts", "train=21,val=9,test=11", "--max-epochs", "2",
                           "--patience", "3", "--lr", "0.003", "--batch-size", "8", "--seed", "1", "--height", "32", "--max-width", "160", "--workers", "0", "--no-augment"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"train": 21, "val": 9, "test": 11}
    assert len(report["history"]) == 2 and report["test"]["n"] == 11
    assert report["test"]["split"].keys() == {"seen", "unseen"} and report["test"]["coverage"][0]["coverage"] == 1.0
    assert "scored once" in report["note"]
    assert (out / "best.pt").exists() and (out / "test_predictions.tsv").exists()


def test_the_command_refuses_when_the_counts_do_not_match(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    make_digit_dataset(root)
    done = subprocess.run([sys.executable, SCRIPT, "--root", str(root), "--layout", "ids", "--out-dir", str(tmp_path / "run"), "--expected-counts", "train=999,val=9,test=11",
                           "--max-epochs", "1", "--patience", "1", "--lr", "0.003", "--batch-size", "8", "--seed", "1", "--height", "32", "--max-width", "160", "--workers", "0"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 2 and "counts" in done.stderr.lower()
