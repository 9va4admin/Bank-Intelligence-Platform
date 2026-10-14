"""Score an inward run against by-eye ground truth and write an honest evaluation report.

python scripts/eval_inward.py --results all_lots_detail.json --truth12 all_lots_l12_truth.json \
    --truth3 lot3_truth.json --classification lot3_classification.json --sig sig_roc.json --out docs/evaluation/inward_evaluation.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.cts.evaluation.inward_eval import NFR_TARGETS, Row, score  # noqa: E402
from modules.cts.evaluation.stats import required_n_for_error_bound, wilson_interval  # noqa: E402


def load(p):
    return json.load(open(p, encoding="utf-8"))


def build_rows(results, truth12, truth3, classification):
    idx3 = {k: i for i, k in enumerate(sorted(classification), 1)}
    rows = []
    for k, v in results.items():
        o = v.get("ocr") or {}
        fin = v.get("final") or {}
        if v["lot"] == "Lot 3":
            t = truth3[str(idx3[k])]
            tt, tp, t9, tn = t["type"], t["payee"], t["micr9"], t["num"]
            tamt, scored, should_return = "", t.get("unsure") is None, None
        else:
            t = truth12[k]
            tt, tp, t9, tn, tamt = t["type"], t["payee"], t["micr9"], t["num"], t["amount"]
            scored = t.get("payee_script") != "indic" and not t.get("unsure")
            # Lots 1-2 are dated September 2026 and were run in October 2026: within the 90-day window,
            # so an automatic return of any of them for staleness or post-dating is wrong.
            should_return = False if t["date"] != "ambiguous" else None
        rows.append(Row(
            key=k, lot=v["lot"], truth_type=tt,
            read_type="DD" if o.get("instrument_category") == "DEMAND_DRAFT" else "CHQ",
            truth_payee=tp, read_payee=o.get("payee"), payee_withheld=o.get("payee_reread_status") == "DISAGREE",
            payee_scored=scored, truth_micr9=t9, read_micr9=o.get("bank_branch_code"), truth_num=tn,
            read_num=o.get("cheque_number"), truth_amount=tamt, read_amount=o.get("amount_figures") if tamt else None,
            decision=fin.get("decision") or "NONE", truth_should_return=should_return))
    return rows


def main():
    ap = argparse.ArgumentParser()
    for a in ("results", "truth12", "truth3", "classification", "sig", "out"):
        ap.add_argument("--" + a, required=True)
    a = ap.parse_args()
    rows = build_rows(load(a.results), load(a.truth12), load(a.truth3), load(a.classification))
    res = score(rows)
    sig = load(a.sig)
    gen, imp = sig["genuine"], sig["impostor"]
    out = [f"# Inward evaluation against the documented accuracy targets", "",
           f"Generated {datetime.date.today()} by `scripts/eval_inward.py` from {len(rows)} real KBL instruments "
           f"(Lot 1: {sum(r.lot == 'Lot 1' for r in rows)}, Lot 2: {sum(r.lot == 'Lot 2' for r in rows)}, "
           f"Lot 3: {sum(r.lot == 'Lot 3' for r in rows)}).", "",
           "**Ground truth is my own by-eye reading of the images and can itself be wrong.** Targets are the NFRs in "
           "CLAUDE.md section 12. An interval is a 95% Wilson interval. `MEETS` is only claimed when the whole interval "
           "clears the target; a point estimate on too few samples is reported as `NOT DEMONSTRABLE`.", "",
           "## Field and decision metrics", "",
           "| Metric | Result | 95% interval | Target | Verdict |", "|---|---|---|---|---|"]
    for m in res.metrics:
        lo, hi = m.ci
        tgt = "-" if m.target is None else (f">= {m.target:.0%}" if m.higher_is_better else f"<= {m.target:.0%}")
        flag = " **(critical: a wrong value reached the screen/decision)**" if m.critical and m.k else ""
        out.append(f"| {m.name} | {m.k}/{m.n} = {m.rate:.1%} | {lo:.1%} - {hi:.1%} | {tgt} | {m.verdict}{flag} |")
    out += ["", f"**Sample size needed.** To show an error rate below 1% with zero errors you need "
            f"{required_n_for_error_bound(0.01)} clean samples; below 3%: {required_n_for_error_bound(0.03)}; "
            f"below 0.1%: {required_n_for_error_bound(0.001)}. The bank's labelled set must be sized for the target it wants to prove.", ""]

    # signature
    def far(th): return sum(i >= th for i in imp) / len(imp)
    def frr(th): return 1 - sum(g >= th for g in gen) / len(gen)
    out += ["## Signature verification (current verifier: generic ImageNet ResNet-18, NOT a trained signature model)", "",
            f"Measured on {sig['n_signatures']} real signatures: {len(gen)} genuine pairs (same account) and {len(imp)} impostor pairs "
            "(different accounts). Only 5 genuine pairs exist in the data, so these are indicative, not conclusive.", "",
            "| Threshold | Impostors accepted (FAR) | Genuine rejected (FRR) |", "|---|---|---|"]
    for th in (0.85, 0.90, 0.95):
        out.append(f"| {th:.2f} | {sum(i >= th for i in imp)}/{len(imp)} = {far(th):.1%} | {sum(g < th for g in gen)}/{len(gen)} = {frr(th):.0%} |")
    out += ["", f"Target: signature precision > {NFR_TARGETS['signature_precision']:.0%}. At the production threshold (0.85) the verifier "
            "accepts about half of different-signer pairs, so it is **BELOW target by a wide margin**. The pipeline therefore refuses "
            "to confirm automatically on this verifier (`signature_verifier_untrained`). A trained model and genuine/forgery data are required.", "",
            "## Fraud model", "",
            f"**NOT ASSESSABLE.** Targets: F1 > {NFR_TARGETS['fraud_f1']}, false positive < {NFR_TARGETS['false_positive']:.0%}, "
            f"false negative < {NFR_TARGETS['false_negative']:.0%}. There are no labelled fraud cases in the data; the model in use is a "
            "synthetic stand-in trained on rule-labelled data. Any metric computed on it would measure the rules, not fraud.", "",
            "## What the bank must supply for a real assessment", "",
            "- At least 300 real inward instruments with verified field values (more to prove tighter targets), spanning cheques and DDs, "
            "printed and handwritten, Latin and Indic scripts, good and poor scans.",
            "- Genuine signature specimens (3 or more per account) and a set of confirmed forgeries or disowned instruments.",
            "- Confirmed fraud and confirmed-genuine outcomes for the fraud model, with the account history features it needs.",
            "- The decision the bank actually took on each instrument, so wrong automatic returns/confirms can be measured, not inferred.", ""]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out[:30]))


if __name__ == "__main__":
    main()
