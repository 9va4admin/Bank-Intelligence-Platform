# Handwriting recognition on CPU: results for Gujarati, Kannada and Hindi

Research use only. The IIIT-Indic-HW-Words data has no stated licence, and the authors' permission is needed before any use in a bank product. No customer or bank data was used. Tools: `scripts/htr_research/`.

> **Correction (2026-11-27).** The first version of this document, written 2026-11-24, reported Kannada and Hindi figures from quick pipeline checks as if they were results. They were not: a fixed 3,000-step schedule (about one pass over the data), scored on a 1,000-image sample of the validation split, with the test split never scored. Those numbers are kept below for the record, marked **superseded**. The proper runs, described next, replace them.

## Proper runs (current)

Method, from `scripts/htr_research/train_full.py`:

- every training image in every epoch, with small random changes to training images only (tilt, slant, width, blur, contrast);
- the **whole validation split** scored after every epoch, the best checkpoint by validation character error kept, the learning rate halved when validation stalls, early stopping after 4 epochs without improvement (or 30 epochs);
- the **whole test split scored once**, at the end, with the best checkpoint, with 95% intervals from resampling the test images;
- the same small CRNN with CTC loss, one CPU, seed 1.

### Gujarati (finished)

Best epoch 17 of 19 trained. Stopped by hand after epoch 19, because validation had been flat since epoch 17 and the saved best checkpoint is what the test score uses. 82,563 training, 17,643 validation and 16,490 test images.

| Test split, all 16,490 images | Character error | Word error |
|---|---|---|
| Overall | **3.4%** (95% interval 3.2% to 3.5%) | **16.6%** (16.0% to 17.2%) |
| Words seen in training (12,105) | 2.6% | 13.1% |
| Words never seen in training (4,385) | 5.5% | 26.3% |

If the model answers only when its confidence is at least 0.95, it answers 65% of words and reads 91% of those exactly right (83% of all words are exactly right without that filter).

The earlier quick check on Gujarati had given 12.9% character error and 52.4% word error, a large difference caused by the method, not the model.

**Caveat.** The Gujarati files do not name the writer of each image, so we cannot confirm that the test writers are absent from training. The test score may be optimistic by an unknown amount.

### Kannada and Hindi

Kannada is training on the proper method; its result will be added when it finishes. Hindi follows. The Hindi folder was found damaged on 2026-11-27 (all test images and most validation images missing, cause unknown) and was re-extracted from the original archive, verified complete, before use.

### Other languages

Bengali, Punjabi, Malayalam, Tamil, Telugu, Oriya and Urdu are downloaded and queued. Two data problems were found and fixed on the way: Oriya's validation and test images had unpacked one folder too deep, and about 15 Urdu label rows use a space instead of a tab.

## Superseded: quick pipeline checks (2026-11-23 and 2026-11-24)

Same small CRNN, 3,000 steps of 32 images (about 1.3 passes), scored on 1,000 validation images only. Do not quote these figures.

| Run | Character error | Word error | Test setting |
|---|---|---|---|
| Kannada, 3,000 steps | 5.0% | 28.3% | unseen words (writers not identifiable) |
| Hindi, 3,000 steps | 21.1% | 63.4% | unseen writers (7 train, 2 val, 3 test writers; no writer in two splits) |

The Hindi figure is the only one that measured new handwriting, and it was poor: a model trained on 7 writers reads new writers badly. That conclusion is likely to stand for Hindi until the proper Hindi run reports.

## What these results do and do not show

- **The pipeline works** and, trained properly, reads held-out word images far better than the quick checks suggested.
- **New words are about twice as hard as known words** (Gujarati: 26.3% against 13.1% word error), so more varied words and writers would help most.
- **Not cheque accuracy.** These are clean word images from a few writers, not cheque crops with stamps, ruled lines, mixed ink and varied scans. A person must still read names the model is unsure of.
- **One seed.** No repeat runs yet.
- **No comparison with large vision models.** That is the bake-off (`docs/research/ocr-bakeoff-plan.md`), which needs a GPU host.

## Next steps

1. Finish the proper runs for all ten languages (`docs/research/indic-htr-all-languages-plan.md`). On this CPU a language takes about 10 to 20 hours.
2. Move to a GPU host for longer runs and the model comparison; the pipeline already takes a device setting.
3. Get the authors' permission to use the data in a product, or keep it to research.
4. Marathi: the IIIT camera-captured dataset (IIIT-Indic-HW-UC) includes Marathi, but no working download was found (its project page is gone and the ICDAR 2025 download links return 404); an email to the authors is drafted. Collecting writing sheets from real writers is the fallback.
5. Collect cheque-style handwriting from many writers: for payee names the number of writers matters more than the number of images.
6. Repeat with several seeds before quoting any figure.

## Reproduce

```
python scripts/htr_research/train_full.py --root <dataset> --layout <ids|text|gt> --out-dir <run folder> \
  --max-epochs 30 --patience 4 --lr 0.001 --batch-size 32 --seed 1 --height 64 --max-width 320 --workers 6
```

A run resumes from its last finished epoch if interrupted (`--fresh` starts over). Result files are kept outside the repository.
