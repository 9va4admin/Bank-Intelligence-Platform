"""Drop-in replacement for shared.ai.local_signature_embedder.LocalSignatureEmbedder: same embed(image_bytes, bank_id) shape and the same
512-d unit vectors, so the vault and the verifier need no change. `trained` is True only when the model card records a promotion."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
from typing import Optional

import torch
from PIL import Image

from modules.cts.signature_training.checkpoint import MODEL_LABEL, card_path
from modules.cts.signature_training.model import SignatureNet, preprocess


class TrainedSignatureEmbedder:
    MODEL_LABEL = MODEL_LABEL

    def __init__(self, checkpoint: Optional[Path] = None, *, _model: Optional[SignatureNet] = None, _size: int = 224,
                 _promoted: bool = False) -> None:
        version_id = f"{MODEL_LABEL}@unsaved"
        if checkpoint is not None:
            checkpoint = Path(checkpoint)
            # identifies THESE weights: a retrained checkpoint gets a new id, so the vault re-embeds instead of mixing vectors
            version_id = f"{MODEL_LABEL}@{hashlib.sha256(checkpoint.read_bytes()).hexdigest()[:12]}"
            blob = torch.load(checkpoint, map_location="cpu", weights_only=True)
            _model = SignatureNet(init=None)
            _model.trunk.load_state_dict(blob["trunk"])
            _size = int(blob["size"])
            cp = card_path(checkpoint)
            _promoted = bool(json.loads(cp.read_text(encoding="utf-8")).get("promoted")) if cp.exists() else False
        self._net = _model.eval()
        self._size = _size
        self.trained = _promoted
        self.version_id = version_id

    @classmethod
    def from_model(cls, model: SignatureNet, size: int) -> "TrainedSignatureEmbedder":
        return cls(_model=model, _size=size)

    def _embed_pil(self, img: Image.Image) -> list[float]:
        with torch.no_grad():
            return self._net.embed(preprocess(img, self._size).unsqueeze(0))[0].tolist()

    def _embed_sync(self, image_bytes: bytes) -> list[float]:
        return self._embed_pil(Image.open(io.BytesIO(image_bytes)))

    async def embed(self, image_bytes: bytes, bank_id: str = "") -> list[float]:
        return await asyncio.to_thread(self._embed_sync, image_bytes)
