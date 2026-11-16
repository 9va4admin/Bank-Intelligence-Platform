"""Checkpoint + model card. The card records what the model was trained on and whether it has been PROMOTED; promotion is a separate,
recorded act (after an evaluation on data the bank accepts), never a side effect of training."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import torch

from modules.cts.signature_training.model import SignatureNet

MODEL_LABEL = "resnet18-signature-contrastive"


def card_path(ckpt: Path) -> Path:
    return Path(ckpt).with_suffix(".card.json")


def save_checkpoint(model: SignatureNet, path: Path, size: int, n_images: int, n_writers: int, final_loss: float,
                    evaluation: Optional[dict] = None) -> None:
    path = Path(path)
    torch.save({"trunk": model.trunk.state_dict(), "size": size}, path)
    card_path(path).write_text(json.dumps({
        "model_label": MODEL_LABEL, "input_size": size, "embedding_dim": 512,
        "trained_on": {"n_images": n_images, "n_writers": n_writers},
        "final_training_loss": round(final_loss, 6),
        "evaluation": evaluation,          # writer-disjoint results from modules/cts/evaluation, when available
        "promoted": False,                 # flipped only by a recorded promotion decision
    }, indent=2), encoding="utf-8")
