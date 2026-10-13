# Labelled fraud data contract

What the bank must supply to replace the synthetic stand-in fraud model with a real one. Enforced by
`modules/cts/fraud_training/io.py` (loader) and `train.py` (guardrails); try it with
`python scripts/train_fraud_model.py --data <file>.csv --out models/<name>.json --data-label <label>`.

## File

One CSV, UTF-8, one row per **presented inward instrument**, header row required.

| Column | Meaning |
|---|---|
| `timestamp` | presentment time, epoch seconds (used for the chronological split) |
| `is_fraud` | `1` = confirmed fraudulent / forged / disowned / returned as fake; `0` = confirmed genuine |
| `amount` | presented amount, rupees |
| `ocr_confidence` | overall OCR confidence the pipeline produced for the instrument |
| `alteration_flag` | `1` if alteration was detected on the image |
| `signature_match_score` | similarity to the enrolled specimens, from a **trained** verifier (leave empty until one exists) |
| `amount_to_balance_ratio` | amount / available balance at presentment |
| `pps_found` | `1` positive-pay entry matched, `0` did not |
| `amount_vs_account_median` | amount / the account's median cheque amount over the previous 90 days |
| `payee_seen_before` | `1` if the payee had been paid from this account before |
| `cheques_last_24h` | cheques presented on the account in the previous 24 hours |
| `days_since_account_opened` | account age in days |

An **empty cell means unknown** and is kept as missing. Never write `0` for "unknown": it claims knowledge that
the model would then learn from.

## What must NOT be in the file

No account numbers, customer names, payee names, mobile numbers, PAN or Aadhaar. The loader refuses any column
whose name suggests them. Join history features on the bank's side and export only the numbers above.

## Volume and quality

* The pipeline refuses to train below **1,000 rows** or **30 confirmed-fraud rows**, and refuses if any of the
  chronological train / validation / test slices has no fraud case.
* To *show* a false-negative rate below 1% at 95% confidence you need roughly 300 test-slice fraud cases with
  none missed; below 3% needs about 100. Plan the labelled window for the target you want to prove, not for
  what is convenient.
* Labels must reflect the **outcome**, not what a model or reviewer first suspected. Include genuine instruments
  that were flagged and then cleared: they are exactly what teaches the model not to over-flag.
* At least 6 months, so seasonal patterns (festival cash cycles, month-end) are in both train and test.

## How it is judged

Chronological 60 / 20 / 20 split. The decision threshold is chosen on the validation slice only, to keep false
negatives within 1%. The report on the **test** slice gives precision, recall, F1, false-positive and
false-negative rates with 95% intervals, and `meets_nfr` is true only if the interval upper bounds clear the
documented error targets (false positive < 3%, false negative < 1%) **and** F1 > 0.92. A model that misses the
targets is not promoted unless `--allow-below-target` is passed for inspection.

## Using the model

Set the Layer 3 config key `cts.fraud_model_path` to the written file (the `.meta.json` beside it carries the
feature names, threshold, provenance and the full report). The scoring path builds the vector from the model's
declared feature names; any feature the pipeline cannot supply stays missing. History features
(`amount_vs_account_median`, `payee_seen_before`, `cheques_last_24h`, `days_since_account_opened`) need the bank
to implement the `FeatureStore` interface in `modules/cts/fraud_training/features.py`; until then they are
missing at scoring time and a model that depends heavily on them should not be promoted.

Every score from a synthetic model carries `_source: xgboost_synthetic_standin`; a model trained on supplied data
carries `xgboost_trained:<data-label>`.
