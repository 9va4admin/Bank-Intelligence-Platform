# IIIT-Indic-HW-Words: what it is, and how ASTRA can train on it (research and plan, 2026-11-23)

Sources read for this brief (primary): the [dataset page](https://cvit.iiit.ac.in/research/projects/cvit-projects/iiit-indic-hw-words), its README, the ICDAR 2021 paper (Gongidi and Jawahar), the CVIP 2024 PARSeq paper (Lalitha, Mondal, Jawahar) and its repository page, the companion [Devanagari and Telugu dataset page](https://cvit.iiit.ac.in/research/projects/cvit-projects/indic-hw-data), and the repository pages of the three open code bases. Nothing here has been downloaded or trained yet.

## 1. What the dataset is (verified)

| Item | Fact |
|---|---|
| Content | Handwritten **word images** with Unicode labels, 8 scripts: Bengali, Gujarati, Gurumukhi (Punjabi), **Kannada**, Odia, Malayalam, Tamil, Urdu. **Devanagari (Hindi) and Telugu** come from two earlier sets, IIIT-HW-Dev (about 95K words, 1.8 GB) and IIIT-HW-Telugu (about 120K words, 3.7 GB) on the companion page. Together: all 10 major Indic scripts. |
| Size, Kannada | **73,517 train, 13,752 validation, 15,730 test** word images; average word length 9 characters; 83 distinct characters; lexicon about 11,766 words; about 103K instances in total. The Kannada zip is **5.19 GB**. |
| How it was made | Writers wrote a chosen vocabulary in a coded grid on A4 paper; pages were **scanned at 600 dpi** on a flatbed scanner; word images and labels were cut out automatically; about 4% (wrongly cut, printed text, QR codes, box borders) were removed. Average image about 288 x 1120 pixels. Almost no other pre-processing. |
| Writers | 135 writers aged 18 to 70 across the 8 scripts. **Per script the 2024 paper lists about 8 to 27 writers; Kannada has 11.** |
| Split | About 70% / 15% / 15% of the **instances**. The papers state 9 to 12% of test labels are out-of-vocabulary. **I found no statement that writers are held out of the training set.** |
| File format | Zip per script with train, val and test image folders; label files `train.txt`, `val.txt`, `test.txt` with rows `<FileName>, <VocabId>`; `vocab.txt` maps each id (line number from 0) to the Unicode string. |
| Licence | **Not stated** on the page, the README or the paper (they say it is "available publicly"). Must be confirmed with the authors before any use inside a bank product. The page asks users to cite the paper. |

Code that works with it: [sanny26/indic-htr](https://github.com/sanny26/indic-htr) (MIT; the 2021 baseline: spatial transformer + CNN + BLSTM + CTC), [LalithaEvani/Indic-HTR-CVIP-2024](https://github.com/LalithaEvani/Indic-HTR-CVIP-2024) (Apache-2.0; a fork of the PARSeq code; says trained models and code are public), [iitb-research-code/indic-trocr](https://github.com/iitb-research-code/indic-trocr) (Apache-2.0; TrOCR for Indic words; needs a language-specific text decoder).

## 2. What published models achieve on it (verified from the papers)

Kannada, word level, no lexicon unless stated:

| Model | CER | WER | Notes |
|---|---|---|---|
| 2021 baseline (hw-resnet + BLSTM + CTC, with a spatial transformer) | **1.03%** | **5.90%** | test set; out-of-vocabulary subset: CER 1.59, WER 9.39 |
| PARSeq fine-tuned (2024) | 1.13% | 6.55% | transformer; lower word error than the earlier CRNN for Hindi and Malayalam, slightly higher for Kannada (the paper's own comparison table uses different baseline figures from the 2021 paper, so treat small differences as noise) |
| PARSeq, without and with pre-training on printed text | | 11.59 to 7.28 | pre-training on printed text lowered the word error rate in all 7 scripts tested (by more than 4 points in 5 of them) |
| PARSeq with lexicon post-correction (5 candidates) | 0.21% | 0.39% | **optimistic: the lexicon is built from the train, validation and test words together**, so the test words are in the dictionary |

Hindi (PARSeq): WER 6.93, CER 2.93. Tamil: WER 8.02, CER 1.43. Malayalam: WER 5.97, CER 0.98.

Training the 2024 model, per its repository: **4 GPUs, about 160,000 iterations, batch size 254**, maximum label length 35, one-cycle learning rate for pre-training then Adam with stochastic weight averaging.

## 3. What these numbers do NOT tell us about cheques

1. **Isolated words on clean forms** versus **fields on cheques**: payee names are several words, amounts in words are phrases, and the field sits on a printed form with ruled lines, stamps, and different pens.
2. **600 dpi flatbed scans** versus cheque captures at about 96 to 200 dpi. ASTRA's own test showed resolution is not the main bottleneck, but real capture quality is far below this data.
3. **Few writers** (Kannada: 11). Handwriting from many unseen people is the real task. With no stated writer hold-out, the 1% character error rate may be writer-dependent.
4. **A small closed vocabulary** (about 12K Kannada words). Models can lean on it; 9 to 12% out-of-vocabulary in the test labels is the only check. Payee names are open vocabulary.
5. **No cheque content**: no amounts in words, no dates, no signatures, no personal names as written on a cheque.

So a model trained on this set is a **starting point for a handwriting reader**, not evidence that cheque handwriting is solved. The only number that counts is the model's error on real cheque crops.

## 4. How to train on it: options

| Option | Model | Pros | Cons |
|---|---|---|---|
| **1. PARSeq** (recommended start) | small transformer from the PARSeq family (the original is about 24M parameters: verify) | published Kannada, Hindi, Tamil results; Apache-2.0 code ready to run; gives per-character probabilities for a real confidence; runs on one GPU or CPU | word-level; needs line handling for multi-word fields |
| 2. CRNN baseline (indic-htr) | CNN + BLSTM + CTC | smallest, MIT licence, runs on CPU; lowest published Kannada error | older design; same word-level limit |
| 3. Fine-tune a VLM (GOT-OCR2.0 as in HindiOCR-VLM, or dots.ocr) | LoRA on the winner of the bake-off | can read whole lines and fields; the IIIT Hindi paper shows the route | needs a larger GPU; hallucination risk; Kannada not done by anyone publicly |
| 4. Indic TrOCR | TrOCR with an Indic decoder | transformer | needs a language-specific decoder model per script; more work |

Recommendation: **start with PARSeq, with the CRNN as the cheap control**, as a specialist reader that sits **beside** the VLM, not instead of it (section 6). Fine-tune a VLM only if the bake-off winner is close and the specialist cannot reach the target.

## 5. Training plan

**Phase A: reproduce the published result (a sanity check, about days of effort).**
1. Ask the dataset authors for the licence and for permission to use it in a commercial bank product (contact on the dataset page). Do not proceed beyond research use without it.
2. Download the Kannada and Hindi data (5.19 GB for Kannada; 1.8 GB for Devanagari) on a machine with disk and a GPU. The data is public, so this step may use a rented GPU: **no bank data is involved**.
3. Convert to the format the code expects (LMDB, via the repo's `create_lmdb_dataset.py`), train the PARSeq configuration from the 2024 repository, and check that the published Kannada and Hindi numbers are reproduced. If they are not, stop and find out why before going further.
4. Inspect the file names and any metadata for a **writer identifier**. If one exists, rebuild the split by writer so the test measures unseen writers; if not, state that the published numbers are not writer-held-out.

**Phase B: make it resemble cheque captures.** Augment training images to imitate the target: downscale from 600 to about 200 dpi (and 96), JPEG compression, blur and noise, ruled lines and printed background behind the ink, stamp-like overlaps, blue and black pens, slight rotation and skew, crop jitter. Then measure how much the clean-data model loses on degraded versions of the held-out set, and how much augmentation recovers.

**Phase C: from words to fields.**
- Payee and similar fields hold several words: build synthetic lines by stitching two to four word images with realistic gaps and train a line reader (labels are the concatenated words), or detect and read word by word.
- **Amount in words** has a very small vocabulary and a fixed grammar (numbers, "lakh", "thousand", "only"): constrain decoding to that grammar, the largest single accuracy lever for that field. The grammar also gives a second check against the figures.
- Names are open vocabulary: do not force a dictionary. Compare against the bank's own account-holder names only where the field is the drawee, as already designed.

**Phase D: evaluate where it matters.** (1) the IIIT test set (sanity only); (2) the bank's real cheque crops from the bake-off set, scored with the existing evaluator: exact match, character error, **wrong value shown versus withheld**, with 95% intervals; (3) the pair analysis: the specialist as the independent second reader against the bake-off winner.

**Phase E: learn from the bank.** The platform already collects reviewer corrections (the OCR feedback loop, retrain threshold in settings). Fine-tune the specialist **on the bank's own labelled crops, on-premises**, and promote a new version only when it beats the current one on held-out data by the configured margin. Bank images never leave the bank.

## 6. How it fits ASTRA

- Run it as a small **sidecar service** like the existing Indic OCR sidecar, returning text plus per-character probabilities.
- Use it as the **independent second reader for handwritten payee and amount words**. The system already withholds a result when two reads disagree; today both reads come from vision-language models that fail the same way. A different family (a trained handwriting model with a real confidence) makes disagreement informative.
- A specialist's confidence is **calibrated on the held-out set before it is used to gate anything**, and a low confidence routes to human review as everywhere else.
- Keep the rules: no threshold in code (settings only), message registry for wording, audit on every change, no bank data off-premises.

## 7. Compute and effort (estimates)

The authors used 4 GPUs for about 160,000 iterations. A single 24 GB GPU can run the same recipe with a longer schedule or a smaller batch; the exact time on ASTRA's hardware is **unmeasured**. Inference is light (a small model): milliseconds per crop on a GPU and workable on CPU. This machine has no GPU, so Phase A needs a GPU host (rented is acceptable for the public data only).

## 8. Risks and open questions

- **Licence** of the dataset is unstated: the main non-technical blocker.
- Domain gap (section 3): the specialist may read IIIT words well and cheques poorly; Phase B and D exist to find out early.
- Writer diversity: 11 Kannada writers. Expect the bank's own data to matter more than this dataset.
- Words are not lines: Phase C adds engineering.
- Reported post-correction results are inflated by a lexicon containing test words; do not quote them.
- No Kannada result exists in the literature for **cheque** handwriting; ours would be the first, so measure carefully.

## 9. Immediate next steps

1. Email the dataset authors about the licence (needs a person: the contact address on the page is hidden behind a script).
2. Provision a GPU host (shared with the bake-off, see [ocr-bakeoff-plan.md](ocr-bakeoff-plan.md)).
3. Phase A on Kannada first (the script that matters for the pilot bank), then Hindi.
