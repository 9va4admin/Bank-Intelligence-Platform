"""Manifest loading and embedding for the signature evaluation. Manifest CSV columns: path, writer_id, label (GENUINE | SKILLED_FORGERY)."""
import asyncio

import pytest

from modules.cts.evaluation.signature_dataset import ManifestError, embed_samples, load_embedder, load_manifest


def _write(tmp_path, rows, header="path,writer_id,label"):
    for name in {r.split(",")[0] for r in rows}:
        (tmp_path / name).write_bytes(name.encode())
    m = tmp_path / "m.csv"
    m.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return m


def test_loads_rows_with_paths_resolved_next_to_the_manifest(tmp_path):
    m = _write(tmp_path, ["a.png,W1,GENUINE", "b.png,W1,SKILLED_FORGERY"])
    rows = load_manifest(m)
    assert [(r.writer_id, r.label) for r in rows] == [("W1", "GENUINE"), ("W1", "SKILLED_FORGERY")]
    assert rows[0].path == tmp_path / "a.png"


def test_rejects_an_unknown_label_naming_the_line(tmp_path):
    m = _write(tmp_path, ["a.png,W1,GENUINE", "b.png,W1,FORGED"])
    with pytest.raises(ManifestError, match="line 3.*FORGED"):
        load_manifest(m)


def test_rejects_a_missing_image_naming_the_line(tmp_path):
    m = _write(tmp_path, ["a.png,W1,GENUINE"])
    (tmp_path / "a.png").unlink()
    with pytest.raises(ManifestError, match="line 2.*a.png"):
        load_manifest(m)


def test_rejects_missing_columns(tmp_path):
    m = _write(tmp_path, ["a.png,W1"], header="path,writer_id")
    with pytest.raises(ManifestError, match="label"):
        load_manifest(m)


class _Sync:
    def embed(self, image_bytes, bank_id=None):
        return [float(len(image_bytes)), 1.0]


class _Async:
    async def embed(self, image_bytes, bank_id=None):
        return [float(len(image_bytes)), 2.0]


@pytest.mark.parametrize("embedder,second", [(_Sync(), 1.0), (_Async(), 2.0)])
def test_embeds_with_a_sync_or_async_embedder(tmp_path, embedder, second):
    rows = load_manifest(_write(tmp_path, ["a.png,W1,GENUINE", "bb.png,W2,SKILLED_FORGERY"]))
    samples = asyncio.run(embed_samples(embedder, rows))
    assert [(s.writer_id, s.label) for s in samples] == [("W1", "GENUINE"), ("W2", "SKILLED_FORGERY")]
    assert samples[0].vector == [5.0, second] and samples[1].vector == [6.0, second]


def test_load_embedder_by_module_attribute():
    emb = load_embedder("tests.modules.cts.evaluation.test_signature_dataset:_Sync")
    assert isinstance(emb, _Sync)


def test_load_embedder_rejects_a_bad_spec():
    with pytest.raises(ManifestError):
        load_embedder("not-a-spec")
