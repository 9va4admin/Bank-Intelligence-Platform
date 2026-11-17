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

## When the bank will not provide labelled forgeries (the constraint we are designing for)

The bank has to provide something anyway: the **customers' genuine specimens for the signature vault**. That is enough to do two things
with no forged examples and no data leaving the bank.

**1. Train an embedder from genuine specimens only** (`scripts/train_signature_embedder.py`, `modules/cts/signature_training/`).
Two augmented views of the same signature (and other specimens of the same account) are pulled together; other accounts are pushed apart
(supervised contrastive loss). The augmentation imitates what changes between two captures of one signature: crop box, tilt, ink thickness,
contrast, noise, blur, JPEG, printed lines behind the ink. It runs on the bank's own hardware. The checkpoint carries a model card that always
starts `promoted: false`; the worker loads it through `signature.embedder_checkpoint` and the confirm gate stays on until a promotion is recorded.

**2. Measure the part that needs no labels.** Different customers' signatures *are* the "random forgeries", and held-out customers are
never trained on, so the training script scores the model on writers it never saw, with the same harness (FAR / FRR / EER, 95% intervals).

### Experiment on real cheques (2026-11-16, `scripts/experiments/signature_contrastive_real_cheques.py`)

119 real KBL cheque images; each cheque is one "writer". Trained on 89 (30 epochs, about 8 minutes on a CPU, no forgery labels), scored on
30 never-seen writers. Held-out "genuine" samples are made by moving and resizing the detector's crop box and re-scanning (code independent of
the training augmentation); 3 variants enrolled, 2 tested per writer; 1,500 random-forgery trials.

| | EER | forgeries accepted at the production threshold 0.85 | genuine rejected at 0.85 | threshold for <= 3% forgeries accepted -> genuine rejected |
|---|---|---|---|---|
| generic ImageNet ResNet-18 | 8.7% | **66.7%** (1001/1500) | 0 / 60 | 0.959 -> **28.3%** (17/60) |
| contrastive, trained on the 89 | **1.8%** | **2.9%** (44/1500; 95% CI 2.2-3.9%) | 1.7% (1/60) | 0.849 -> **1.7%** (1/60) |

With an easier held-out variant (re-scan only, no crop-box change) the same pattern held: generic 60.1% accepted at 0.85, trained 2.4%.

### What this shows, and what it does not

- **Shows:** training on genuine specimens alone makes the embedder separate *different people's* signatures far better than the generic one,
  on people it was not trained on, and holds up when the crop frame moves. The generic model's problem (it rates almost everyone as similar)
  is largely a training problem, not a method problem, and it is fixable on-prem with data the bank must supply for the vault anyway.
- **Does not show: skilled-forgery protection.** No forged examples exist here, and this training never sees one. A careful forger who
  copies a customer's signature is the case that matters most for fraud and it remains **unmeasured**.
- **Does not show: real genuine variation.** Held-out "genuine" samples are re-captures of one image, not a customer signing on different days
  with different pens. Real FRR will be worse than 1.7%.
- Small and unaudited: 30 held-out writers; two cheques may be the same customer (that would inflate the false-accept number and
  contaminate the train/held-out split); the signature box is a fixed frame, not the detected signature.

### What protects the bank for the risk that stays unmeasured

Signature similarity is one signal, not the control. The controls that do not depend on signature data: Positive Pay (amount, payee, number,
date against what the customer registered), the cheque-leaf vault (is this leaf issued to this account and not yet presented), stop-payment and
CBS status, duplicate detection, the two-model reads of MICR and amount, alteration detection, the fraud score, and the high-value threshold that
already sends large cheques to a human. A forged cheque usually fails one of those as well. A low signature score should send a cheque to review;
a signature mismatch must never auto-return one.

### Promotion rule when only random-forgery evidence exists

Promote an embedder to support `STP_CONFIRM` only when (a) its held-out random-forgery result clears the bank's target by the 95% interval on the
bank's *own* vault specimens with real repeated specimens per account (not re-scans), (b) the bank's risk owner has accepted in writing that
skilled-forgery risk is carried by the other controls above for the value band concerned, and (c) the decision is recorded (the model card
`promoted` flag is set by that recorded decision, never by training). Reviewer decisions collected in shadow mode can add evidence over time,
but genuine skilled forgeries are rare, so they will not by themselves prove a skilled-forgery rate.

## Public benchmark with real forgeries: CEDAR (2026-11-17) - and a retraction

CEDAR (55 writers, 24 genuine + 24 forgeries each; from the CEDAR group's own server, used for a temporary evaluation, never committed or shipped). Writer-disjoint: trained on 40
writers, scored on 15 held-out writers, two independent splits (A, B), 5 specimens enrolled per writer, 360 forgery trials per split. Scripts: `scripts/experiments/signature_cedar_benchmark.py`
and `scripts/experiments/signature_cedar_pairs.py`. BHSig260 (Hindi/Bengali) could not be obtained from an open, trustworthy source (the original short link is dead; the Hugging Face copies
are access-gated or third-party mirrors of gated data), so it was not used.

### RETRACTION: an earlier version of this section said forged examples make a trained embedder clearly beat the generic one (skilled-forgery EER 0.8-1.4% against 2.5-7.4%). That was wrong.

In CEDAR the **paper tone alone separates every genuine image from every forged one** (median grey level: genuine mean 239.8, forged mean 253.5; AUC 1.000 over all 2,640 images). Genuine
signatures were scanned on grey paper, forgeries on white. Any model that is sensitive to paper brightness "detects forgeries" perfectly without looking at the signature, and a model trained
with forged negatives learns exactly that shortcut. The earlier numbers measured paper colour. They were found by looking at the images, not by the metrics.

### Valid result: paper removed (background normalised, Otsu-binarised to black strokes on white; the same treatment for every image)

After cleaning, ink fraction no longer separates the classes (AUC 0.47; 0.5 = no leak). Skilled-forgery EER, held-out writers, split A / split B (lower is better):

| model | skilled-forgery EER (A / B) | skilled forgeries accepted at 0.85 (A / B) | genuine rejected to hold forgeries at 3% (A / B) | other-writer EER (A / B) |
|---|---|---|---|---|
| generic ImageNet ResNet-18 | 22.2% / 23.9% | 99.2% / 99.7% | 73% / 76% | 5.2% / 5.2% |
| trained, genuine specimens only (224 px, no augmentation) | 18.9% / 22.2% | 50.3% / 55.6% | 78% / 81% | 2.1% / 3.2% |
| trained + real same-writer forgeries as negatives | 15.8% / 21.1% | 27.5% / 38.1% | 79% / 75% | 2.1% / 2.8% |
| trained + synthetic forgeries (distorted genuine) as negatives | 20.3% / 22.5% | 33.1% / 61.1% | 88% / 77% | 2.8% / 4.9% |

### What this actually shows

- **No tested method is usable against skilled forgeries.** Every skilled-forgery EER is 16-24%; holding forgeries to 3% would reject three quarters or more of genuine signatures.
- **Training on genuine signatures helps against *other customers* (EER 5.2% -> 2-3%), barely against forgeries** (22-24% -> 19-22%). The earlier cheque experiment (other writers only) stands as an other-writer result and nothing more.
- **Real forged negatives help a little** (about 1-3 points of EER); **synthetic forgeries made by distorting genuine signatures help not at all** (20.3% / 22.5% against 18.9% / 22.2% for genuine-only). With no forged examples there is no demonstrated way, here, to learn skilled-forgery detection.
- **Shape-only is a harsh test and a fair one for this question,** but it also discards ink darkness and pressure cues that a real pen-and-scanner pipeline retains; I cannot say whether those are real signals or more dataset artefacts.
- Limits: one benchmark, two splits of 15 writers, 360 forgery trials per split, a small fine-tuned last block (300 steps), experiment scripts rather than the production trainer. Different methods (full pair training at higher
  resolution, stroke-level features, a pretrained signature model) were not tried. These results do not say skilled forgery is undetectable, only that none of what was tried detects it.

### Consequences

- Signature similarity cannot be what protects the bank against a careful forger. Positive Pay, the cheque-leaf vault, stop-payment and balance checks, the fraud score, alteration detection and the high-value rule remain the controls; signature similarity routes cheques to review.
- **Promotion rule:** an embedder is promoted to support `STP_CONFIRM` only if it clears a skilled-forgery test **after paper-tone and other dataset artefacts are removed**, on data the bank accepts, and is not worse than the one it replaces; plus the bank's written acceptance of the residual risk. No embedder here comes close.
- Any future public-dataset result must first be checked for this kind of leak (a simple classifier on global statistics such as paper tone, ink fraction, image size); `signature_cedar_pairs.py` prints that check.
