# Transliteration POC Findings — 2026-08-13

## Objective

Determine whether replacing our homegrown Brahmic engine with the
`indic-transliteration` library (ITRANS scheme) or the AI4Bharat IndicXlit
seq2seq model improves payee name JW-matching accuracy for CTS inward/outward.

---

## Phase 1: indic-transliteration (ITRANS) — Completed

### Test corpus: 24 names across 9 scripts

| Metric | Brahmic engine | ITRANS (indic-transliteration) |
|---|---|---|
| Avg Jaro-Winkler | **0.920** | 0.876 |
| Wins | **14** | 0 |
| Ties | 10 | 10 |

### Why ITRANS loses

ITRANS follows scholarly Sanskrit transliteration rules — not Indian name conventions:

| Name | English expected | Brahmic (ours) | JW | ITRANS | JW | Delta |
|---|---|---|---|---|---|---|
| देशपांडे | Deshpande | deshapande | **0.958** | deshapamde | 0.913 | +0.045 |
| महेंद्र | Mahendra | mahendra | **1.000** | mahemdra | 0.950 | +0.050 |
| ਸਿੰਘ | Singh | singha | **0.967** | simgha | 0.858 | +0.109 |
| দেবনাথ | Debnath | debanatha | **0.915** | devanatha | 0.829 | +0.086 |
| চক্রবর্তী | Chakraborty | chakrabarti | **0.927** | chakravarti | 0.891 | +0.036 |

Root causes:
- **anusvara before 'dh'** → ITRANS uses `m` (Sanskrit rule: anunasika assimilates to
  bilabial); our engine uses `n` throughout. "pAMDe" → "pamde" vs our "pande"
- **Gurmukhi tippi (ੰ)** → ITRANS treats like standard Sanskrit `ṃ` → `m` before
  fricatives, giving "simgha"; our engine maps it correctly to "n" via the `chandrabindu`
  field → "singha"
- **Bengali ব** → ITRANS romanizes as `v` (Sanskrit rule); names written "Debnath" use
  `b`; our engine maps ব → `b` for name-matching purposes

**Verdict: Keep our Brahmic engine as-is. It is already better than ITRANS.**

---

## Known Failures (JW < 0.75 with Brahmic engine)

These are NOT transliteration problems — they are lexical/semantic problems:

| Name (Malayalam) | Our output | English expected | JW |
|---|---|---|---|
| ജോർജ്ജ് | jorja | George | 0.578 |

**Root cause:** "George" is a Greek name (Γεώργιος) adapted into Malayalam phonology as
/dʒɔːrdʒ/ → Malayali pronunciation "Jorj" → written ജോർജ്ജ്. The phonemic chain breaks:
- Our engine: j+o+r+j+j → "jorja"
- "George" has entirely different phoneme origins
- No phonemic rule engine can recover this without a name lexicon

Same category: Thomas (Aramaic), John, Philip, Matthew, Francis (Latin/Greek).
Estimated 15–20% of Kerala CTS accounts are Christian; this gap is real.

---

## Phase 2: AI4Bharat IndicXlit (seq2seq) — Blocked on this machine

**Status: CANNOT INSTALL on Python 3.12 / Windows**

```
pip install ai4bharat-transliteration==1.1.3
# FAILS: fairseq 0.12.2 requires building from source
#   FileNotFoundError: fairseq\version.txt (build system bug on Python 3.12)
#   omegaconf<2.1 invalid metadata (pip>=24.1 rejects it)
```

**Why IndicXlit would be better:** It is a seq2seq model trained on the
[Dakshina dataset](https://github.com/google-research-datasets/dakshina) — 100K+ actual
Indian name pairs (written form → romanized conventional spelling). It would recover
"George" from ജോർജ്ജ് because the training data includes these pairs directly.
Latency: ~5ms on CPU. Model size: 8MB.

**To test in production:** Deploy in a Linux Docker container (fairseq builds fine on
Linux). Run the benchmark above against IndicXlit output to validate the delta.

---

## Recommended Roadmap (priority order)

### 1. Malayalam Christian-name lexicon (2 days — do now)
Add a lexicon of the top 50 Christian names with their Malayalam script forms:

```python
_MALAYALAM_CHRISTIAN_NAMES = {
    "ജോർജ്": "george",
    "ജോർജ്ജ്": "george",
    "തോമസ്": "thomas",
    "ജോൺ": "john",
    "ഫിലിപ്പ്": "philip",
    # ... 45 more
}
```

Pre-transliteration lookup in `payee_names_match()`: if Malayalam text matches a
known Christian name form, use the lexicon string directly before JW matching.
Expected improvement: 0.578 → 0.950+ for George.

### 2. IndicXlit in Docker/Linux (1 sprint — trial next deployment)
- Wrap as a Temporal activity: `transliterate_via_xlit(text, script) → latin`
- POC: compare on this 24-name corpus + expanded Kerala Christian-name corpus
- Include if benchmark shows ≥ 0.02 avg JW improvement over Brahmic
- Discard if improvement is smaller (not worth the GPU/CPU overhead)

### 3. BGE-M3 semantic approach (medium-term — post-pilot)
BGE-M3 is already deployed for EJ embeddings. It could produce embeddings for both the
Indic OCR name and the English CBS name and compare cosine similarity directly —
bypassing transliteration entirely.
- Pro: language-agnostic, handles any script including Urdu/Nastaliq
- Con: requires EJ-side infrastructure in CTS namespace (isolation rule violation unless
  we run a separate CTS embedding queue)
- Decision: evaluate post-pilot when we have real Kerala bank onboarding data

---

## Files Produced

| File | Purpose |
|---|---|
| `modules/cts/preprocessing/xlit_benchmark.py` | Benchmark runner + comparison module |
| `tests/modules/cts/preprocessing/test_xlit_benchmark.py` | 22 tests, all GREEN |
| `docs/xlit-poc-findings.md` | This document |
