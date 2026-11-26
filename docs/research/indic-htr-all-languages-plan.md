# Indic handwriting and printed-text recognition: plan for all languages with data

Status: plan, nothing run beyond the Kannada, Hindi and Gujarati baselines. Research use only until dataset licences are confirmed.
Sources: the dataset list at ilocr.iiit.ac.in/dataset and each dataset's detail page (read 2026-11-26).

## 1. What data exists

Handwritten word images, all from IIIT-INDIC-HW-WORDS, all scanned at 600 DPI, all with true text per image:

| Language | Writers | Word images | Train / val / test |
|---|---|---|---|
| Bengali | 24 | 113,076 | not read |
| Gujarati | 17 | 116,696 | 82,563 / 17,643 / 16,490 |
| Punjabi | 22 | 112,616 | 81,042 / 13,627 / 17,947 |
| Hindi | 12 | 95,431 | 69,853 / 12,708 / 12,870 |
| Kannada | 11 | 102,999 | 73,517 / 13,752 / 15,730 |
| Malayalam | 27 | 116,783 | 85,270 / 11,878 / 19,635 |
| Oriya | 10 | 101,467 | 73,400 / 11,217 / 16,850 |
| Tamil | 16 | 103,517 | 75,736 / 11,597 / 16,184 |
| Telugu | 11 | about 126,413 (page text is garbled) | 88,534 / 19,980 / 17,899 |
| Urdu | 8 | about 102,063 | 71,207 / 13,906 / 15,517 |

Marathi has no handwritten set on this site. See `docs/research/` and the open email to the authors.

Two facts shape everything below:

1. **Few writers.** Eight to twenty-seven per language. A model trained on this learns a handful of hands.
2. **The writer of each image is not named** in the tab layout (Gujarati and most others). The Hindi set is the exception, with a folder per writer. Where writers are unnamed we cannot confirm that the test set uses writers the model never saw, so those scores are optimistic by an unknown amount.

Scene text ("scanned text", confirmed by the bank owner to mean the Scene Text modality): IndicSTR12 has real photographed text for 12 languages, Hindi, Gujarati and Marathi among them, and the IIIT-Synthetic-IndicSTR sets are computer-generated. Sizes and licences have not been read yet. Printed text (the Mozhi sets, scanned book lines) is a lower priority and stays as an optional sanity check.

## 2. Phases

**Phase 0: data (per language, about 1 day for all ten).** Download the three zips, check size and zip integrity, count rows against the page, confirm no image is missing. About 4 GB per language, about 40 GB in all. Confirm each dataset's licence, which the detail pages do not state.

**Phase 1: baseline on CPU (per language).** The same recipe as Kannada, Hindi and Gujarati: small CRNN with CTC, 3,000 steps, batch 32, seed 1, 1,000 validation words. Report character error and word error. Time: about 1 hour on this machine while it stays awake, up to 18 hours if it sleeps. Kannada took 17.9 hours for that reason. Keep the machine awake or run on a server.

**Phase 2: make the numbers comparable.** For the nine languages without writer names, ask the dataset authors for writer ids, or accept that the figures are upper bounds. Report the share of test words never seen in training next to every result (Gujarati: 26.6%), since a model can pass by memorising common words.

**Phase 3: a real test on GPU.** The CPU baselines show the pipeline works. A longer schedule and a stronger model need a GPU host. Run the model comparison (the bake-off harness already merged) on the held-out sets.

**Phase 4: language families.** Languages that share a script can borrow from each other: Hindi to Marathi, Bengali to Assamese and Manipuri, and so on. Test whether a model trained on one improves the other with few samples. This is where Marathi benefits, since it has no handwriting data of its own.

## 3. Scene text plan

After the handwritten baselines, read the IndicSTR12 detail pages (sizes, licence, layout) and run the same small model on the real-photo set for Hindi, Gujarati and Marathi first, then the rest. Report character and word error next to the handwritten result for the same language. Scene text is photographed signs and boards, so it tests reading under blur, perspective and lighting, not handwriting. Keep the synthetic sets separate from the real ones in every table, since a score on generated text says little about real photos. Marathi is the one language where scene-text data exists and handwriting data does not.

## 4. What a good result would and would not mean

These are public clean word images, not cheque crops. Even a low error here does not say how a name or amount-in-words on a real cheque will read. That needs cheque-style samples from real writers, which is what the Marathi writing-sheet plan collects. A bank still needs a human to read names the model is unsure of.

## 5. Decisions needed

- Decided: "scanned text" means Scene Text. Decided: download and test one language after another, with the next language downloading while the current one trains.
- A GPU host for Phase 3, and a server or keep-awake setting for Phase 1.
- Licence confirmation per dataset before any use beyond research.
