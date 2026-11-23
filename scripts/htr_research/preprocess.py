"""Turning a word image into a model input, and a list of them into a padded batch."""
from __future__ import annotations

import torch
from PIL import Image

WIDTH_STEP = 4          # the model shortens the width by 4, so widths are kept a multiple of 4


def prepare_image(image: Image.Image, *, height: int, max_width: int) -> torch.Tensor:
    """Grayscale, scaled to `height` keeping the shape, then a width that is a multiple of 4 and at most `max_width` (a wider image is shrunk, never cropped).
    Pixels are inverted so ink is near 1 and paper near 0: padding with zeros then means 'blank paper'."""
    gray = image.convert("L")
    width = round(gray.width * height / max(1, gray.height))
    width = min(max_width, max(WIDTH_STEP, -(-width // WIDTH_STEP) * WIDTH_STEP))
    resized = gray.resize((width, height), Image.LANCZOS)
    pixels = torch.frombuffer(bytearray(resized.tobytes()), dtype=torch.uint8).reshape(1, height, width).to(torch.float32)
    return (255.0 - pixels) / 255.0


def collate(batch):
    """[(tensor (1,H,W), target ids)] -> images (B,1,H,Wmax) padded with blank paper, concatenated targets, and the input and target lengths for the CTC loss."""
    width = max(t.shape[-1] for t, _ in batch)
    images = torch.zeros(len(batch), 1, batch[0][0].shape[-2], width)
    for i, (t, _) in enumerate(batch):
        images[i, :, :, :t.shape[-1]] = t
    targets = torch.tensor([c for _, ids in batch for c in ids], dtype=torch.long)
    input_lengths = torch.tensor([t.shape[-1] // WIDTH_STEP for t, _ in batch], dtype=torch.long)
    target_lengths = torch.tensor([len(ids) for _, ids in batch], dtype=torch.long)
    return images, targets, input_lengths, target_lengths
