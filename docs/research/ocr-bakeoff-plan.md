# OCR / VLM bake-off plan for cheque field extraction (plan, 2026-11-23)

Status: **plan only. Nothing has been run.** Follows [cheque-extraction-models-2026-11.md](cheque-extraction-models-2026-11.md).
Question to answer: *which open-weight model(s), served on-premises, read ASTRA's real cheque fields best, in Latin, Kannada and Devanagari, printed and handwritten, and which pairing gives the lowest rate of a wrong value being shown?*

## 1. What we know about the starting point (from the repo)

- Real data: 70 KBL instruments (Lot 1: 20, Lot 2: 10, Lot 3: 40) under `docs/cheques/KBL/` (untracked and git-ignored on purpose; never commit it).
- Existing scorer: `scripts/eval_inward.py` and `modules/cts/evaluation/inward_eval.py`, with 95% Wilson intervals and the "wrong value shown vs withheld" split. Result on the current pipeline: payee exact 41/55 = 74.5%, payee wrong-shown 1/55, sort code wrong-read 4/70, cheque number wrong-read 3/70, amount figures wrong-read 5/30 (docs/evaluation/inward_evaluation.md). **Those are the numbers to beat.**
- Ground truth is by-eye reading by one person and "can itself be wrong". The truth files used for that run (`all_lots_l12_truth.json`, `lot3_truth.json`) are **not in git**; locate them or recreate them first (step 1).
- Current second-read model: `cts.field_reread_model = qwen3-vl-32b`; payee re-read similarity gate 0.99. The earlier 70-cheque run used a **cloud** model (a documented dev-only exception); the cloud account later ran out of credits. The bake-off must use **local open weights only**.
- **This development machine has no GPU** (no `nvidia-smi`). The bake-off needs a GPU host on the bank-side network (see step 3). Real cheque images must not go to a cloud service.
- Field zones can be cut by `modules/cts/preprocessing/zone_extractor.py`, so every model can be fed identical crops.

## 2. The decision this plan serves

Not "which model has the best benchmark". It is: **which primary reader, and which independent second reader of a *different* model family, minimise the rate of a wrong value being shown, at an acceptable review rate, per script and per field.** A pair is judged by its disagreement behaviour, because a single read of handwriting is never trusted (CLAUDE.md 2.11).

## 3. Candidates

| # | Model | Why it is in | Serving | Open items to check first |
|---|---|---|---|---|
| A | dots.ocr | best open model on Kannada, Devanagari, Telugu, Gujarati in GlotOCR (printed) | vLLM if its model card says so; else its own server | licence; vLLM support; size on card |
| B | dots.mocr (dots.ocr 1.5) | same family, slightly higher Kannada (87 vs 80) | as A | licence |
| C | Qwen3-VL-8B | control: already tested by the project, mainstream vLLM | vLLM | licence (Apache-2.0 expected: verify) |
| D | Qwen3-VL-32B | current reread model; may differ from 8B on Indic | vLLM, 4-bit if memory is short | memory |
| E | HunyuanOCR | strong Devanagari and Gurmukhi, weaker Kannada (33) | vLLM recipe exists | licence (custom licences are common) |
| F | PaddleOCR-VL-1.5 | strong Tamil and Telugu; Kannada 0 in GlotOCR; official vLLM | vLLM | confirms Kannada failure on real cheques |
| G | GOT-OCR2.0 | already named in the design; base of HindiOCR-VLM | transformers | licence; Indic weakness expected without fine-tune |
| H | Current pipeline (baseline) | what runs today | as deployed | none |

Optional later: Bodhan IndicOCR (gated weights, handwriting claimed for Kannada and Hindi; only if its licence and weights are verified), and any model that appears with a convincing handwritten-Indic result.

**Gate 0 (before any download):** for each model record licence (from the licence file, not the blog), weight size, and whether vLLM serves it. A model with an unusable licence or no way to serve it on-premises is dropped here with the reason written down.

## 4. Test data and ground truth

1. **Recover or recreate the by-eye truth** for the 70 instruments and save it, with a content hash of each image, in a git-ignored folder; commit only a schema and a README.
2. **Second labeller.** Have a second person label payee, amount words, amount figures and date independently for the handwritten fields; disagreements are listed and resolved by the bank officer. One-person truth is the weakest part of the current evidence.
3. **Strata** (record each instrument's strata so results can be broken down): script of payee (Latin, Kannada, Devanagari, other), print vs handwritten, field (payee, amount words, amount figures, date, MICR band, printed bank/branch text), scan quality (good, poor).
4. **Size reality.** 70 instruments give roughly 55 scoreable payees and 30 amounts. That can **rank** models and show large differences; it **cannot prove** a 99% target (299 clean samples are needed for that, per the evaluation doc). Plan to grow the labelled set to at least 300 instruments from the bank during the pilot, and say "NOT DEMONSTRABLE" until then.
5. **Held-out discipline.** Pick prompts and thresholds on a tuning split (about 30 instruments) and report only on the remaining ones, so the winner is not chosen on the data it is reported on.

## 5. Protocol

- **Identical inputs:** every model gets the same zone crops (from the zone extractor) and, separately, the full image. Same crop sizes, same resolution (the real captures are about 96 to 200 dpi; the CTS-2010 standard is 200 dpi).
- **Identical task:** one JSON schema (payee, amount words, amount figures, date, plus MICR for the band crop), the same prompt text, temperature 0, a fixed maximum output length. **Length guard** on every model: output longer than a set multiple of the expected length is a failure, because DeepSeek-style repetition loops were reported.
- **Three runs per model** with different prompt wordings (two with a different order of fields) to measure how much the result depends on prompting; report the median.
- **Scoring**, per field and per stratum, with 95% Wilson intervals:
  - exact match, and character error rate on normalised text (case, spacing, Unicode normalisation, digit forms);
  - **wrong value shown** (the dangerous error) versus **withheld or empty** (the costly one), reusing `inward_eval`;
  - script correctness (did it answer in the right script at all: the failure mode where a model writes confident text in the wrong script is counted separately).
- **Pair analysis:** for every ordered pair (primary, second reader) from different families, apply the existing agreement rule (`cts.payee_reread_min_similarity`) and report: wrong shown, correct but sent to a human, and unread. The best pair is the one with the lowest wrong-shown at a review rate the bank accepts.
- **Efficiency:** per-crop latency p50 and p95, GPU memory, and batch throughput on the actual host, so a model is not chosen that cannot keep up with the clearing window.
- **Comparison between models** uses a paired test on the same items (McNemar or a paired bootstrap), not two separate intervals. A model is declared better only when the paired difference clears zero.

## 6. Steps and what each produces

| Step | Work | Output |
|---|---|---|
| 0 | Licence, size and vLLM check for A to G | one table in this folder, with the licence text location for each |
| 1 | Recover/recreate truth; second labeller; strata tags | truth files (git-ignored) plus a schema doc |
| 2 | Build the harness (test-first): `modules/cts/evaluation/ocr_bakeoff.py` (loading, scoring, pairing) and `scripts/bakeoff_ocr.py` (runs a named model against the crops and writes a result JSON) | tests; no model needed for the scoring tests |
| 3 | Provision a GPU host on-prem and serve the candidates one at a time | serving recipe per model |
| 4 | Run all candidates on the tuning split, fix prompts, then run the held-out split | raw result JSON per model (git-ignored) |
| 5 | Score, pair analysis, efficiency | `docs/evaluation/ocr_bakeoff.md` with intervals and a plain verdict per field and script |
| 6 | Decision | recommended primary and second reader per script, plus what is still not demonstrable |

## 7. Hardware (estimates, to confirm on the host)

Weights alone are about 2 bytes per parameter in 16-bit: roughly 2 GB for a 1B model, 16 GB for an 8B model, 64 GB for a 32B model; 4-bit quantisation cuts that to about a quarter. Add working memory for images and the cache. So a **single 24 GB GPU** can serve every candidate except the 32B model; a 48 to 80 GB GPU (or the pilot's 4 x RTX 4090 with the 32B model quantised or split) covers all of them. The design's pilot hardware (4 x RTX 4090) is sufficient to run the bake-off.

## 8. Decision rules (written before running, so they cannot be bent afterwards)

- **Adopt as primary reader** only if, on held-out data, its wrong-shown rate is lower than the current pipeline's with a paired difference that clears zero, for that field and script.
- **Adopt as second reader** only if it belongs to a different model family from the primary and the pair's wrong-shown rate is lower than any single model's.
- **No model is promoted for handwritten Indic payee or amount words on this data alone.** If the best open model still gets handwritten Kannada or Devanagari wrong more often than the target allows, the result is "route to human review, and train a specialist" (see [iiit-indic-hw-words-training.md](iiit-indic-hw-words-training.md)).
- A result with fewer than the needed samples is reported as such, never as a pass.

## 9. Risks

- Truth quality: one person's reading. Mitigated by the second labeller.
- Small n: the bake-off ranks; it does not prove. The pilot data must close that gap.
- Prompt sensitivity: three prompt variants and a tuning split.
- Licence surprises: Gate 0.
- Printed-benchmark optimism: the published Kannada numbers are for rendered printed text. Real cheques mix handwriting, stamps and ruled lines; expect lower numbers and judge only on the bake-off.
- Cost of GPU time: modest (inference on a few hundred crops per model).

## 10. Not in this plan

Signature comparison (see the research brief: train on the bank's genuine specimens, evaluate with the existing evaluator), the fraud model, and the full inward pipeline run (this isolates the reading step only; re-run `scripts/eval_inward.py` end to end once a reader is chosen).
