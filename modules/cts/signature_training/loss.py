"""Supervised contrastive loss. One function covers both cases: when each signature has only itself (two views) as a positive it is
SimCLR NT-Xent; when an account has several specimens, all of them are positives for each other."""
from __future__ import annotations

import torch


def supcon_loss(z: torch.Tensor, labels: torch.Tensor, temperature: float = 0.1) -> torch.Tensor:
    """z: (N, d) L2-normalised embeddings; labels: (N,) writer ids. Anchors without a positive in the batch are skipped."""
    n = z.shape[0]
    sim = z @ z.T / temperature
    self_mask = torch.eye(n, dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(self_mask, float("-inf"))
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    positives = (labels[:, None] == labels[None, :]) & ~self_mask
    has_pos = positives.any(dim=1)
    if not has_pos.any():
        return z.sum() * 0.0
    mean_pos = (log_prob.masked_fill(~positives, 0.0)).sum(dim=1)[has_pos] / positives.sum(dim=1)[has_pos]
    return -mean_pos.mean()
