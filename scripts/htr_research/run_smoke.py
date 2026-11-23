"""Pipeline check for handwriting recognition data: validate an IIIT-Indic-HW-Words style folder, train the small CRNN briefly on a subset, report error rates and speed.

    python scripts/htr_research/run_smoke.py --root <extracted dataset> --expected-counts train=73517,val=13752,test=15730 \
        --train-samples 4000 --val-samples 500 --steps 300 --batch-size 32 --lr 0.001 --seed 1 --height 64 --max-width 320 --workers 4 --out report.json

This proves the data loads and the model learns; it is NOT a reproduction of the published results (those need the full data, a long schedule and a GPU).
Research use only until the dataset's licence is confirmed with its authors. Exit codes: 0 done, 2 the data is missing or does not match what was expected.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from htr_research.dataset import LabelError, WordDataset, build_charset, validate  # noqa: E402
from htr_research.train import evaluate, train  # noqa: E402

NOTE = "pipeline check on a subset and a short schedule; not a reproduction of the published results"


def parse_counts(text):
    return {k: int(v) for k, v in (item.split("=") for item in text.split(","))} if text else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--expected-counts", default=None)
    ap.add_argument("--train-samples", type=int, required=True)
    ap.add_argument("--val-samples", type=int, required=True)
    ap.add_argument("--steps", type=int, required=True)
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--lr", type=float, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--max-width", type=int, required=True)
    ap.add_argument("--workers", type=int, required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        report = validate(a.root, expected_counts=parse_counts(a.expected_counts))
        train_ds, val_ds = WordDataset(a.root, "train"), WordDataset(a.root, "val")
    except (LabelError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"counts {report.counts}; vocabulary {report.vocab_size} words; charset {report.charset_size} characters; missing images "
          f"{ {k: len(v) for k, v in report.missing.items()} }; test images with a word not seen in training {report.test_unseen_word_share:.1%}", flush=True)
    if report.counts_match is False:
        print(f"error: the counts {report.counts} do not match what was expected {a.expected_counts}", file=sys.stderr)
        return 2
    if not report.ok:
        print("error: the data is not ok (missing images or empty labels)", file=sys.stderr)
        return 2
    charset = build_charset(train_ds.vocab)
    rng = random.Random(a.seed)
    train_samples = rng.sample(train_ds.samples, min(a.train_samples, len(train_ds)))
    val_samples = rng.sample(val_ds.samples, min(a.val_samples, len(val_ds)))
    result = train(train_samples, charset, steps=a.steps, batch_size=a.batch_size, lr=a.lr, seed=a.seed, height=a.height, max_width=a.max_width, device=a.device,
                   workers=a.workers, log_every=a.log_every, verbose=True)
    scores = evaluate(result.model, val_samples, charset, height=a.height, max_width=a.max_width, batch_size=a.batch_size, device=a.device)
    print(f"validation on {scores['n']} images: character error {scores['cer']:.3f}, word error {scores['wer']:.3f}; {result.images_per_second:.1f} images/s training", flush=True)
    payload = {"note": NOTE, "config": {k: getattr(a, k) for k in ("train_samples", "val_samples", "steps", "batch_size", "lr", "seed", "height", "max_width", "workers", "device")},
               "validation": {"ok": report.ok, "counts": report.counts, "vocab_size": report.vocab_size, "charset_size": report.charset_size,
                              "test_unseen_word_share": report.test_unseen_word_share, "missing": {k: len(v) for k, v in report.missing.items()}},
               "train": {"losses": result.losses, "seconds": result.seconds, "images_per_second": result.images_per_second}, "val": scores}
    Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
