"""The signature network: a ResNet-18 trunk giving the 512-d embedding the vault already stores, plus a projection head used only
while training. Preprocessing matches shared/ai/local_signature_embedder.py (pad to square on white, resize, grayscale -> 3 channels)."""
from __future__ import annotations

import torch
import torch.nn as nn
import torchvision
from PIL import Image

_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


class SignatureNet(nn.Module):
    def __init__(self, init: str | None = "imagenet") -> None:
        super().__init__()
        weights = torchvision.models.ResNet18_Weights.DEFAULT if init == "imagenet" else None
        trunk = torchvision.models.resnet18(weights=weights)
        trunk.fc = nn.Identity()
        self.trunk = trunk
        self.head = nn.Sequential(nn.Linear(512, 512), nn.ReLU(), nn.Linear(512, 128))   # training only, discarded at inference

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        return nn.functional.normalize(self.trunk(x), dim=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return nn.functional.normalize(self.head(self.trunk(x)), dim=1)


def preprocess(img: Image.Image, size: int) -> torch.Tensor:
    import numpy as np

    img = img.convert("L")
    side = max(img.size)
    canvas = Image.new("L", (side, side), 255)
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    arr = np.asarray(canvas.resize((size, size)), dtype="float32") / 255.0
    t = torch.from_numpy(arr).unsqueeze(0).repeat(3, 1, 1)
    return (t - _MEAN) / _STD
