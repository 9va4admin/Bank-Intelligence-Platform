"""CEDAR, writer-disjoint: a recipe aimed at skilled forgeries, against the generic embedder and the earlier augmentation-heavy recipe.

    CEDAR_DIR=<folder holding signatures/full_org and signatures/full_forg> python scripts/experiments/signature_cedar_pairs.py [steps]

Differences from signature_cedar_benchmark.py (which lost to the generic embedder on skilled forgeries):
  - full 224 px resolution (that run used 128);
  - NO augmentation: the real specimens of a writer (24 captures) are the positives, so nothing teaches invariance to the small differences
    that give a forgery away;
  - the same writer's forgeries are in every batch as hard negatives (variant 2); variant 1 uses genuine specimens only, to separate the
    effect of the forged negatives from the effect of the recipe;
  - to make this fast on a CPU the early layers stay frozen (their features are cached) and only the last ResNet block and the head train.
Held-out writers are never trained on. Temporary public-benchmark evaluation; the data is never committed.
"""
from __future__ import annotations

import copy
import io
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import torch
import torch.nn as nn
import torchvision
from PIL import Image

from modules.cts.evaluation.signature_eval import GENUINE, SKILLED, SigSample, evaluate
from modules.cts.signature_training.loss import supcon_loss
from modules.cts.signature_training.model import preprocess
from shared.ai.local_signature_embedder import LocalSignatureEmbedder

ROOT = Path(os.environ["CEDAR_DIR"]) / "signatures"
STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 600
SIZE = 224
N_HELD, K_ENROL = 15, 5
WRITERS_PER_BATCH, GEN_PER, FORG_PER = 8, 4, 4
OUT = Path(os.environ.get("OUT_DIR", "."))
torch.manual_seed(0)

orig, forg = defaultdict(list), defaultdict(list)
for p in sorted((ROOT / "full_org").glob("original_*.png")):
    orig[p.name.split("_")[1]].append(p)
for p in sorted((ROOT / "full_forg").glob("forgeries_*.png")):
    forg[p.name.split("_")[1]].append(p)
writers = sorted(orig)
SPLIT_SEED = int(os.environ.get("SPLIT_SEED", "3"))              # 3 = the same split as signature_cedar_benchmark.py
random.Random(SPLIT_SEED).shuffle(writers)
held, train_w = writers[:N_HELD], writers[N_HELD:]
print(f"writers: {len(train_w)} to train on, {len(held)} held out")

base = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.DEFAULT).eval()
frozen = nn.Sequential(base.conv1, base.bn1, base.relu, base.maxpool, base.layer1, base.layer2, base.layer3).eval()
for p_ in frozen.parameters():
    p_.requires_grad_(False)


def features(paths):
    out = []
    with torch.no_grad():
        for i in range(0, len(paths), 32):
            x = torch.stack([preprocess(Image.open(p).convert("L"), SIZE) for p in paths[i:i + 32]])
            out.append(frozen(x))
    return torch.cat(out)


t0 = time.time()
all_paths = [p for w in writers for p in orig[w] + forg[w]]
feat = dict(zip(all_paths, features(all_paths).split(1)))
print(f"cached layer3 features for {len(all_paths)} images in {time.time()-t0:.0f}s")


class Tail(nn.Module):
    """Trainable last block + pooled 512-d embedding (same shape the vault stores) + a training-only head."""

    def __init__(self):
        super().__init__()
        self.layer4 = copy.deepcopy(base.layer4)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Sequential(nn.Linear(512, 512), nn.ReLU(), nn.Linear(512, 128))

    def embed(self, f):
        return nn.functional.normalize(self.pool(self.layer4(f)).flatten(1), dim=1)

    def forward(self, f):
        return nn.functional.normalize(self.head(self.pool(self.layer4(f)).flatten(1)), dim=1)


def train_tail(use_forgeries: bool, steps: int, seed=0):
    rng = random.Random(seed)
    torch.manual_seed(seed)
    tail = Tail()
    opt = torch.optim.AdamW(tail.parameters(), lr=1e-4, weight_decay=1e-4)
    label_of = {w: i for i, w in enumerate(train_w)}
    next_unique = len(train_w)
    losses = []
    for step in range(steps):
        tail.train()
        fs, labels = [], []
        for w in rng.sample(train_w, WRITERS_PER_BATCH):
            for p in rng.sample(orig[w], GEN_PER):
                fs.append(feat[p]); labels.append(label_of[w])
            if use_forgeries:
                for p in rng.sample(forg[w], FORG_PER):
                    fs.append(feat[p]); labels.append(next_unique); next_unique += 1   # a forgery is its own class: a pure negative
        z = tail(torch.cat(fs))
        loss = supcon_loss(z, torch.tensor(labels), 0.1)
        opt.zero_grad(); loss.backward(); opt.step()
        losses.append(loss.item())
        if (step + 1) % 100 == 0:
            print(f"   step {step+1}: loss {sum(losses[-100:])/100:.3f}", flush=True)
    return tail.eval()


def held_samples(embed_path):
    out = []
    for w in held:
        out += [SigSample(f"C{w}", GENUINE, embed_path(p)) for p in orig[w]]
        out += [SigSample(f"C{w}", SKILLED, embed_path(p)) for p in forg[w]]
    return out


def report(name, embed_path):
    r = evaluate(held_samples(embed_path), k_enrol=K_ENROL, threshold=0.85, max_far=0.03, seed=0)
    for kind, e in r["by_kind"].items():
        far, frr, t = e["far"], e["frr"], e["threshold_for_target_far"]
        print(f"{name:44s} {kind:15s} FAR@0.85 {far['rate']:.1%}  FRR@0.85 {frr['rate']:.1%}  EER {e['equal_error_rate']:.1%}  "
              f"| FAR<=3%: thr {t['threshold']:.3f} FRR {t['frr']['rate']:.1%}", flush=True)
    return r


results = {}
generic = LocalSignatureEmbedder()
results["generic"] = report("generic ImageNet ResNet-18", lambda p: generic._embed_sync(Path(p).read_bytes()))


def tail_embed(tail):
    def f(p):
        with torch.no_grad():
            return tail.embed(feat[p])[0].tolist()
    return f


for name, use_f in (("224px layer4, genuine specimens only", False), ("224px layer4, + same-writer forgeries as negatives", True)):
    t0 = time.time()
    print(f"-- training: {name}, {STEPS} steps")
    tail = train_tail(use_f, STEPS)
    print(f"   {time.time()-t0:.0f}s")
    results[name] = report(name, tail_embed(tail))

(OUT / f"cedar_pairs_result_split{SPLIT_SEED}.json").write_text(json.dumps(results, indent=2))
