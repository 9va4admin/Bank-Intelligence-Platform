"""Train the signature embedder from the bank's own GENUINE specimens (no forgery labels), on-prem, and check it on writers it never saw.

    python scripts/train_signature_embedder.py --manifest specimens.csv --out models/sig_v1.pt --epochs 30 [--bbox x1,y1,x2,y2]

Manifest CSV columns: path, writer_id, label. Only GENUINE rows are used. One or many specimens per account both work: views of the same
specimen (and other specimens of the same account) are positives, other accounts are negatives.

A fraction of writers (--holdout-fraction) is kept out of training. Writers with more than --k-enrol specimens are then scored with the
evaluation harness (enrol k, test the rest, other writers as random forgeries); the result is stored in the model card. If no held-out
writer has enough specimens the model is still trained but the card says it could not be evaluated.

The model card always says promoted=false. Promotion is a separate, recorded decision. Nothing here shows protection against a skilled
forgery: that needs forged examples, which this deliberately does not require.
"""
from __future__ import annotations

import argparse
import io
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image  # noqa: E402

from modules.cts.evaluation.signature_dataset import ManifestError, load_manifest  # noqa: E402
from modules.cts.evaluation.signature_eval import GENUINE, SigSample, evaluate  # noqa: E402
from modules.cts.signature_training.checkpoint import save_checkpoint  # noqa: E402
from modules.cts.signature_training.embedder import TrainedSignatureEmbedder  # noqa: E402
from modules.cts.signature_training.train import train  # noqa: E402


def _load(row, crop):
    data = row.path.read_bytes()
    if crop:
        data = crop(data)
    return Image.open(io.BytesIO(data)).convert("L")


def _crop_fn(bbox):
    if not bbox:
        return None
    from modules.cts.workflows.activities.signature import _sync_crop_signature
    box = [float(v) for v in bbox.split(",")]
    if len(box) != 4:
        raise ManifestError("--bbox needs four comma-separated fractions: x1,y1,x2,y2")
    return lambda data: _sync_crop_signature(data, box)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True, help="checkpoint path; the model card is written next to it as <name>.card.json")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--init", choices=("imagenet", "none"), default="imagenet")
    ap.add_argument("--holdout-fraction", type=float, default=0.2, help="share of writers kept out of training for the evaluation")
    ap.add_argument("--k-enrol", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=0.85, help="operating threshold the held-out evaluation is scored at")
    ap.add_argument("--max-far", type=float, default=0.03)
    ap.add_argument("--bbox", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    try:
        rows = [r for r in load_manifest(Path(args.manifest)) if r.label == GENUINE]
        crop = _crop_fn(args.bbox)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    by_writer = defaultdict(list)
    for r in rows:
        by_writer[r.writer_id].append(r)
    writers = sorted(by_writer)
    random.Random(args.seed).shuffle(writers)
    n_hold = int(len(writers) * args.holdout_fraction) if len(writers) >= 5 else 0
    held, train_w = writers[:n_hold], writers[n_hold:]
    train_images = [(w, _load(r, crop)) for w in train_w for r in by_writer[w]]
    print(f"writers: {len(train_w)} to train on, {len(held)} held out; {len(train_images)} training signatures")

    model, history = train(train_images, epochs=args.epochs, batch_size=args.batch_size, size=args.size, lr=args.lr, seed=args.seed,
                           init=None if args.init == "none" else "imagenet")
    print(f"training loss {history[0]:.3f} -> {history[-1]:.3f}")

    embedder = TrainedSignatureEmbedder.from_model(model, size=args.size)
    evaluation = None
    eligible = [w for w in held if len(by_writer[w]) > args.k_enrol]
    if eligible:
        samples = [SigSample(w, GENUINE, embedder._embed_pil(_load(r, crop))) for w in eligible for r in by_writer[w]]
        evaluation = evaluate(samples, k_enrol=args.k_enrol, threshold=args.threshold, max_far=args.max_far, seed=args.seed)
        for kind, e in evaluation["by_kind"].items():
            far, frr = e["far"], e["frr"]
            print(f"held-out writers ({evaluation['writers_evaluated']}), {kind}: FAR {far['k']}/{far['n']} = {far['rate']:.1%}, "
                  f"FRR {frr['k']}/{frr['n']} = {frr['rate']:.1%}, EER {e['equal_error_rate']:.1%} at threshold {args.threshold}")
    else:
        print(f"the model could not be evaluated: no held-out writer has more than {args.k_enrol} specimens "
              "(need specimens per account beyond the enrolment ones, and enough writers to hold some out)")
    save_checkpoint(model, Path(args.out), size=args.size, n_images=len(train_images), n_writers=len(train_w),
                    final_loss=history[-1], evaluation=evaluation)
    print(f"wrote {args.out} and its model card: NOT promoted (promotion is a separate recorded decision)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
