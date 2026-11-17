"""Public-benchmark check of skilled-forgery behaviour on CEDAR (55 writers, 24 genuine + 24 forgeries each), writer-disjoint.

    CEDAR_DIR=<folder holding signatures/full_org and signatures/full_forg> python scripts/experiments/signature_cedar_benchmark.py [epochs] [size]

Scores, on the SAME held-out writers: the generic ImageNet embedder; the contrastive embedder trained on the training writers' GENUINE signatures
only; and the same trainer with the training writers' forgeries added as extra negatives. Held-out writers are never trained on.
This is a public benchmark (clean pen-on-paper signature crops, forgeries made by volunteers who practised), NOT evidence about cheques: use it
to compare methods, not to claim a rate for the bank. Temporary evaluation only: the data is never committed or shipped.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image

from modules.cts.evaluation.signature_eval import GENUINE, SKILLED, SigSample, evaluate
from modules.cts.signature_training.embedder import TrainedSignatureEmbedder
from modules.cts.signature_training.train import train
from shared.ai.local_signature_embedder import LocalSignatureEmbedder

ROOT = Path(os.environ["CEDAR_DIR"]) / "signatures"
EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
SIZE = int(sys.argv[2]) if len(sys.argv) > 2 else 128
N_HELD = 15
K_ENROL = 5
OUT = Path(os.environ.get("OUT_DIR", "."))

orig, forg = defaultdict(list), defaultdict(list)
for p in sorted((ROOT / "full_org").glob("original_*.png")):
    orig[p.name.split("_")[1]].append(p)
for p in sorted((ROOT / "full_forg").glob("forgeries_*.png")):
    forg[p.name.split("_")[1]].append(p)
writers = sorted(orig)
random.Random(3).shuffle(writers)
held, train_w = writers[:N_HELD], writers[N_HELD:]
print(f"writers: {len(train_w)} to train on, {len(held)} held out")


def load(p):
    return Image.open(p).convert("L")


def held_out_samples(embed):
    out = []
    for w in held:
        out += [SigSample(f"C{w}", GENUINE, embed(load(p))) for p in orig[w]]
        out += [SigSample(f"C{w}", SKILLED, embed(load(p))) for p in forg[w]]
    return out


def report(name, embed):
    r = evaluate(held_out_samples(embed), k_enrol=K_ENROL, threshold=0.85, max_far=0.03, seed=0)
    for kind, e in r["by_kind"].items():
        far, frr = e["far"], e["frr"]
        t = e["threshold_for_target_far"]
        print(f"{name:34s} {kind:15s} FAR@0.85 {far['k']}/{far['n']} = {far['rate']:.1%}  FRR@0.85 {frr['rate']:.1%}  EER {e['equal_error_rate']:.1%}  "
              f"| for FAR<=3%: thr {t['threshold']:.3f} FRR {t['frr']['rate']:.1%}")
    return r


generic = LocalSignatureEmbedder()
import io


def gen_embed(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return generic._embed_sync(buf.getvalue())


results = {"generic": report("generic ImageNet ResNet-18", gen_embed)}

genuine_only = [(f"C{w}", load(p)) for w in train_w for p in orig[w]]
t0 = time.time()
model_a, hist_a = train(genuine_only, epochs=EPOCHS, batch_size=32, size=SIZE, seed=0, init="imagenet")
print(f"genuine-only: {len(genuine_only)} images, {EPOCHS} epochs, {time.time()-t0:.0f}s, loss {hist_a[0]:.2f} -> {hist_a[-1]:.2f}")
emb_a = TrainedSignatureEmbedder.from_model(model_a, size=SIZE)
results["genuine_only"] = report("trained: genuine only", emb_a._embed_pil)

with_forged = genuine_only + [(f"C{w}#F{i}", load(p)) for w in train_w for i, p in enumerate(forg[w])]   # each forgery its own class: a pure negative
t0 = time.time()
model_b, hist_b = train(with_forged, epochs=EPOCHS, batch_size=32, size=SIZE, seed=0, init="imagenet")
print(f"genuine + forged negatives: {len(with_forged)} images, {EPOCHS} epochs, {time.time()-t0:.0f}s, loss {hist_b[0]:.2f} -> {hist_b[-1]:.2f}")
emb_b = TrainedSignatureEmbedder.from_model(model_b, size=SIZE)
results["genuine_plus_forged_negatives"] = report("trained: genuine + forged negatives", emb_b._embed_pil)

(OUT / "cedar_benchmark_result.json").write_text(json.dumps(results, indent=2))
