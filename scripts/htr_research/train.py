"""Training and evaluating the CRNN on word samples (CPU or GPU). Used for a pipeline check on a CPU and, later, for real runs on a GPU host."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from htr_research.crnn import CRNN, cer_wer, coverage_table, ctc_greedy_decode, split_scores, word_confidence
from htr_research.dataset import Charset, Sample
from htr_research.preprocess import collate, prepare_image


class WordImages(Dataset):
    def __init__(self, samples: list[Sample], charset: Charset, *, height: int, max_width: int) -> None:
        self.samples, self.charset, self.height, self.max_width = samples, charset, height, max_width

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, i: int):
        s = self.samples[i]
        with Image.open(s.path) as img:
            tensor = prepare_image(img, height=self.height, max_width=self.max_width)
        return tensor, self.charset.encode(s.text)


@dataclass
class TrainResult:
    model: CRNN
    losses: list[float]          # the mean loss of each logging window
    seconds: float
    images_per_second: float


def train(samples: list[Sample], charset: Charset, *, steps: int, batch_size: int, lr: float, seed: int, height: int, max_width: int, device: str, workers: int,
          log_every: int, model: CRNN | None = None, verbose: bool = False) -> TrainResult:
    """Adam with the CTC loss for `steps` batches drawn at random. Returns the model, the mean loss per `log_every` steps, and the speed in images per second."""
    random.seed(seed)
    torch.manual_seed(seed)
    model = (model or CRNN(num_classes=charset.size, height=height)).to(device)
    loader = DataLoader(WordImages(samples, charset, height=height, max_width=max_width), batch_size=batch_size, shuffle=True, collate_fn=collate, num_workers=workers,
                        persistent_workers=workers > 0, drop_last=len(samples) >= batch_size)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    ctc = torch.nn.CTCLoss(blank=0, zero_infinity=True)
    model.train()
    losses, window, step, images = [], [], 0, 0
    started = time.perf_counter()
    while step < steps:
        for batch_images, targets, input_lengths, target_lengths in loader:
            log_probs = model(batch_images.to(device)).log_softmax(2)
            loss = ctc(log_probs, targets, input_lengths, target_lengths)
            optimiser.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimiser.step()
            step += 1
            images += batch_images.shape[0]
            window.append(loss.item())
            if step % log_every == 0 or step == steps:
                losses.append(sum(window) / len(window))
                window = []
                if verbose:
                    print(f"step {step}/{steps} loss {losses[-1]:.3f} {images / (time.perf_counter() - started):.1f} images/s", flush=True)
            if step >= steps:
                break
    seconds = time.perf_counter() - started
    return TrainResult(model=model, losses=losses, seconds=seconds, images_per_second=images / seconds if seconds else 0.0)


@torch.no_grad()
def evaluate(model: CRNN, samples: list[Sample], charset: Charset, *, height: int, max_width: int, batch_size: int, device: str = "cpu", known_words=None) -> dict:
    """Greedy-decoded character and word error rates over the samples. Also the error on words seen versus never seen in training (when `known_words` is given)
    and the accuracy at each confidence level."""
    model.eval().to(device)
    loader = DataLoader(WordImages(samples, charset, height=height, max_width=max_width), batch_size=batch_size, shuffle=False, collate_fn=collate, num_workers=0)
    predictions: list[str] = []
    confidences: list[float] = []
    for images, _, _, _ in loader:
        logits = model(images.to(device))
        predictions += [charset.decode(ids) for ids in ctc_greedy_decode(logits)]
        confidences += word_confidence(logits)
    references = [s.text for s in samples]
    cer, wer = cer_wer(predictions, references)
    result = {"cer": cer, "wer": wer, "n": len(samples)}
    result["coverage"] = coverage_table(confidences, [p == r for p, r in zip(predictions, references)], [0.0, 0.5, 0.7, 0.8, 0.9, 0.95])
    if known_words is not None:
        result["split"] = split_scores(predictions, references, known_words)
    return result
