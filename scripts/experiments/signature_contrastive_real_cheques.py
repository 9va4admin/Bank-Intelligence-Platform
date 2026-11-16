"""Run: CHEQUE_DIR=<folder of cheque images> python scripts/experiments/signature_contrastive_real_cheques.py 30

Writer-disjoint experiment: train the contrastive embedder on 59 real cheque signatures, evaluate generic vs trained on 30 UNSEEN writers.
Held-out 'genuine' samples are re-scan style variants made by code that is NOT the training augmentation. They are still variants of one image,
so this measures random-forgery separation and invariance, NOT skilled-forgery protection and NOT real genuine variation."""
import io, json, random, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from PIL import Image, ImageFilter

from modules.cts.evaluation.signature_eval import GENUINE, SigSample, build_trials, equal_error_rate, far_frr_at, threshold_for_far
from modules.cts.signature_training.embedder import TrainedSignatureEmbedder
from modules.cts.signature_training.train import train
from modules.cts.workflows.activities.signature import _sync_crop_signature
from shared.ai.local_signature_embedder import LocalSignatureEmbedder

import os
ROOT = Path(os.environ["CHEQUE_DIR"])        # folder of real whole-cheque images (customer data: never committed)
BBOX = [0.616, 0.62, 0.904, 0.83]
EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 30

paths = sorted(p for p in ROOT.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
rng = random.Random(11)
rng.shuffle(paths)
crops = []
raw_of = {}
for p in paths:
    try:
        raw_of[p.name] = p.read_bytes()
        crops.append((p.name, Image.open(io.BytesIO(_sync_crop_signature(raw_of[p.name], BBOX))).convert("L")))
    except Exception as exc:
        print("skip", p.name, exc)
n_test = 30
test, train_set = crops[:n_test], crops[n_test:]
print(f"writers: train {len(train_set)}  held-out {len(test)}")


def rescan(img, seed):
    """Independent of the training augmentation: rescale, rotate, sensor noise, blur."""
    r = random.Random(seed)
    s = r.uniform(0.92, 1.08)
    im = img.resize((max(8, int(img.width * s)), max(8, int(img.height * s)))).rotate(r.uniform(-2.5, 2.5), expand=False, fillcolor=255)
    a = np.asarray(im, dtype="float32") + np.random.default_rng(seed).normal(0, 6, (im.height, im.width))
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    return im.filter(ImageFilter.GaussianBlur(0.6)) if seed % 2 else im


def jittered(name, seed):
    """HARDER genuine variant: the detector's box moves and changes size (what the frame contains changes), then a re-scan."""
    r = random.Random(seed)
    x1, y1, x2, y2 = BBOX
    dx, dy = r.uniform(-0.05, 0.05), r.uniform(-0.05, 0.05)
    sx, sy = r.uniform(0.85, 1.2), r.uniform(0.85, 1.2)
    cx, cy, w, h = (x1 + x2) / 2 + dx, (y1 + y2) / 2 + dy, (x2 - x1) * sx, (y2 - y1) * sy
    box = [max(0, cx - w / 2), max(0, cy - h / 2), min(1, cx + w / 2), min(1, cy + h / 2)]
    crop = Image.open(io.BytesIO(_sync_crop_signature(raw_of[name], box))).convert("L")
    return rescan(crop, seed)


def samples_for(embed):
    out = []
    for w, (name, img) in enumerate(test):
        for v in range(5):
            out.append(SigSample(f"W{w:02d}", GENUINE, embed(jittered(name, w * 10 + v))))
    return out


def report(name, embed):
    trials, skipped = build_trials(samples_for(embed), k_enrol=3, seed=0)
    far85, frr85 = far_frr_at(trials, 0.85)
    th, far_t, frr_t = threshold_for_far(trials, 0.03)
    res = {"model": name, "eer": round(equal_error_rate(trials), 4),
           "far_at_0.85": far85.as_dict(), "frr_at_0.85": frr85.as_dict(),
           "threshold_for_far_3pct": round(th, 4), "frr_at_that": frr_t.as_dict()}
    print(json.dumps(res))
    return res


generic = LocalSignatureEmbedder()
gen_embed = lambda im: generic._embed_sync(_to_bytes(im))


def _to_bytes(im):
    buf = io.BytesIO(); im.save(buf, format="PNG"); return buf.getvalue()


results = [report("generic ImageNet ResNet-18", gen_embed)]
t0 = time.time()
model, history = train(train_set, epochs=EPOCHS, batch_size=16, size=224, lr=1e-4, seed=0, init="imagenet")
print(f"trained {EPOCHS} epochs in {time.time()-t0:.0f}s; loss {history[0]:.3f} -> {history[-1]:.3f}")
from modules.cts.signature_training.checkpoint import save_checkpoint
save_checkpoint(model, Path(os.environ.get("OUT_DIR", ".")) / "sig_model.pt", size=224, n_images=len(train_set), n_writers=len(train_set), final_loss=history[-1])
trained = TrainedSignatureEmbedder.from_model(model, size=224)
results.append(report(f"contrastive, {EPOCHS} epochs, {len(train_set)} writers", trained._embed_pil))
(Path(os.environ.get("OUT_DIR", ".")) / "signature_contrastive_result.json").write_text(json.dumps({"loss_history": history, "results": results}, indent=2))
