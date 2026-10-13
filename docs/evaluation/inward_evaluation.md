# Inward evaluation against the documented accuracy targets

Generated 2026-10-13 by `scripts/eval_inward.py` from 70 real KBL instruments (Lot 1: 20, Lot 2: 10, Lot 3: 40).

**Ground truth is my own by-eye reading of the images and can itself be wrong.** Targets are the NFRs in CLAUDE.md section 12. An interval is a 95% Wilson interval. `MEETS` is only claimed when the whole interval clears the target; a point estimate on too few samples is reported as `NOT DEMONSTRABLE`.

## Field and decision metrics

| Metric | Result | 95% interval | Target | Verdict |
|---|---|---|---|---|
| instrument type (cheque vs DD) | 70/70 = 100.0% | 94.8% - 100.0% | >= 99% | NOT DEMONSTRABLE at n=70 (point estimate 100.0% meets 99.0%, interval 94.8%-100.0%) |
| payee: exact | 42/55 = 76.4% | 63.7% - 85.6% | >= 99% | BELOW target (76.4% < 99.0%; interval 63.7%-85.6%) |
| payee: wrong value SHOWN | 1/55 = 1.8% | 0.3% - 9.6% | <= 1% | BELOW target (1.8% > 1.0%; interval 0.3%-9.6%) **(critical: a wrong value reached the screen/decision)** |
| payee: withheld for review | 12/55 = 21.8% | 12.9% - 34.4% | - | (no target defined) |
| 9-digit sort code correct | 56/70 = 80.0% | 69.2% - 87.7% | >= 99% | BELOW target (80.0% < 99.0%; interval 69.2%-87.7%) |
| 9-digit sort code: wrong value READ | 4/70 = 5.7% | 2.2% - 13.8% | <= 1% | BELOW target (5.7% > 1.0%; interval 2.2%-13.8%) **(critical: a wrong value reached the screen/decision)** |
| cheque/DD number correct | 57/70 = 81.4% | 70.8% - 88.8% | >= 99% | BELOW target (81.4% < 99.0%; interval 70.8%-88.8%) |
| cheque/DD number: wrong value READ | 3/70 = 4.3% | 1.5% - 11.9% | <= 1% | BELOW target (4.3% > 1.0%; interval 1.5%-11.9%) **(critical: a wrong value reached the screen/decision)** |
| amount figures correct | 25/30 = 83.3% | 66.4% - 92.7% | >= 99% | BELOW target (83.3% < 99.0%; interval 66.4%-92.7%) |
| amount figures: wrong value READ | 5/30 = 16.7% | 7.3% - 33.6% | <= 1% | BELOW target (16.7% > 1.0%; interval 7.3%-33.6%) **(critical: a wrong value reached the screen/decision)** |
| automatic returns that were WRONG | 0/0 = 0.0% | 0.0% - 100.0% | <= 1% | NOT ASSESSABLE (no data) |

**Sample size needed.** To show an error rate below 1% with zero errors you need 299 clean samples; below 3%: 99; below 0.1%: 2995. The bank's labelled set must be sized for the target it wants to prove.

## Signature verification (current verifier: generic ImageNet ResNet-18, NOT a trained signature model)

Measured on 36 real signatures: 5 genuine pairs (same account) and 625 impostor pairs (different accounts). Only 5 genuine pairs exist in the data, so these are indicative, not conclusive.

| Threshold | Impostors accepted (FAR) | Genuine rejected (FRR) |
|---|---|---|
| 0.85 | 332/625 = 53.1% | 0/5 = 0% |
| 0.90 | 171/625 = 27.4% | 0/5 = 0% |
| 0.95 | 28/625 = 4.5% | 1/5 = 20% |

Target: signature precision > 97%. At the production threshold (0.85) the verifier accepts about half of different-signer pairs, so it is **BELOW target by a wide margin**. The pipeline therefore refuses to confirm automatically on this verifier (`signature_verifier_untrained`). A trained model and genuine/forgery data are required.

## Fraud model

**NOT ASSESSABLE.** Targets: F1 > 0.92, false positive < 3%, false negative < 1%. There are no labelled fraud cases in the data; the model in use is a synthetic stand-in trained on rule-labelled data. Any metric computed on it would measure the rules, not fraud.

## What the bank must supply for a real assessment

- At least 300 real inward instruments with verified field values (more to prove tighter targets), spanning cheques and DDs, printed and handwritten, Latin and Indic scripts, good and poor scans.
- Genuine signature specimens (3 or more per account) and a set of confirmed forgeries or disowned instruments.
- Confirmed fraud and confirmed-genuine outcomes for the fraud model, with the account history features it needs.
- The decision the bank actually took on each instrument, so wrong automatic returns/confirms can be measured, not inferred.
