# Cheque data extraction: which open models help ASTRA (research brief, 2026-11-23)

Purpose: what is publicly known about open models for multilingual cheque field extraction (printed and handwritten), served on-premises, and for signature comparison; and what that means for ASTRA.
Method: web search plus reading primary papers. Confidence is stated per claim. Nothing here has been run on ASTRA's own cheques yet. Read it next to
[docs/indic-ocr-handwriting-evidence.md](../indic-ocr-handwriting-evidence.md) (what the project already tested) and [docs/evaluation/signature_verifier_evaluation.md](../evaluation/signature_verifier_evaluation.md).

## 1. Summary

1. **Printed multilingual text (bank name, branch, printed names, addresses): an open model that reads Kannada, Devanagari, Tamil and Telugu well exists, and it is not Qwen3-VL.** On the GlotOCR Bench (rendered printed text, read from the paper's tables), `dots.ocr` and `dots.mocr` read Kannada at 80% and 87%, Qwen3-VL-8B and PaddleOCR-VL-1.5 at 0%. Confidence: high for the numbers, medium for transfer to real scans (see section 2).
2. **Handwritten Indic text: no open model is shown to solve it.** No benchmark found ranks open models on handwritten Hindi, Kannada or Tamil. ASTRA's own tests (0 correct of 3 real cheques across five engines, plus IndicPhotoOCR) agree. The only path with published evidence is fine-tuning on real labelled handwriting.
3. **Fine-tuning a small open VLM on cheque fields works when the training data looks like the test data, and collapses when it does not.** A 2026 paper reports Qwen2.5-VL 3B and 7B fine-tuned at F1 0.983 and 0.985 on synthetic US cheques, but the 3B model fell to 0.593 on a public Indian-style cheque set it had not seen.
4. **Signature comparison: public benchmarks are saturated and do not transfer.** ASTRA's measured 65% false-accept rate for the generic embedder stands. The credible route is the one already built: train on the bank's genuine specimens and measure on the bank's own labelled data.
5. **vLLM:** official support or recipes exist for PaddleOCR-VL, GLM-OCR, HunyuanOCR and MiniCPM-OCR. Qwen3-VL is a mainstream vLLM model. Support for dots.ocr was not confirmed by the sources read and must be checked on its model card.

## 2. Printed text, by script (GlotOCR Bench, primary source)

Source: Kargaran et al., "GlotOCR Bench", arXiv 2604.12978 (CC BY 4.0), Tables 5 and 6, extracted from the paper PDF.
**What the test is:** sentences rendered from fonts (Google Fonts, HarfBuzz, FreeType), clean and degraded variants, up to 100 sentences per script (400 for Devanagari). **It is printed, synthetic text. It is not handwriting and not cheques.** Metric: Acc@5 = share of sentences read with character error rate at or below 5%.

| Script | dots.mocr | dots.ocr | Gemini 3.1 Flash-Lite | HunyuanOCR | GPT-4.1 | olmOCR-2 | Qwen3-VL-8B | PaddleOCR-VL-1.5 | Nanonets-OCR2 | GLM-OCR |
|---|---|---|---|---|---|---|---|---|---|---|
| Devanagari (Hindi, Marathi) | 86.0 | 90.2 | 93.5 | 79.8 | 65.8 | 71.5 | 70.8 | 1.0 | 54.2 | 0.2 |
| **Kannada** | **87.0** | **80.0** | 85.0 | 33.0 | 16.0 | 0.0 | **0.0** | **0.0** | 0.0 | 0.0 |
| Tamil | 86.0 | 88.0 | 99.0 | 65.0 | 73.0 | 4.0 | 7.0 | 98.0 | 0.0 | 0.0 |
| Telugu | 90.0 | 93.0 | 92.0 | 35.0 | 20.0 | 0.0 | 0.0 | 81.0 | 0.0 | 0.0 |
| Malayalam | 69.0 | 35.0 | 81.0 | 23.0 | 15.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Bengali | 58.0 | 73.0 | 63.0 | 53.0 | 27.0 | 27.0 | 33.0 | 29.0 | 26.0 | 0.0 |
| Gujarati | 90.0 | 95.0 | 98.0 | 6.0 | 48.0 | 13.0 | 13.0 | 0.0 | 0.0 | 0.0 |
| Gurmukhi | 79.0 | 89.0 | 85.0 | 71.0 | 20.0 | 0.0 | 22.0 | 0.0 | 0.0 | 0.0 |
| Odia | 11.0 | 0.0 | 82.0 | 2.0 | 4.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Reading it:
- `dots.ocr` / `dots.mocr` are the strongest open models across Indian scripts, and the gap to the best frontier API is small (the paper says so too). They are the first candidates to test.
- The paper's mean across all scripts: Gemini 3.1 Flash-Lite 61.9, dots.mocr 59.6, dots.ocr 59.3, HunyuanOCR 54.2, Qwen3-VL-8B 52.4, olmOCR-2 51.5, PaddleOCR-VL-1.5 43.5.
- **Qwen3-VL-8B, a model family the project has already tested, reads Kannada at 0% here**, with a script-identification score of 5 (it does not even recognise the script). Telugu and Malayalam are also 0%. For a Kannada bank this matters.
- PaddleOCR-VL-1.5 is strong on Tamil and Telugu and zero on Kannada, Malayalam, Gujarati, Gurmukhi and Odia. (This is the newer vision-language model, not the PaddleOCR 2.7.3 engine ASTRA's IndicOCR sidecar uses.)
- The paper's finding: models given an unfamiliar script produce noise or hallucinate characters of a script they know. That is the same wrong-script confidence ASTRA saw on real cheques.

## 3. Handwritten Indic text

- No benchmark found ranks open models on handwritten Hindi, Kannada or Tamil (search, medium confidence in the absence).
- **IIIT-Indic-HW-Words** (Gongidi and Jawahar, ICDAR 2021): word-level handwriting, about 872 thousand word images from 135 writers in 8 scripts (a later paper counts 1,081,730 images in 10 languages; check the version). The right public set to fine-tune and test a handwriting recognizer on. Hindi subset on Hugging Face (`c3rl/IIIT-INDIC-HW-WORDS-Hindi`).
- **HindiOCR-VLM** (IIIT Hyderabad CVIT, primary paper read): GOT-OCR2.0 (580M parameters, already named in ASTRA's design) adapted with LoRA for Hindi. Two designs: a single-stage page reader for print, and a two-stage (detect words, recognize words) model for print, handwriting and scene text. On a Hindi printed word validation set, fine-tuned GOT-OCR2.0 reaches 98.21 token accuracy against 57.03 for Phi-3 Vision under the same setup. **Hindi only, no Kannada.** Code and resources at hindiocr-vlm.github.io. The handwriting numbers were not extracted here; read the paper's Table 3 before relying on them.
- **Bodhan IndicOCR**: reported to read handwriting in English and 12 Indian languages including Kannada, Tamil, Telugu, Hindi. The Hugging Face page is gated behind a licence agreement. Whether it is truly open weights, and its handwriting scores, are **unverified**.
- **Sarvam Vision** (3B, 22 Indian languages): offered as an API and marketplace listing; no public weights found. Its own benchmark data (`sarvamai/indic-ocr-bench`, Apache-2.0) is public. Vendor-reported scores only.
- Pretrained generic handwriting is not enough: ASTRA's own test shows every engine confidently wrong on real handwritten payees (docs/indic-ocr-handwriting-evidence.md).

## 4. Cheque-specific extraction

- **"Beyond Accuracy" (arXiv 2609.15706, CC BY 4.0; read from the paper's HTML, partly model-summarised):** US business cheques, synthetic and template-driven (3,748 images). Fields: payee, amount, date, bank. Micro-F1 on 750 test cheques: Qwen2.5-VL-7B fine-tuned (LoRA) 0.985, 3B fine-tuned 0.983, GPT-5 0.928, OCR then GPT-4.1 0.917, Azure Content Understanding 0.889, Claude Sonnet 4.5 0.857, OCR plus regex 0.395. Per field the fine-tuned 7B scored payee 0.935, amount 0.992, date 0.960.
  - **Out-of-distribution test on a public Indian-style cheque set (400 cheques): Qwen2.5-VL-3B fine-tuned fell to 0.593; SmolVLM2-2.2B fine-tuned 0.788.** The authors blame a training artefact (the year 2024 in every training record). Lesson: fine-tuning on synthetic data does not transfer; it needs the bank's real variety.
  - Not reported: handwriting, Indic languages, scan-quality stress by tier. Code, data generation and eval harness: github.com/manulife-ai/beyond-accuracy-vlm-emnlp2026 (licence not stated in what was read). Fine-tuned weights not stated as released.
- Community model `AJNG/qwen-vl-2.5-3B-finetuned-cheque` (Hugging Face): Qwen2.5-VL-3B fine-tune returning cheque JSON. **No licence stated, no metrics, own card says it works mainly on printed cheques and may struggle with cursive handwriting or non-English.** Not usable as is.
- Two Hugging Face handwritten-cheque datasets exist (`arunchincheti/handwritten_and_cheques_dataset`, `aniketVerma07/handwritten_cheque_vqa_dataset`) with fields including amount in words and payee. **Size, language and licence not checked.** Useful only as a pilot corpus, probably not Indian.
- No dedicated open repository for amount-in-words plus payee on Indian cheques was found.
- Production OCR for India (Krutrim, arXiv 2602.16430): a fine-tuned OCR-specialised model beat training end to end for multilingual and domain adaptation; a government-document extractor reached 89.8% exact match. Printed documents; no handwriting evaluation reported.
- A 2026 Devanagari benchmark (arXiv 2606.29213, printed scans; abstract-level reading only): open Qwen3-VL-8B scored chrF++ 75.2 on real printed Devanagari scans (GPT-5.5 58.5, olmOCR-7B 40.5, Gemini 86.3, Claude 82.2); real scans separate models far more than clean renders; DeepSeek-OCR can loop and emit output up to 71 times the reference length (so it needs a length guard).

## 5. Signature comparison

- Public offline benchmarks (CEDAR, BHSig260 which is Bengali and Hindi, GPDS, ICDAR) are standard, but a 2026 IJACSA benchmark reports CEDAR near saturation under strict writer-independent protocols, and a 2025 study reports models trained on one dataset generalise poorly to another.
- Open code exists (SigNet, MS-SigNet at github.com/ashleyfhh/MS-SigNet, small Siamese repos). No open **pretrained** model with published cross-dataset numbers worth adopting was found.
- Using a general foundation encoder (DINOv2, CLIP, SigLIP) as a few-shot signature verifier: no direct evidence found for signatures; the nearest evidence (face recognition) says a foundation encoder helps most when fine-tuned on in-domain identities.
- ASTRA's measured baseline: the generic ImageNet embedder accepts 64.8% of other people's signatures at threshold 0.85. Its training and evaluation tooling is already built (`scripts/train_signature_embedder.py`, `scripts/eval_signature_verifier.py`).

## 6. Serving with vLLM (support, not speed)

| Model | vLLM support found | Note |
|---|---|---|
| PaddleOCR-VL (0.9B) | official, with a serving recipe (Nov 2025) | Tamil and Telugu strong; no Kannada |
| GLM-OCR (0.9B) | recipe | weak on Indic in the benchmark above |
| HunyuanOCR | recipe | middling Indic |
| MiniCPM-OCR 1.0 | recipe | no Indic evidence found |
| Qwen3-VL | mainstream vLLM model | weak on Kannada, Telugu, Malayalam |
| DeepSeek-OCR (v1) | supported per community notes | repetition failures reported |
| dots.ocr / dots.mocr | **not confirmed by the sources read** | strongest Indic result; check its model card and licence |
| olmOCR-2, Chandra | not confirmed | weak on Indic in the benchmark |

## 7. What this means for ASTRA (recommendations, in order)

1. **Run a bake-off on ASTRA's own real cheques before choosing anything.** Candidates: dots.ocr, dots.mocr, Qwen3-VL-8B (as the control), HunyuanOCR, PaddleOCR-VL-1.5, GOT-OCR2.0. Use the 70 real KBL instruments and the existing evaluation scripts (`scripts/eval_inward.py`), scored with intervals. Report printed fields and handwritten fields separately; the table above says nothing about handwriting.
2. **Printed multilingual fields: try dots.ocr first**, served on vLLM if it supports it (otherwise its own server), as the primary and Qwen3-VL as the independent reread. The design already withholds a result when two models disagree; a pair that can both read the script makes that gate useful instead of always disagreeing.
3. **Handwritten fields: plan on fine-tuning, not on model choice.** Start from the model that wins step 1; LoRA fine-tune on (a) IIIT-Indic-HW-Words for the script, then (b) the bank's own labelled cheque crops. Section 4's out-of-distribution drop is the warning: real data first, synthetic only to fill gaps. Keep human review as the safety net for everything the model is unsure about, exactly as the current rules say.
4. **Signature: do not adopt a public model.** Train on the bank's genuine specimens with the existing script and measure with the existing evaluator on the bank's own data. Use BHSig260 (Hindi and Bengali) only to pre-train a base.
5. **Licences before any adoption:** verify dots.ocr, HunyuanOCR, GOT-OCR2.0 and any dataset on the actual model card and licence file. Several sources read here did not state one.
6. **Cloud is not an option for production** (CLAUDE.md data-localisation rule): Gemini scored best on the benchmark but cannot be used with bank data. It is useful only as a yardstick.

## 8. Confidence and gaps

- Verified from the primary PDF: GlotOCR numbers and what the benchmark is; HindiOCR-VLM design and the Table 7 comparison.
- Read from the paper's HTML, partly model-summarised: the "Beyond Accuracy" tables.
- Search-summary only (not verified): Devanagari stress-test numbers, Bodhan and Sarvam details, vLLM support list, signature benchmark remarks, Hugging Face dataset descriptions.
- Not found at all: handwritten Indic benchmark ranking open models; Kannada results for handwriting anywhere; throughput numbers on ASTRA's hardware.

## Sources

- [GlotOCR Bench, arXiv 2604.12978](https://arxiv.org/pdf/2604.12978)
- [Adapting Vision-Language Models for Hindi OCR (IIIT CVIT)](https://cdn.iiit.ac.in/cdn/cvit.iiit.ac.in/images/ConferencePapers/2025/adapting-Vision-Language-ocr.pdf)
- [Beyond Accuracy: VLMs in Templated Document Extraction, arXiv 2609.15706](https://arxiv.org/abs/2609.15706)
- [Can OCR-VLMs Read Devanagari? arXiv 2606.29213](https://arxiv.org/pdf/2606.29213)
- [Designing Production-Scale OCR for India, arXiv 2602.16430](https://arxiv.org/abs/2602.16430)
- [PaddleOCR-VL on Hugging Face](https://huggingface.co/paddlepaddle/PaddleOCR-VL), [vLLM recipe](https://recipes.vllm.ai/PaddlePaddle/PaddleOCR-VL)
- [Bodhan IndicOCR (gated)](https://huggingface.co/bodhan-ai/indic-ocr), [Sarvam Vision](https://www.sarvam.ai/blogs/sarvam-vision), [Sarvam indic-ocr-bench](https://huggingface.co/datasets/sarvamai/indic-ocr-bench)
- [IIIT-Indic-HW-Words](https://cvit.iiit.ac.in/research/projects/cvit-projects/iiit-indic-hw-words), [PLATTER](https://arxiv.org/pdf/2502.06172), [Indic TrOCR](https://github.com/iitb-research-code/indic-trocr)
- [AJNG cheque model card](https://huggingface.co/AJNG/qwen-vl-2.5-3B-finetuned-cheque), [handwritten cheque dataset](https://huggingface.co/datasets/arunchincheti/handwritten_and_cheques_dataset)
- [MS-SigNet](https://github.com/ashleyfhh/MS-SigNet), [unified signature benchmark (IJACSA)](https://thesai.org/Downloads/Volume17No2/Paper_27-A_Unified_Benchmarking_Framework.pdf), [cross-dataset signature study, arXiv 2510.17724](https://arxiv.org/abs/2510.17724v1)
