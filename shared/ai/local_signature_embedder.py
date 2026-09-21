"""
LocalSignatureEmbedder — CPU signature embedder (dev/pilot stand-in).

HONEST LABEL: this is a GENERIC ImageNet ResNet-18 backbone, NOT the
custom-trained Siamese network CLAUDE.md specifies (no trained artifact exists
in this repo). Cosine similarity of generic features is a weak forgery signal;
it exists so extract -> embed -> store vector -> compare-at-runtime runs for
real, on-prem, with no vLLM and no cloud call. Replace with the trained model
by supplying another object with the same `embed(image_bytes, bank_id)` shape.
"""
import asyncio
import io

import structlog

log = structlog.get_logger()

MODEL_LABEL = "resnet18-imagenet-generic"
_SIZE = 224


class LocalSignatureEmbedder:
    def __init__(self) -> None:
        import torch
        import torchvision

        self._torch = torch
        weights = torchvision.models.ResNet18_Weights.DEFAULT
        net = torchvision.models.resnet18(weights=weights)
        net.fc = torch.nn.Identity()          # 512-d pooled features
        self._net = net.eval()
        self._mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        self._std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)

    def _embed_sync(self, image_bytes: bytes) -> list[float]:
        from PIL import Image
        import numpy as np

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
        except Exception as exc:
            raise ValueError(f"undecodable signature image: {exc}") from exc
        # pad to a square on white so the stroke aspect ratio is preserved
        side = max(img.size)
        canvas = Image.new("L", (side, side), 255)
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        canvas = canvas.resize((_SIZE, _SIZE))
        arr = np.asarray(canvas, dtype="float32") / 255.0
        t = self._torch.from_numpy(arr).unsqueeze(0).repeat(3, 1, 1)
        t = ((t - self._mean) / self._std).unsqueeze(0)
        with self._torch.no_grad():
            v = self._net(t)[0]
        v = v / (v.norm() + 1e-12)
        return v.tolist()

    async def embed(self, image_bytes: bytes, bank_id: str = "") -> list[float]:
        return await asyncio.to_thread(self._embed_sync, image_bytes)
