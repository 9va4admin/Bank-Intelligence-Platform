# Signature verifier evaluation

How to find out, with numbers, whether a signature embedder is good enough to support an automatic confirm.
Tool: `scripts/eval_signature_verifier.py` (maths in `modules/cts/evaluation/signature_eval.py`, dataset loading in
`signature_dataset.py`). Any embedder can be scored: the generic stand-in, a trained Siamese network, a vendor model, or a per-account
classifier built on top of one. Several can be compared side by side on the same data.

## What it measures

Protocol, the same as production scoring: a writer is enrolled with *k* genuine specimens (the vault); a trial scores the **best cosine
similarity** to any enrolment vector.

| Error | Meaning | Why it matters |
|---|---|---|
| **FAR** (false accept) | a forgery scores at or above the threshold | the dangerous error: an automatic confirm of a forged cheque |
| **FRR** (false reject) | a genuine signature scores below the threshold | the costly one: a human reviews a good cheque |
| **EER** | the error rate where FAR = FRR | one number to compare embedders independent of the threshold |

Forgery trials come in two kinds: `SKILLED_FORGERY` (labelled, a real attempt to copy that writer's signature) and `RANDOM_FORGERY`
(another writer's genuine signature, built automatically). **Random forgeries are the easy case**: a model that fails them is clearly
unusable, but one that passes them is not thereby safe against skilled forgeries.

Every rate has a 95% Wilson interval. Nothing is reported as meeting a target unless the interval clears it; a good point estimate on too few
trials is reported as `NOT DEMONSTRABLE`. The report also says how many error-free forgery trials are needed (299 shows FAR < 1% at 95%).
`threshold_for_target_far` gives the least strict threshold that meets the FAR target and the FRR you pay for it.

## Data it needs

A manifest CSV: `path, writer_id, label` with label `GENUINE` or `SKILLED_FORGERY`. Images are signature crops, or whole cheques with
`--bbox x1,y1,x2,y2` (fractions) to cut the signature out.

For a result worth acting on, per the report's own arithmetic: at least a few hundred skilled-forgery trials and enough genuine samples per
writer (more than *k* each) from **real, varied captures** (different pens, dates, scanners, cheque backgrounds). That has to come from the bank
(signature cards, cheques with confirmed genuine/forged status), kept on-premises. Public datasets (CEDAR, GPDS, BHSig260) can train a base
model, but the decision data must be the bank's own cheques.

```
python scripts/eval_signature_verifier.py --manifest data/sig/manifest.csv \
    --embedder generic --embedder my_pkg.model:TrainedEmbedder \
    --k-enrol 3 --threshold 0.85 --max-far 0.03 --out docs/evaluation/signature_eval.json
```

## Smoke result on real cheque images (2026-11-16): what it shows and what it does not

30 real KBL cheques, the signature region cut with a fixed frame, each cheque treated as one writer with 5 re-scan style variants (rescale,
slight rotation, noise, blur) as the "genuine" samples; 3 enrolled, 2 tested per writer; the generic ImageNet ResNet-18 embedder.

| | result |
|---|---|
| Random-forgery FAR at threshold 0.85 | **972 / 1500 = 64.8%** (95% CI 62.3% - 67.2%) |
| FRR at 0.85 | 0 / 60 |
| Threshold needed for FAR <= 3% | 0.958, at which FRR was 2 / 60 |
| EER | 3.4% |

**Read this carefully.** It confirms that at the production operating point the generic model accepts about two thirds of other people's
signatures. The low EER and the "workable" 0.958 threshold are **not** evidence the model is usable: the genuine samples here are
re-scans of the *same* image, so they are near-duplicates of the enrolled one and trivially separable. Real genuine signatures vary far
more, which pushes FRR up sharply at any threshold that holds FAR down. Skilled forgeries were not tested at all (none exist in the data).
The 65% FAR is the meaningful number; the rest is optimistic by construction.

## Decision rule this feeds

An embedder can be promoted to support `STP_CONFIRM` only when, on the bank's own labelled data, its skilled-forgery FAR at the chosen
threshold is shown below the bank's target by the 95% interval (verdict `MEETS`), and the FRR at that threshold is a reviewer workload
the bank accepts. Until then the verifier stays flagged untrained and the confirm gate stays on.
