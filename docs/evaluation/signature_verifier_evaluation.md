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

## Public benchmark with real skilled forgeries: CEDAR (2026-11-17) - it contradicts the optimistic reading above

CEDAR (55 writers, 24 genuine + 24 forgeries each; from the CEDAR group's own server, used for a temporary evaluation, never committed or shipped).
Writer-disjoint: trained on 40 writers, scored on 15 held-out writers (5 specimens enrolled per writer, 360 skilled-forgery and 750
random-forgery trials). Script: `scripts/experiments/signature_cedar_benchmark.py`. BHSig260 (Hindi/Bengali) could not be obtained from an open, trustworthy source
(the original short link is dead; the Hugging Face copies are access-gated or third-party mirrors of gated data), so it was not used.

| model (held-out writers) | skilled-forgery EER | random-forgery EER | skilled-forgery FAR at 0.85 | genuine rejected at 0.85 |
|---|---|---|---|---|
| generic ImageNet ResNet-18 (224 px) | **2.5%** | 9.5% | 72.5% | 0% |
| contrastive, genuine signatures only (128 px, 8 epochs) | **21.4%** | **3.9%** | 16.1% | 33.3% |
| contrastive, genuine + forgeries as extra negatives (128 px, 8 epochs) | **20.3%** | **1.8%** | 21.4% | 19.3% |

(Zero-shot, all 55 writers: the model trained only on KBL cheque crops scored skilled-forgery EER 15.3% against the generic model's 4.7%, random-forgery EER 2.3% against 5.4%.)

### What this changes

- **The genuine-only embedder separates different people better, and separates skilled forgeries WORSE than the generic one on this benchmark.** That is the opposite of
  what the cheque experiment above could suggest. Random-forgery evidence alone must never be read as protection against forgery.
- **Forged negatives did not fix it in this setup.** EER stayed about 20%. Untested confounds: the trained models ran at 128 px against 224 for the generic one; only 8 epochs;
  only 40 training writers; and the training augmentation (crop, blur, thickness, noise) teaches invariance to exactly the small differences that give a forgery away.
  A recipe without those (higher resolution, gentler augmentation, pair training as in SigNet) is the obvious next experiment; none of it has been run.
- **The generic embedder looks strong on CEDAR ranking (EER 2.5-4.7%) while accepting 72% of forgeries at the production threshold 0.85.** CEDAR is known to be easy and its
  genuine and forged images differ in ways a model can exploit that a real forger would not leave; and it is pen-on-paper, not cheques. Do not read 2.5% as a bank-ready number either.
- **Promotion rule, tightened.** A trained embedder must not be promoted on random-forgery evidence. It must also be scored on skilled forgeries (this benchmark is the minimum; the bank's own
  confirmed forgeries are the real test) and must not be worse than the model it replaces on them. Until a recipe clears that, the confirm gate stays on and signature similarity remains a
  review-routing signal only.
