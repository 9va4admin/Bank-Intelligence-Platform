"""Train a signature embedder from genuine specimens only.

Each step takes a batch of signatures, makes two independently augmented views of each, and pulls views of the same writer together
while pushing other writers apart (supcon_loss). No forged examples are needed. This teaches writer identity and invariance to capture
variation; it does NOT teach what a skilled forgery looks like, so it cannot by itself prove protection against one.
"""
from __future__ import annotations

import random
from typing import Optional, Sequence

import torch
from PIL import Image

from modules.cts.signature_training.augment import augment
from modules.cts.signature_training.loss import supcon_loss
from modules.cts.signature_training.model import SignatureNet, preprocess
from shared.messages import get_message


def train(
    images: Sequence[tuple[str, Image.Image]], epochs: int = 30, batch_size: int = 32, size: int = 224,
    lr: float = 1e-4, seed: int = 0, init: Optional[str] = "imagenet", temperature: float = 0.1,
) -> tuple[SignatureNet, list[float]]:
    """images: (writer_id, PIL image). Returns (model, mean loss per epoch)."""
    if len(images) < 2:
        raise ValueError(get_message("CTS_TRAINING_NEEDS_AT_LEAST_TWO_SIGNATURES"))
    torch.manual_seed(seed)
    rng = random.Random(seed)
    writers = sorted({w for w, _ in images})
    label_of = {w: i for i, w in enumerate(writers)}
    model = SignatureNet(init=init)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    history: list[float] = []
    model.train()
    for _ in range(epochs):
        order = list(range(len(images)))
        rng.shuffle(order)
        losses = []
        for start in range(0, len(order), batch_size):
            idx = order[start:start + batch_size]
            if len(idx) < 2:
                continue
            views, labels = [], []
            for i in idx:
                w, img = images[i]
                for _view in range(2):
                    views.append(preprocess(augment(img, rng), size))
                    labels.append(label_of[w])
            z = model(torch.stack(views))
            loss = supcon_loss(z, torch.tensor(labels), temperature)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(loss.item())
        history.append(sum(losses) / max(1, len(losses)))
    model.eval()
    return model, history
