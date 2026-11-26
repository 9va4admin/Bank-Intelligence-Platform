"""Train a word-image handwriting recogniser properly on one language and score it once on the test split.

    python scripts/htr_research/train_full.py --root <dataset> --layout gt --out-dir runs/gujarati --expected-counts train=82563,val=17643,test=16490 \
        --max-epochs 40 --patience 5 --lr 0.001 --batch-size 32 --seed 1 --height 64 --max-width 320 --workers 6

Every epoch uses all training images; the whole validation split is scored after each epoch; the best checkpoint by validation character error is kept; training stops
when validation stops improving; an interrupted run resumes from the last finished epoch (use --fresh to start over). The test split is scored once, at the end,
with the best checkpoint, and every prediction is written to test_predictions.tsv. Research use only until the dataset's licence is confirmed with its authors.
Exit codes: 0 done, 2 the data is missing or does not match what was expected.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from htr_research.dataset import LabelError, TextLabelDataset, build_charset, load_splits  # noqa: E402
from htr_research.fit import FitConfig, final_test, fit  # noqa: E402

NOTE = ("The test split was scored once, with the checkpoint that was best on validation, and was not used to make any choice. Validation was the whole split every epoch. "
        "Public clean word images, not cheque crops: this is not cheque accuracy.")


def parse_counts(text):
    return {k: int(v) for k, v in (item.split("=") for item in text.split(","))} if text else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--layout", choices=["ids", "text", "gt"], required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--expected-counts", default=None)
    ap.add_argument("--max-epochs", type=int, required=True)
    ap.add_argument("--patience", type=int, required=True)
    ap.add_argument("--lr", type=float, required=True)
    ap.add_argument("--batch-size", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--max-width", type=int, required=True)
    ap.add_argument("--workers", type=int, required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--augment-strength", type=float, default=1.0)
    ap.add_argument("--min-delta", type=float, default=0.0)
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--fresh", action="store_true", help="ignore any earlier checkpoint in --out-dir and start over")
    a = ap.parse_args()
    try:
        splits = load_splits(a.root, a.layout)
    except (LabelError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    missing_splits = [s for s in ("train", "val", "test") if s not in splits]
    if missing_splits:
        print(f"error: the splits {missing_splits} are missing; a proper run needs train, val and test", file=sys.stderr)
        return 2
    counts = {s: len(v) for s, v in splits.items()}
    missing = {s: [str(x.path) for x in v if not x.path.exists()][:5] for s, v in splits.items()}
    expected = parse_counts(a.expected_counts)
    extra = ""
    if a.layout == "text":
        writers = {s: TextLabelDataset(a.root, s).writers for s in splits}
        overlap = {f"{x}&{y}": len(writers[x] & writers[y]) for x, y in (("train", "val"), ("train", "test"), ("val", "test"))}
        extra = f"; writers per split { {s: len(w) for s, w in writers.items()} }, shared between splits {overlap}"
        if any(overlap.values()):
            print(f"error: a writer appears in more than one split ({overlap})", file=sys.stderr)
            return 2
    elif a.layout == "gt":
        extra = "; writers are not named in this layout, so unseen writers cannot be confirmed"
    train_words = {x.text for x in splits["train"]}
    unseen = {s: sum(1 for x in splits[s] if x.text not in train_words) / len(splits[s]) for s in ("val", "test")}
    print(f"counts {counts}; images missing { {s: len(v) for s, v in missing.items()} }; words not seen in training: validation {unseen['val']:.1%}, test {unseen['test']:.1%}{extra}", flush=True)
    if expected is not None and counts != expected:
        print(f"error: the counts {counts} do not match what was expected {expected}", file=sys.stderr)
        return 2
    if any(missing.values()):
        print(f"error: images are listed but absent: {missing}", file=sys.stderr)
        return 2
    charset = build_charset([x.text for v in splits.values() for x in v])   # the alphabet of the script as the labels show it; characters never seen in training stay untrained
    cfg = FitConfig(max_epochs=a.max_epochs, patience=a.patience, lr=a.lr, batch_size=a.batch_size, seed=a.seed, height=a.height, max_width=a.max_width, workers=a.workers,
                    device=a.device, augment=not a.no_augment, augment_strength=a.augment_strength, min_delta=a.min_delta, max_hours=a.max_hours)
    out_dir = Path(a.out_dir)
    result = fit(splits["train"], splits["val"], charset, out_dir=out_dir, cfg=cfg, resume=not a.fresh, verbose=True)
    print(f"training ended ({result['stopped']}); best epoch {result['best_epoch']} with validation character error {result['best_val_cer']:.3f}; scoring the whole test split once", flush=True)
    test = final_test(out_dir / "best.pt", splits["test"], known_words=train_words, cfg=cfg, out_dir=out_dir)
    print(f"TEST on all {test['n']} images: character error {test['cer']:.3f} (95% {test['cer_ci'][0]:.3f}-{test['cer_ci'][1]:.3f}), word error {test['wer']:.3f} "
          f"(95% {test['wer_ci'][0]:.3f}-{test['wer_ci'][1]:.3f})", flush=True)
    for name, grp in (test.get("split") or {}).items():
        if grp:
            print(f"  {name} words ({grp['n']}): character error {grp['cer']:.3f}, word error {grp['wer']:.3f}", flush=True)
    for row in test["coverage"]:
        print(f"  confidence >= {row['threshold']}: answers {row['coverage']:.0%} of words, {('%.0f%%' % (100 * row['accuracy'])) if row['accuracy'] is not None else 'n/a'} of those exactly right", flush=True)
    report = {"note": NOTE, "config": {k: getattr(a, k) for k in ("layout", "max_epochs", "patience", "lr", "batch_size", "seed", "height", "max_width", "workers", "device", "augment_strength", "min_delta", "max_hours")}
              | {"augment": not a.no_augment}, "counts": counts, "charset_size": charset.size, "unseen_word_share": unseen, "stopped": result["stopped"], "best_epoch": result["best_epoch"],
              "history": result["history"], "test": test}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
