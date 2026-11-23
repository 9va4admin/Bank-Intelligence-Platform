"""A small CRNN for handwritten word images: a convolutional feature extractor, a bidirectional LSTM over the width, and a CTC output layer.

This is a deliberately plain baseline in the spirit of the 2021 IIIT-Indic-HW-Words recognizer (CNN + BLSTM + CTC), without its spatial transformer and with a smaller
CNN, so it runs on a CPU for a pipeline check. It is NOT a reproduction of the published numbers.
"""
from __future__ import annotations

import torch
from torch import nn


def _block(cin: int, cout: int, pool) -> nn.Sequential:
    layers = [nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(inplace=True)]
    if pool is not None:
        layers.append(nn.MaxPool2d(pool))
    return nn.Sequential(*layers)


class CRNN(nn.Module):
    """Input (B, 1, height, W) with W a multiple of 4; output (W // 4, B, num_classes) scores, class 0 being the CTC blank."""

    def __init__(self, *, num_classes: int, height: int, hidden: int = 192, lstm_layers: int = 2) -> None:
        super().__init__()
        self.cnn = nn.Sequential(_block(1, 32, 2), _block(32, 64, 2), _block(64, 128, None), _block(128, 128, (2, 1)), _block(128, 256, (2, 1)))
        self.rnn = nn.LSTM(256, hidden, num_layers=lstm_layers, bidirectional=True, dropout=0.1 if lstm_layers > 1 else 0.0)
        self.head = nn.Linear(2 * hidden, num_classes)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        features = self.cnn(images).mean(dim=2)                  # (B, 256, W/4): average over the remaining height
        sequence = features.permute(2, 0, 1)                    # (W/4, B, 256)
        out, _ = self.rnn(sequence)
        return self.head(out)


def ctc_greedy_decode(logits: torch.Tensor, blank: int = 0) -> list[list[int]]:
    """The best class at every step, repeats merged, blanks removed. logits is (T, B, C)."""
    best = logits.argmax(dim=2).permute(1, 0).tolist()
    out = []
    for path in best:
        ids, prev = [], blank
        for c in path:
            if c != prev and c != blank:
                ids.append(c)
            prev = c
        out.append(ids)
    return out


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer_wer(predictions: list[str], references: list[str]) -> tuple[float, float]:
    """Character error rate (edits over reference characters) and word error rate (the share of words not read exactly right)."""
    if not references:
        return 0.0, 0.0
    chars = sum(len(r) for r in references)
    edits = sum(edit_distance(p, r) for p, r in zip(predictions, references))
    wrong = sum(p != r for p, r in zip(predictions, references))
    return (edits / chars if chars else 0.0), wrong / len(references)
