"""The pipeline-check command: validate the dataset layout, train briefly on a subset, report error rates and speed, and say plainly that it is not a reproduction."""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = str(ROOT / "scripts" / "htr_research" / "run_smoke.py")


def make_digit_dataset(root, n_train=24, n_val=8, n_test=8):
    words = [f"{a}{b}" for a in "0123" for b in "0123"]                              # 16 two-digit words
    (root / "vocab.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
    font = ImageFont.load_default(size=26)
    for split, n in (("train", n_train), ("val", n_val), ("test", n_test)):
        (root / split).mkdir()
        rows = []
        for k in range(1, n + 1):
            wid = (k * 7) % len(words)
            img = Image.new("L", (80, 40), 255)
            ImageDraw.Draw(img).text((8, 4), words[wid], fill=0, font=font)
            img.save(root / split / f"{k}.jpg")
            rows.append(f"{split}/{k}.jpg, {wid}")
        (root / f"{split}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, capture_output=True, text=True, timeout=240)


def test_it_validates_trains_on_a_subset_and_writes_an_honest_report(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    make_digit_dataset(root)
    out = tmp_path / "report.json"
    done = run("--root", str(root), "--expected-counts", "train=24,val=8,test=8", "--train-samples", "24", "--val-samples", "8", "--steps", "20", "--batch-size", "8", "--lr", "0.002",
               "--seed", "1", "--height", "32", "--max-width", "160", "--workers", "0", "--out", str(out))
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["validation"]["ok"] is True and report["validation"]["counts"] == {"train": 24, "val": 8, "test": 8}
    assert report["config"]["steps"] == 20 and report["train"]["images_per_second"] > 0 and len(report["train"]["losses"]) >= 1
    assert 0.0 <= report["val"]["cer"] <= 1.5 and report["val"]["n"] == 8
    assert "not a reproduction" in report["note"]
    assert "images/s" in done.stdout


def test_it_stops_before_training_when_the_data_does_not_match_what_was_expected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    make_digit_dataset(root)
    done = run("--root", str(root), "--expected-counts", "train=999,val=8,test=8", "--train-samples", "8", "--val-samples", "4", "--steps", "5", "--batch-size", "4", "--lr", "0.002",
               "--seed", "1", "--height", "32", "--max-width", "160", "--workers", "0", "--out", str(tmp_path / "r.json"))
    assert done.returncode == 2 and "counts" in done.stderr.lower()
    assert not (tmp_path / "r.json").exists()


def test_it_stops_with_a_message_when_the_folder_is_not_a_dataset(tmp_path):
    done = run("--root", str(tmp_path / "nothing"), "--train-samples", "8", "--val-samples", "4", "--steps", "5", "--batch-size", "4", "--lr", "0.002", "--seed", "1", "--height", "32",
               "--max-width", "160", "--workers", "0", "--out", str(tmp_path / "r.json"))
    assert done.returncode == 2 and done.stderr.strip()


def make_text_dataset(root, n_train=24, n_val=8, n_test=8):
    font = ImageFont.load_default(size=26)
    words = [f"{a}{b}" for a in "0123" for b in "0123"]
    for split, n, writers in (("train", n_train, (1, 2, 3)), ("val", n_val, (4,)), ("test", n_test, (5, 6))):
        rows = []
        for k in range(1, n + 1):
            w = writers[k % len(writers)]
            rel = f"HindiSeg/{split}/{w}/1/{k}.jpg"
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            word = words[(k * 5) % len(words)]
            img = Image.new("L", (80, 40), 255)
            ImageDraw.Draw(img).text((8, 4), word, fill=0, font=font)
            img.save(root / rel)
            rows.append(f"{rel} {word}")
        (root / f"{split}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_the_text_layout_with_writer_folders_is_validated_and_reports_the_writers(tmp_path):
    root = tmp_path / "hi"
    root.mkdir()
    make_text_dataset(root)
    out = tmp_path / "report.json"
    done = run("--layout", "text", "--root", str(root), "--expected-counts", "train=24,val=8,test=8", "--train-samples", "24", "--val-samples", "8", "--steps", "10", "--batch-size", "8",
               "--lr", "0.002", "--seed", "1", "--height", "32", "--max-width", "160", "--workers", "0", "--out", str(out))
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["validation"]["ok"] is True and report["validation"]["writers"] == {"train": 3, "val": 1, "test": 2}
    assert report["validation"]["writer_overlap"] == {"train&val": 0, "train&test": 0, "val&test": 0}
    assert report["val"]["n"] == 8 and "writers" in done.stdout


def test_the_text_layout_run_stops_when_a_writer_appears_in_two_splits(tmp_path):
    root = tmp_path / "hi"
    root.mkdir()
    make_text_dataset(root)
    leak = root / "HindiSeg/val/1/1/99.jpg"                                            # writer 1 is a training writer
    leak.parent.mkdir(parents=True)
    Image.new("L", (80, 40), 255).save(leak)
    (root / "val.txt").write_text((root / "val.txt").read_text(encoding="utf-8") + "HindiSeg/val/1/1/99.jpg 00\n", encoding="utf-8")
    done = run("--layout", "text", "--root", str(root), "--train-samples", "8", "--val-samples", "4", "--steps", "5", "--batch-size", "4", "--lr", "0.002", "--seed", "1", "--height", "32",
               "--max-width", "160", "--workers", "0", "--out", str(tmp_path / "r.json"))
    assert done.returncode == 2 and "writer" in done.stderr.lower()
