"""The proper training run for word-image handwriting recognition.

Every epoch uses every training image (the last partial batch included). After each epoch the whole validation split is scored. The best checkpoint by validation
character error is kept, the learning rate drops when validation stalls, and training stops when it has not improved for `patience` epochs (or the epoch or time
budget is spent). The run can be resumed after an interruption. The test split is touched once, at the end, with the best checkpoint (`final_test`).
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import DataLoader

from htr_research.augment import augment_image
from htr_research.crnn import CRNN
from htr_research.dataset import Charset, Sample
from htr_research.preprocess import collate
from htr_research.train import WordImages, evaluate


@dataclass
class FitConfig:
    max_epochs: int
    patience: int
    lr: float
    batch_size: int
    seed: int
    height: int
    max_width: int
    workers: int
    device: str
    augment: bool
    min_delta: float = 0.0            # an epoch must beat the best validation character error by this much to count as an improvement
    lr_patience: int = 1              # epochs without improvement before the learning rate is cut
    lr_factor: float = 0.5
    weight_decay: float = 0.0
    max_hours: Optional[float] = None
    augment_strength: float = 1.0
    eval_batch_size: int = 64


def _save(obj, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def _augmenter(cfg: FitConfig, epoch: int):
    if not cfg.augment:
        return None
    return lambda img, i: augment_image(img, random.Random(cfg.seed * 1_000_003 + epoch * 10_007 + i), strength=cfg.augment_strength)


def fit(train_samples: list[Sample], val_samples: list[Sample], charset: Charset, *, out_dir: Path | str, cfg: FitConfig, resume: bool = False, verbose: bool = False) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(cfg.seed)
    model = CRNN(num_classes=charset.size, height=cfg.height).to(cfg.device)
    optimiser = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimiser, mode="min", factor=cfg.lr_factor, patience=cfg.lr_patience)
    ctc = torch.nn.CTCLoss(blank=0, zero_infinity=True)
    known = {s.text for s in train_samples}
    history: list[dict] = []
    best_cer, best_epoch, bad, start_epoch = float("inf"), 0, 0, 1
    last = out_dir / "last.pt"
    if resume and last.exists():
        state = torch.load(last, map_location=cfg.device, weights_only=False)
        model.load_state_dict(state["model"])
        optimiser.load_state_dict(state["optimiser"])
        scheduler.load_state_dict(state["scheduler"])
        history, best_cer, best_epoch, bad, start_epoch = state["history"], state["best_cer"], state["best_epoch"], state["bad"], state["epoch"] + 1
    stopped = "max epochs"
    started = time.perf_counter()
    for epoch in range(start_epoch, cfg.max_epochs + 1):
        t0 = time.perf_counter()
        loader = DataLoader(WordImages(train_samples, charset, height=cfg.height, max_width=cfg.max_width, augment=_augmenter(cfg, epoch)), batch_size=cfg.batch_size, shuffle=True,
                            collate_fn=collate, num_workers=cfg.workers, drop_last=False, generator=torch.Generator().manual_seed(cfg.seed + epoch))
        model.train()
        losses, images = [], 0
        for batch_images, targets, input_lengths, target_lengths in loader:
            loss = ctc(model(batch_images.to(cfg.device)).log_softmax(2), targets, input_lengths, target_lengths)
            optimiser.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimiser.step()
            losses.append(loss.item())
            images += batch_images.shape[0]
        val = evaluate(model, val_samples, charset, height=cfg.height, max_width=cfg.max_width, batch_size=cfg.eval_batch_size, device=cfg.device, known_words=known, workers=cfg.workers)
        lr_now = optimiser.param_groups[0]["lr"]
        scheduler.step(val["cer"])
        record = {"epoch": epoch, "train_loss": sum(losses) / len(losses), "train_images": images, "val_cer": val["cer"], "val_wer": val["wer"], "val_n": val["n"],
                  "val_split": val.get("split"), "lr": lr_now, "seconds": time.perf_counter() - t0}
        history.append(record)
        improved = val["cer"] < best_cer - cfg.min_delta
        if improved:
            best_cer, best_epoch, bad = val["cer"], epoch, 0
            _save({"state_dict": model.state_dict(), "chars": list(charset.chars), "height": cfg.height, "max_width": cfg.max_width, "epoch": epoch}, out_dir / "best.pt")
        else:
            bad += 1
        _save({"model": model.state_dict(), "optimiser": optimiser.state_dict(), "scheduler": scheduler.state_dict(), "history": history, "best_cer": best_cer,
               "best_epoch": best_epoch, "bad": bad, "epoch": epoch}, last)
        if verbose:
            print(f"epoch {epoch}/{cfg.max_epochs}: train loss {record['train_loss']:.3f}, validation character error {val['cer']:.3f} word error {val['wer']:.3f} "
                  f"on all {val['n']} validation images, lr {lr_now:.2g}, {record['seconds'] / 60:.1f} min{' (best)' if improved else ''}", flush=True)
        if bad >= cfg.patience:
            stopped = "no improvement"
            break
        if cfg.max_hours is not None and (time.perf_counter() - started) > cfg.max_hours * 3600:
            stopped = "time budget"
            break
    return {"history": history, "best_epoch": best_epoch, "best_val_cer": min((h["val_cer"] for h in history), default=float("nan")), "stopped": stopped}


def bootstrap_ci(values: list[float], *, seed: int, weights: Optional[list[float]] = None, n_boot: int = 1000) -> tuple[float, float]:
    """A 95% interval for a mean (or, with weights, a ratio of sums such as character error) by resampling the images."""
    n = len(values)
    if n == 0:
        return (float("nan"), float("nan"))
    v = torch.tensor(values, dtype=torch.float64)
    w = torch.tensor(weights if weights is not None else [1.0] * n, dtype=torch.float64)
    gen = torch.Generator().manual_seed(seed)
    stats = []
    for _ in range(n_boot):
        idx = torch.randint(n, (n,), generator=gen)
        denom = w[idx].sum()
        stats.append(float(v[idx].sum() / denom) if denom > 0 else 0.0)
    stats.sort()
    return (stats[int(0.025 * n_boot)], stats[min(n_boot - 1, int(0.975 * n_boot))])


def _charset_from(chars: list[str]) -> Charset:
    return Charset(chars=tuple(chars), _index={c: i + 1 for i, c in enumerate(chars)})


def final_test(best_path: Path | str, test_samples: list[Sample], *, known_words, cfg: FitConfig, out_dir: Path | str) -> dict:
    """Score the whole test split once with the best checkpoint. Writes every prediction to test_predictions.tsv and returns the scores with 95% intervals."""
    from htr_research.crnn import edit_distance
    state = torch.load(best_path, map_location=cfg.device, weights_only=False)
    charset = _charset_from(state["chars"])
    model = CRNN(num_classes=charset.size, height=state["height"]).to(cfg.device)
    model.load_state_dict(state["state_dict"])
    res = evaluate(model, test_samples, charset, height=state["height"], max_width=state["max_width"], batch_size=cfg.eval_batch_size, device=cfg.device, known_words=known_words,
                   workers=cfg.workers, return_predictions=True)
    preds = res.pop("predictions")
    edits = [float(edit_distance(p["prediction"], p["reference"])) for p in preds]
    lens = [float(max(1, len(p["reference"]))) for p in preds]
    wrong = [0.0 if p["prediction"] == p["reference"] else 1.0 for p in preds]
    cer_lo, cer_hi = bootstrap_ci(edits, seed=cfg.seed, weights=lens)
    wer_lo, wer_hi = bootstrap_ci(wrong, seed=cfg.seed)
    res["cer_ci"] = (min(cer_lo, res["cer"]), max(cer_hi, res["cer"]))
    res["wer_ci"] = (min(wer_lo, res["wer"]), max(wer_hi, res["wer"]))
    lines = ["path\treference\tprediction\tconfidence\tcorrect"] + [f"{p['path']}\t{p['reference']}\t{p['prediction']}\t{p['confidence']:.4f}\t{int(p['prediction'] == p['reference'])}" for p in preds]
    (Path(out_dir) / "test_predictions.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return res
