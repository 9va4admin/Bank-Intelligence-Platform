"""Load a labelled signature dataset and embed it with any embedder, for modules/cts/evaluation/signature_eval.py.

Manifest: a CSV with columns  path, writer_id, label  (label is GENUINE or SKILLED_FORGERY). Paths are relative to the manifest.
An embedder is any object with embed(image_bytes, bank_id=None) -> list[float], sync or async (the production
LocalSignatureEmbedder is async; a trained model can be either).
"""
from __future__ import annotations

import csv
import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from modules.cts.evaluation.signature_eval import GENUINE, SKILLED, SigSample
from shared.messages import get_message

_LABELS = (GENUINE, SKILLED)
_REQUIRED = ("path", "writer_id", "label")


class ManifestError(ValueError):
    """The manifest or an embedder spec is unusable; the message names the line or the spec."""


@dataclass(frozen=True)
class ManifestRow:
    path: Path
    writer_id: str
    label: str


def load_manifest(manifest: Path) -> list[ManifestRow]:
    manifest = Path(manifest)
    with manifest.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ManifestError(get_message("CTS_MANIFEST_IS_MISSING_COLUMN_S", value=', '.join(missing)))
        rows: list[ManifestRow] = []
        for line_no, rec in enumerate(reader, start=2):
            label = (rec["label"] or "").strip()
            if label not in _LABELS:
                raise ManifestError(f"line {line_no}: unknown label {label!r} (use {' or '.join(_LABELS)})")
            path = manifest.parent / (rec["path"] or "").strip()
            if not path.is_file():
                raise ManifestError(get_message("CTS_LINE_IMAGE_NOT_FOUND", line_no=line_no, rec=rec['path']))
            rows.append(ManifestRow(path=path, writer_id=(rec["writer_id"] or "").strip(), label=label))
    return rows


def load_embedder(spec: str) -> Any:
    """'package.module:Attr' -> Attr() (a class or factory returning the embedder)."""
    if ":" not in spec:
        raise ManifestError(f"embedder spec must look like 'package.module:Attr', got {spec!r}")
    module, _, attr = spec.partition(":")
    try:
        target = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as exc:
        raise ManifestError(f"cannot load embedder {spec!r}: {exc}") from exc
    return target()


async def embed_samples(embedder: Any, rows: Sequence[ManifestRow], bank_id: Optional[str] = "eval", crop=None) -> list[SigSample]:
    """Embed every image. `crop` is an optional bytes->bytes function applied before embedding (e.g. cut the signature out of a cheque)."""
    out: list[SigSample] = []
    for row in rows:
        data = row.path.read_bytes()
        if crop is not None:
            data = crop(data)
        result = embedder.embed(data, bank_id=bank_id)
        vector = await result if inspect.isawaitable(result) else result
        out.append(SigSample(row.writer_id, row.label, list(vector)))
    return out
