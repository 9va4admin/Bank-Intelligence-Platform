# OCR / VLM bake-off harness (built 2026-11-23)

Tool for comparing open-weight models that read cheque fields, on the bank's own network and on the bank's own cheques. It implements step 2 of the bake-off plan (`docs/research/ocr-bakeoff-plan.md` on branch `claude/research-extraction-models`). **No model has been run yet.**

Code: `modules/cts/evaluation/ocr_bakeoff.py` (scoring), `modules/cts/evaluation/bakeoff_runner.py` (calling a model, manifest, settings), `scripts/bakeoff_ocr.py` (command line). 88 tests; they need no model and no network.

## Use

```
python scripts/bakeoff_ocr.py run   --manifest m.json --images crops/ --model-name dots.ocr --endpoint http://gpu01.internal:8000/v1 \
                                    --api-model <served model name> --variant 1 --out readings_dots_v1.json
python scripts/bakeoff_ocr.py score --manifest m.json --readings readings_*.json --families families.json --baseline current \
                                    --out-md report.md --out-json report.json
```

- **Manifest** (JSON list): `item_id, field, crop, text` (the truth), `script, handwritten, quality`, optional `scoreable` (false when the truth is uncertain: such items are left out). Fields: `payee, amount_words, amount_figures, date, micr_band`. **Keep the manifest, the crops and every readings file in a git-ignored folder: they are real customer data.**
- **Readings** of the model currently in production go in as a model too (any name, e.g. `current`), so it is the baseline. `families.json` maps every model name to its model family; two models of one family are never proposed as a pair.

## What `run` guarantees

- **The model endpoint must be on the bank's own network**: localhost, a private or link-local address, a name under `.internal`, `.local` or `.lan`, or a host named with `--allow-host`. Anything else is refused before a single image is sent, and a name is never looked up in DNS (so `localhost.evil.com` is not allowed).
- The same question for every model: three fixed wordings per field (`--variant 1|2|3`), temperature 0, a fixed output length. The readings file records a fingerprint of the exact prompt used.
- A failed call, a timeout, a missing crop or an unreadable answer is recorded and the run goes on. Nothing is silently dropped: an item without a reading counts as *withheld*.

## What `score` reports

Per model, field and stratum (all items; script; handwritten or printed; scan quality):

| Column | Meaning |
|---|---|
| Exact | the value matches the truth after normalising case, spacing, punctuation, Unicode form and digits of any script (amounts are compared as numbers) |
| **Wrong shown** | a value was produced and it is wrong: the dangerous error |
| Withheld | nothing usable: empty, failed, or a runaway output |
| Runaway output | an answer longer than the guard allows (catches repetition loops); counted as withheld |
| Wrong script | an answer in a different script from the truth (the "confident text in the wrong script" failure) |
| Mean CER | character error rate, capped at 1 |
| Latency p50 / p95 | per model, successful calls only |
| verdict | 95% Wilson interval against the wrong-shown target: MEETS, NOT DEMONSTRABLE (the point estimate is fine but too few samples), or BELOW |

Then: a **paired comparison with the baseline** (exact McNemar test on the items where exactly one model is right, and a paired bootstrap interval on the difference in the wrong-shown rate), and **every primary plus second-reader pair from different families**: a primary read is shown only when the second reader agrees; the table gives how many are shown correct, shown wrong while both agree (the dangerous case), and sent to a human.

## Settings

Shipped defaults in `shared/config/config_service.py`, any overridable by a flag: `cts.bakeoff_length_guard_multiple`, `cts.bakeoff_length_guard_min_chars`, `cts.bakeoff_bootstrap_resamples`, `cts.bakeoff_seed`, `cts.bakeoff_wrong_shown_target`, `cts.bakeoff_request_timeout_seconds`, `cts.bakeoff_max_output_tokens`, `cts.bakeoff_alpha`, and `cts.payee_reread_min_similarity` for when two reads agree. No threshold is written in the code.

## Limits to remember

- Ground truth is a person's reading of the image and can itself be wrong; use a second labeller for the handwritten fields.
- With about 70 cheques the report can rank models and show large differences. It cannot prove a target: showing an error rate below 1% needs 299 error-free samples.
- Agreement between two readers uses a comparison of letters in **every** script. The production payee re-read rule (`_payee_names_agree` in `modules/cts/workflows/activities/ocr.py`) keeps only A-Z and digits and so judges two identical Kannada or Hindi reads as different; that is a separate fix.
