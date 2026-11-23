"""Loading and checking word-image handwriting data in the IIIT-Indic-HW-Words layout.

Layout: `<root>/{train,val,test}.txt` with rows `<split>/<n>.jpg, <vocab id>`, `<root>/vocab.txt` with one word per line (the line number is the id),
and the images under `<root>/<split>/`. Nothing here reads an image until it is asked to: loading the labels of 100,000 words is instant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SPLITS = ("train", "val", "test")


class LabelError(ValueError):
    """The labels or the vocabulary are not what the layout promises."""


@dataclass(frozen=True)
class Sample:
    path: Path
    text: str
    word_id: int


def parse_label_line(line: str) -> tuple[str, int]:
    parts = [p.strip() for p in (line or "").strip().split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
        raise LabelError(f"not a label row: {line!r}")
    return parts[0], int(parts[1])


def load_vocab(path: Path | str) -> list[str]:
    words = Path(path).read_text(encoding="utf-8").splitlines()
    if any(not w.strip() for w in words):
        raise LabelError("the vocabulary has a blank line, so line numbers no longer match word ids")
    return [w.strip() for w in words]


class WordDataset:
    """The (image path, word) pairs of one split. Images are read later by the loader."""

    def __init__(self, root: Path | str, split: str) -> None:
        self.root = Path(root)
        label_file = self.root / f"{split}.txt"
        if split not in SPLITS or not label_file.exists():
            raise LabelError(f"no labels for the split {split!r} in {self.root}")
        self.vocab = load_vocab(self.root / "vocab.txt")
        self.samples: list[Sample] = []
        for line in label_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rel, word_id = parse_label_line(line)
            if word_id >= len(self.vocab):
                raise LabelError(f"word id {word_id} is outside the vocabulary of {len(self.vocab)} words")
            self.samples.append(Sample(self.root / rel, self.vocab[word_id], word_id))

    def __len__(self) -> int:
        return len(self.samples)


@dataclass(frozen=True)
class Charset:
    """The characters the data uses. Index 0 is the CTC blank, so characters start at 1."""
    chars: tuple[str, ...]
    _index: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def size(self) -> int:
        return len(self.chars) + 1

    def encode(self, word: str) -> list[int]:
        try:
            return [self._index[c] for c in word]
        except KeyError as exc:
            raise LabelError(f"the character {exc.args[0]!r} is not in the charset") from None

    def decode(self, ids) -> str:
        return "".join(self.chars[i - 1] for i in ids if i != 0)


def build_charset(vocab: list[str]) -> Charset:
    chars = tuple(sorted(set("".join(vocab))))
    return Charset(chars=chars, _index={c: i + 1 for i, c in enumerate(chars)})


@dataclass(frozen=True)
class ValidationReport:
    counts: dict
    counts_match: Optional[bool]
    missing: dict
    vocab_size: int
    charset_size: int
    test_unseen_word_share: float          # share of test images whose word never appears in the training labels
    empty_labels: int

    @property
    def ok(self) -> bool:
        return not any(self.missing.values()) and self.counts_match is not False and self.empty_labels == 0


def validate(root: Path | str, *, expected_counts: Optional[dict] = None, missing_limit: int = 10) -> ValidationReport:
    """Counts against the published numbers, images that are listed but absent (the first `missing_limit` are named), the size of the vocabulary and charset,
    and how many test images show a word not seen in training. Checks file existence only: it does not open the images."""
    root = Path(root)
    datasets = {s: WordDataset(root, s) for s in SPLITS if (root / f"{s}.txt").exists()}
    if "train" not in datasets or "test" not in datasets:
        raise LabelError(f"{root} needs at least train.txt and test.txt (with vocab.txt) to be checked")
    counts = {s: len(d) for s, d in datasets.items()}
    missing = {s: [str(x.path.relative_to(root)).replace("\\", "/") for x in d.samples if not x.path.exists()][:missing_limit] for s, d in datasets.items()}
    vocab = next(iter(datasets.values())).vocab
    train_ids = {x.word_id for x in datasets["train"].samples}
    test = datasets["test"].samples
    unseen = sum(1 for x in test if x.word_id not in train_ids) / len(test) if test else 0.0
    return ValidationReport(counts=counts, counts_match=None if expected_counts is None else counts == expected_counts, missing=missing, vocab_size=len(vocab),
                            charset_size=len(set("".join(vocab))), test_unseen_word_share=unseen, empty_labels=sum(1 for w in vocab if not w))
