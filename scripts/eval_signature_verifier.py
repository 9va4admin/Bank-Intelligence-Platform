"""Score signature embedders on a labelled dataset: forgery acceptance (FAR) and genuine rejection (FRR), with 95% intervals.

    python scripts/eval_signature_verifier.py --manifest data/sig/manifest.csv --embedder generic --embedder my_pkg.model:TrainedEmbedder \
        --k-enrol 3 --threshold 0.85 --max-far 0.03 --out docs/evaluation/signature_eval.json

Manifest CSV columns: path, writer_id, label (GENUINE | SKILLED_FORGERY); paths relative to the manifest. Images are signature crops, or whole
cheques with --bbox x1,y1,x2,y2 (fractions of the image) to cut the signature region out first.
`--embedder generic` is the production stand-in (untrained ImageNet ResNet-18); any 'package.module:Attr' with embed(bytes, bank_id) works.

Nothing is reported as meeting a target unless its 95% interval clears it, and the report says how many forgery trials would be needed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.cts.evaluation.signature_dataset import ManifestError, embed_samples, load_embedder, load_manifest  # noqa: E402
from modules.cts.evaluation.signature_eval import evaluate  # noqa: E402


def _embedder(spec: str):
    if spec == "generic":
        from shared.ai.local_signature_embedder import LocalSignatureEmbedder
        return LocalSignatureEmbedder()
    return load_embedder(spec)


def _crop_fn(bbox: str | None):
    if not bbox:
        return None
    from modules.cts.workflows.activities.signature import _sync_crop_signature
    box = [float(v) for v in bbox.split(",")]
    if len(box) != 4:
        raise ManifestError("--bbox needs four comma-separated fractions: x1,y1,x2,y2")
    return lambda data: _sync_crop_signature(data, box)


def _print(name: str, report: dict) -> None:
    print(f"\n=== {name}   (k_enrol={report['k_enrol']}, threshold={report['threshold']}) ===")
    print(f"writers evaluated: {report['writers_evaluated']}   skipped (too few genuine): {len(report['writers_skipped_too_few_genuine'])}")
    for kind, e in report["by_kind"].items():
        far, frr = e["far"], e["frr"]
        print(f"  {kind}: FAR {far['k']}/{far['n']} = {far['rate']:.1%} (95% CI {far['ci95'][0]:.1%}-{far['ci95'][1]:.1%});"
              f"  FRR {frr['k']}/{frr['n']} = {frr['rate']:.1%};  EER {e['equal_error_rate']:.1%}")
        if e.get("verdict"):
            print(f"     verdict vs max FAR {report['max_far']:.1%}: {e['verdict']}")
        t = e.get("threshold_for_target_far")
        if t:
            print(f"     threshold for FAR <= {report['max_far']:.1%}: {t['threshold']:.4f} -> FRR {t['frr']['rate']:.1%} ({t['frr']['k']}/{t['frr']['n']})")
    print(f"  error-free forgery trials needed to show FAR < 1% at 95%: {report['clean_forgery_trials_needed_for_1pct']}")


async def main_async(args) -> int:
    rows = load_manifest(Path(args.manifest))
    crop = _crop_fn(args.bbox)
    results = {}
    for spec in args.embedder:
        samples = await embed_samples(_embedder(spec), rows, crop=crop)
        results[spec] = evaluate(samples, k_enrol=args.k_enrol, threshold=args.threshold, max_far=args.max_far, seed=args.seed)
        _print(spec, results[spec])
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--embedder", action="append", required=True, help="'generic' or 'package.module:Attr' (repeatable: compared side by side)")
    ap.add_argument("--k-enrol", type=int, default=3, help="genuine specimens enrolled per writer (default 3)")
    ap.add_argument("--threshold", type=float, required=True, help="the operating threshold to score FAR/FRR at (the bank's signature.min_match_score)")
    ap.add_argument("--max-far", type=float, default=None, help="forgery-acceptance target; without it no verdict is given")
    ap.add_argument("--bbox", default=None, help="x1,y1,x2,y2 fractions: cut the signature out of whole-cheque images")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    try:
        return asyncio.run(main_async(ap.parse_args()))
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
