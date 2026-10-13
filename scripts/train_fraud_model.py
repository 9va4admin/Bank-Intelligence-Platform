"""Train the fraud model from the bank's labelled CSV (docs/fraud/labelled-data-contract.md).

python scripts/train_fraud_model.py --data labelled.csv --out models/fraud_kbl.json --data-label kbl-2026-q3
Add --synthetic ONLY for generated data: the artifact is then labelled a synthetic stand-in.
Prints the held-out report and exits non-zero if the documented targets are not met, so a pipeline cannot
silently promote a model that misses them (pass --allow-below-target to still write it for inspection).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.cts.fraud_training.io import ContractViolation, load_labelled_csv  # noqa: E402
from modules.cts.fraud_training.train import TrainingRefused, train_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data-label", default=None)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--allow-below-target", action="store_true")
    a = ap.parse_args()
    try:
        X, y, ts = load_labelled_csv(a.data)
        rep = train_model(X, y, ts, a.out, synthetic=a.synthetic, data_label=a.data_label)
    except (ContractViolation, TrainingRefused) as exc:
        print("REFUSED:", exc)
        return 2
    print(json.dumps(rep, indent=1, default=float))
    if not rep["meets_nfr"] and not a.allow_below_target:
        print("\nBELOW the documented targets: not promoting. See nfr_note.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
