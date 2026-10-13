# Inward evaluation against the documented accuracy targets

Generated 2026-10-13 by `scripts/eval_inward.py` from 70 real KBL instruments (Lot 1: 20, Lot 2: 10, Lot 3: 40).

**Ground truth is my own by-eye reading of the images and can itself be wrong.** Targets are the NFRs in CLAUDE.md section 12. An interval is a 95% Wilson interval. `MEETS` is only claimed when the whole interval clears the target; a point estimate on too few samples is reported as `NOT DEMONSTRABLE`.

## Field and decision metrics

| Metric | Result | 95% interval | Target | Verdict |
|---|---|---|---|---|
| instrument type (cheque vs DD) | 70/70 = 100.0% | 94.8% - 100.0% | >= 99% | NOT DEMONSTRABLE at n=70 (point estimate 100.0% meets 99.0%, interval 94.8%-100.0%) |
| payee: exact | 41/55 = 74.5% | 61.7% - 84.2% | >= 99% | BELOW target (74.5% < 99.0%; interval 61.7%-84.2%) |
| payee: wrong value SHOWN | 1/55 = 1.8% | 0.3% - 9.6% | <= 1% | BELOW target (1.8% > 1.0%; interval 0.3%-9.6%) **(critical: a wrong value reached the screen/decision)** |
| payee: withheld for review | 13/55 = 23.6% | 14.4% - 36.3% | - | (no target defined) |
| 9-digit sort code correct | 54/70 = 77.1% | 66.0% - 85.4% | >= 99% | BELOW target (77.1% < 99.0%; interval 66.0%-85.4%) |
| 9-digit sort code: wrong value READ | 4/70 = 5.7% | 2.2% - 13.8% | <= 1% | BELOW target (5.7% > 1.0%; interval 2.2%-13.8%) **(critical: a wrong value reached the screen/decision)** |
| cheque/DD number correct | 55/70 = 78.6% | 67.6% - 86.6% | >= 99% | BELOW target (78.6% < 99.0%; interval 67.6%-86.6%) |
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

## Second-read gate for the MICR numbers and the amount (measured 2026-10-13)

An independent read by a different model (Qwen3-VL-32B) of a zoomed crop of the MICR band, and of the amount box,
compared with the pipeline's primary read, on all 70 real instruments (amount truth exists for 30):

| Field | Primary wrong | Exposed by disagreement | Wrong and NOT exposed | Correct reads falsely flagged | Primary unread, second read correct |
|---|---|---|---|---|---|
| Cheque number | 3 | 3 | 0 | 7 of 55 | 10 of 12 |
| Sort code | 4 | 4 | 0 | 7 of 54 | 11 of 12 |
| Amount (n=30) | 5 | 4 | 1 | 3 of 25 | n/a |

The one uncaught amount is a cheque whose figures and words disagree with each other in a way both models read
the same (Rs 30,000 words, Rs 3,00,000 figures), which the figures-vs-words check separately flags. The cost is
about one correct read in eight sent to a human. Implemented as `_field_rereads` in `ocr.py` (commit `5a2e081`);
a disagreement goes to human review with both readings (`micr_reread_disagreement`, `amount_reread_disagreement`).

**Not yet re-measured end to end.** The full-run evaluation above predates this gate. A re-run on 2026-10-14 could
not measure it: the Hugging Face inference account behind the cloud model had **no credits left** (HTTP 402 on
every call). That run is still a useful result: with the model fully unavailable, all 70 instruments degraded to
human review, none failed, none was confirmed or returned automatically. It also exposed and fixed a real defect
(an OCR timeout failed the whole workflow instead of routing to review; see CLAUDE.md section 2.11).
Re-run `scripts/eval_inward.py` after credits are restored, or against the on-prem model.
