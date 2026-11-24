# Handwriting recognition: CPU baseline results (Kannada and Hindi)

Run on 2026-11-23 and 2026-11-24 with the tools in `scripts/htr_research/`. **Research use only.** The IIIT-Indic-HW-Words data has no stated licence, and the authors' permission is needed before any use in a bank product. No customer or bank data was used.

## What was run

A small CRNN with CTC loss, trained from scratch on a CPU, then scored on 1,000 validation word images. The same settings were used for both languages.

| Setting | Value |
|---|---|
| Model | small CRNN + CTC (`scripts/htr_research/crnn.py`) |
| Steps, batch | 3,000 steps of 32 images, about 96,000 images, roughly 1.3 passes over the training set |
| Learning rate, seed | 0.001, seed 1 |
| Image size | height 64, maximum width 320 |
| Hardware | one CPU, no GPU |
| Scored on | 1,000 images sampled from the **validation** split (not the held-out test split) |

## Results

| Run | Training images | Characters | Test setting | Character error | Word error | Training loss, first to last | Wall time |
|---|---|---|---|---|---|---|---|
| Kannada, short check (400 steps, 8,000 images) | 73,517 | 83 | unseen words | 90.9% | 100% | 7.14 to 3.28 | 11 min |
| **Kannada, 3,000 steps** | 73,517 | 83 | unseen words | **5.0%** | **28.3%** | 4.58 to 0.20 | 17.9 h (see note) |
| **Hindi, 3,000 steps** | 69,853 | 108 | unseen writers | **21.1%** | **63.4%** | 4.85 to 0.36 | 1.0 h |

Note on Kannada's time: the run started at about 23 images per second, then fell to about 1.4 for most of it. The likely cause is the computer going to sleep. Hindi ran at about 27 images per second throughout. The Kannada accuracy is not affected, only the time.

## What the two tests measure

The two numbers are **not comparable**, because the test setting differs.

- **Kannada:** the label files do not identify writers, so unseen writers cannot be tested. About 41% of test words never appear in training, so the model has to read words it has not memorised. The validation split probably shares many words with training.
- **Hindi:** writers are identifiable. Training uses 7 writers, validation 2 and test 3, and no writer appears in more than one split (checked by the tool, which stops if one does). Every test word appears in training, so this measures **new handwriting**, not new words.

## What this shows

1. **The pipeline works.** Data loads, the model learns, and real handwriting can be read. Character error fell from 90.9% to 5.0% on Kannada in one short CPU run.
2. **A model trained on few writers reads new handwriting poorly.** Hindi ended training at loss 0.36 but reads unseen writers at 21.1% character error and 63.4% word error. With only 7 training writers, the model has little handwriting variety to learn from.
3. **A word error of 28% to 63% is far too high to show names unchecked.** This supports the existing design: two independent readers, withholding a name when they disagree, and human review.

## What this does not show

- **Not a reproduction** of any published result. Those use full schedules and GPUs.
- **One seed, one short schedule, one validation sample.** No confidence intervals; the differences between runs are indicative only.
- **Clean word images, not cheque crops.** Cheques have stamps, ruled lines, mixed ink and varied scans.
- **No other languages.** Tamil, Malayalam, Gujarati and Telugu are downloaded and validated, but not trained.
- **No comparison with large vision models.** That is the bake-off in `docs/research/ocr-bakeoff-plan.md` (on the `claude/research-extraction-models` branch), which needs a GPU host.

## Next steps

1. Get the authors' permission to use the data in a product, or keep it to research.
2. Train on a GPU with longer schedules, and compare against the bake-off candidates on the same words.
3. Collect handwriting from many writers. For cheque payee fields the number of writers matters more than the number of images.
4. Marathi has no open handwritten-word dataset, so it needs bank cheques or synthetic words.
5. Repeat with several seeds before quoting any figure.

## Reproduce

```
python scripts/htr_research/run_smoke.py --layout ids --root <kn_data> \
  --train-samples 100000 --val-samples 1000 --steps 3000 --batch-size 32 --lr 0.001 \
  --seed 1 --height 64 --max-width 320 --workers 6 --log-every 100 --out kn_long1.json
python scripts/htr_research/run_smoke.py --layout text --root <hi_data> ...same options... --out hi_long1.json
```

Result files are kept outside the repository, in the scratch folder `htr_runs`.
