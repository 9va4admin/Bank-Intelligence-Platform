# Handwritten Indic-Script OCR — Real Evidence Log

> **Purpose:** same rule as `docs/e2e-test-evidence.md` — a dated, append-only record of what was
> actually tested against real images and real (local + cloud) OCR/VLM engines, so "does model X
> solve handwritten Indic OCR" can be answered from evidence, not from a benchmark's marketing page.
> **Honesty rule:** this log records what worked and what did not. No claim below is asserted
> without a result attached to it, and every crop is committed under
> `docs/evidence/2026-09-22/hindi_ocr_dpi_test/` so a claim can be checked against the actual image,
> not this prose.

See also `CLAUDE.md` §2.7 (IndicOCR sidecar status) — this doc is the detailed backing evidence for
the "handwritten accuracy is open" line there.

---

## Entry 2026-09-22 — Two questions: (1) does resolution explain the failure, (2) do newer models fix it

### Question 1 — Is 96 DPI (vs. the CTS-2010-mandated 200 DPI) the real bottleneck?

Two controlled images were built from the same real cheque (`docs/cheques/KBL/OW CHQ/353138.jpg`,
payee = **राजू पंडीत / "Raju Pandit"**, ground truth confirmed by eye and previously corrected by
the user against an earlier wrong OCR read):

| Image | What it isolates | Local IndicOCR (PaddleOCR, devanagari) | Cloud VLM (Qwen2.5-VL-72B) |
|---|---|---|---|
| `ow_353138_UPSCALED_200dpi_equiv.png` — the real handwriting, **interpolated** (Lanczos) to the pixel count 200 DPI would give | "does just adding pixels fix it" | `शाू` — wrong, conf 0.72 | `राजू पटेल` — wrong (same "Patel" error as before), conf 0.9 |
| `SYNTHETIC_200dpi_printed_raju_pandit.png` — the ground-truth text **rendered as clean print**, in a real Devanagari font (Windows `Nirmala.ttc`), at genuine 200 DPI pixel density | "can the engine read Devanagari at all once the ink is clean" | `पंडीत राजू` — **both words correct**, conf 0.9982 | `राजू पंडीत` — **exact match**, conf 1.0 |

**Conclusion:** interpolating an existing low-DPI photo to look like 200 DPI does **nothing** — no
real detail is added, both engines still fail. But both engines read Devanagari **correctly and at
near-1.0 confidence** the moment the input is clean. So the bottleneck is not "Devanagari isn't
supported" or "resolution in the abstract" — it is specifically **handwriting stroke ambiguity at
this dataset's actual capture quality**. A genuine 200 DPI *scanner* capture (not a photo, and not
an upscale) would very plausibly help, because it captures real additional stroke detail that
interpolation cannot invent — but that remains untested, because no real 200 DPI handwritten cheque
exists in this dataset. **This is the concrete next test, when a real scanner capture is available.**

### Question 2 — Do the newest available vision-language models (Qwen3-VL, Gemma 4 31B) solve it?

Three real Devanagari-script handwritten cheques were located and their payee crops read by eye
*before* being run through any engine (crops committed in `docs/evidence/2026-09-22/hindi_ocr_dpi_test/`):

| Cheque | Ground truth (by eye) | Local IndicOCR | Qwen2.5-VL-72B | Qwen3-VL-8B | Qwen3-VL-32B |
|---|---|---|---|---|---|
| `IW CHQ/533684.jpg` | देवेन्द्र कुमार शुक्ला (Devendra Kumar Shukla) | `मा् शुषना` ✗ (0.77) | `श्री देव` ✗ (0.8) | `श्री राम लाल` ✗ (0.85) | `null` (0.0 — honest) |
| `IW CHQ/567048.jpg` | जय लक्ष्मी... (uncertain past 2 words — genuinely hard to read even by eye) | `ज अ` ✗ (0.80) | `null` (0.0 — honest) | `निर्मल अवसर लिमिटेड` ✗ (0.95) | `राजेश कुमार शर्मा` ✗ (0.90) |
| `OW CHQ/353138.jpg` | **राजू पंडीत (Raju Pandit) — known, user-confirmed** | `शजर` ✗ (0.75) | `राजू पटेल` ✗ (0.9) | `हाजी असीम` ✗ (0.95) | `राजू वास्तव` ✗ (0.9) |

**0 correct reads across 3 real cheques × 5 engines.** Every engine is self-confident (0.75–0.95)
while wrong, with exactly two honest low-confidence/null outputs in the whole table
(Qwen2.5-VL-72B on 567048, Qwen3-VL-32B on 533684) — those are the only two *safe* outcomes here,
because a null/low-confidence result correctly routes to human review; every other cell is a
confident wrong answer that would need the same confidence-cap safety net documented in CLAUDE.md
§2.7 (`_CLOUD_VLM_INDIC_CONFIDENCE_CAP`).

**Models checked, for the record:**
- **Qwen3.8-27B** (Alibaba, released 2026-08-14, real, vision-capable, Apache 2.0) — could not be
  tested: no inference provider currently serves it via the HF router this environment uses
  (`model_not_supported` on every route tried).
- **Qwen3-VL-8B / 32B** — real, servable via `featherless-ai` (contrary to this repo's earlier
  comment that featherless-ai was Cloudflare-blocked — that block does not apply to this account/
  model combination). Tested above; no better than the older Qwen2.5-VL-72B on this data.
- **Gemma 4 31B** (Google, released 2026-04-02, real, 84.7% on a general OCR benchmark per
  [BenchLM](https://benchlm.ai/models/gemma-4-31b)) — could not be tested: `google/gemma-4-31B` on
  Hugging Face has **zero inference providers serving it** ("Ask for provider support," 35 requests
  already open). Not reporting a number that was never actually generated.

**Bottom line:** handwritten Indic-script OCR remains unsolved on this real data, across every
model available to test today, old and new. No newer model swap closes this by itself. The one
credible, still-open, testable lever is a genuine 200 DPI scanner capture (Question 1 above) —
everything else here has now actually been tried.

### Raw evidence
All 5 crop images referenced above are committed at `docs/evidence/2026-09-22/hindi_ocr_dpi_test/`.

---

## Entry 2026-09-23 — IndicPhotoOCR (Bhashini/IIT Jodhpur), tested both hosted and self-hosted

A real, MIT-licensed, self-hostable scene-text OCR toolkit
([Bhashini-IITJ/IndicPhotoOCR](https://github.com/Bhashini-IITJ/IndicPhotoOCR), TextBPN++ detection → ViT
script ID → PARseq recognition) was suggested as a candidate. Strategically distinct from every VLM tested so
far: it doesn't require the `cts.allow_cloud_ai_fallback` exception to CLAUDE.md §2.1 ("zero cloud
dependencies") — it can run entirely on-prem. Tested twice, independently:

**1. Hosted HF Space** (`Bhashini-IITJ/IndicPhotoOCR`, via its Gradio API) — on `353138.jpg` (ground truth
payee: **राजू पंडीत / Raju Pandit**): a tight field crop returned empty output across all 11 language
settings (this is a *scene-text* detector, built for full-photo context, not a pre-isolated single line — a
real usage-pattern finding, not a model failure). On the **full cheque image**, it read almost the entire
printed layout correctly (bank name, address, IFSC, account number) and read the handwritten payee as
`राजू डी` — first name exactly right, surname wrong.

**2. Self-hosted, local install** (cloned + `pip install -e .` into an isolated venv, weights downloaded for
real — not the hosted demo) — same full cheque image, same `identifier_lang="hindi"`: printed text again read
correctly (`इंडियन बैंक`, `karnataka bank ltd`, `50401372948`, …), but the handwritten payee field this time
came back as `হালু`, `પડી` — Bengali and Gujarati script fragments, not even Devanagari. The amount-words
field came back as `वेल`, `੬੫੮` (Gurmukhi digits), `धारक` — also wrong, also mixed-script.

**Same crop, same declared language, two runs of the same underlying model family — two different, both
wrong, both differently-scripted answers.** This is the same "wrong-script confidence" failure mode found in
Qwen3-VL on 2026-09-22, now confirmed in a second, independent, self-hostable model family. It reinforces
rather than changes the standing verdict: printed-text recognition is genuinely strong and reliable in this
toolkit; handwritten payee/amount-words recognition is not solved by it, and is not even consistent run to
run on identical input.

**Install note (self-hosted path):** the repo's `pip install -e .` bulk dependency resolve was flaky in this
environment — twice, pip reported `Successfully installed` for the full ~60-package set (including `torch`,
`transformers`, `timm`, …) but `pip show torch` immediately after showed nothing installed. Root cause not
fully isolated (suspected stale/corrupted wheel cache from earlier interrupted install attempts); worked
around by installing the large dependency set as an explicit, `--no-cache-dir` batch separately from the
editable package registration (`pip install -e . --no-deps`). Not an IndicPhotoOCR defect — noted here only
because it cost real time and could recur for anyone else trying a local install of this or a similarly
heavy PyTorch-based toolkit in this environment.
