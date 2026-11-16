"""On-prem signature embedder training from GENUINE specimens only (no forgery labels needed).

Positives are two augmented views of the same signature (and any other specimens of the same account); negatives are other accounts'
signatures. The result is judged on writers the model never saw. The trained embedder stays flagged untrained until a promotion record exists.
"""
import asyncio
import io
import json
import random

import pytest

torch = pytest.importorskip("torch")
from PIL import Image, ImageDraw  # noqa: E402

from modules.cts.signature_training.augment import augment  # noqa: E402
from modules.cts.signature_training.loss import supcon_loss  # noqa: E402
from modules.cts.signature_training.train import train  # noqa: E402
from modules.cts.signature_training.embedder import TrainedSignatureEmbedder  # noqa: E402
from modules.cts.signature_training.checkpoint import save_checkpoint  # noqa: E402


def _signature(seed, size=96):
    """A toy 'signature': a few random strokes on white (distinct per seed)."""
    rng = random.Random(seed)
    img = Image.new("L", (size, size // 2), 255)
    d = ImageDraw.Draw(img)
    pts = [(rng.randint(2, size - 2), rng.randint(2, size // 2 - 2)) for _ in range(7)]
    d.line(pts, fill=20, width=2)
    return img


def test_augment_is_deterministic_per_seed_and_varies_between_seeds():
    base = _signature(1)
    a1 = augment(base, random.Random(5))
    a2 = augment(base, random.Random(5))
    b = augment(base, random.Random(6))
    assert a1.mode == "L" and list(a1.getdata()) == list(a2.getdata())
    assert list(a1.getdata()) != list(b.getdata())


def test_augment_never_returns_a_blank_page():
    base = _signature(2)
    for s in range(20):
        arr = list(augment(base, random.Random(s)).getdata())
        assert min(arr) < 200           # ink survives the crop / blur / noise


def test_supcon_loss_is_lower_when_same_writer_embeddings_agree():
    labels = torch.tensor([0, 0, 1, 1, 2, 2])
    aligned = torch.nn.functional.normalize(torch.tensor(
        [[1., 0, 0], [1, .05, 0], [0, 1, 0], [0, 1, .05], [0, 0, 1], [.05, 0, 1]]), dim=1)
    shuffled = aligned[torch.tensor([0, 2, 4, 1, 3, 5])]
    assert supcon_loss(aligned, labels).item() < supcon_loss(shuffled, labels).item()


def test_supcon_loss_with_all_distinct_writers_is_the_simclr_case():
    z = torch.nn.functional.normalize(torch.randn(8, 16), dim=1)
    labels = torch.tensor([0, 0, 1, 1, 2, 2, 3, 3])       # two views per signature, one signature per writer
    assert torch.isfinite(supcon_loss(z, labels))


def _margin(embedder, n=8, seed=99):
    """mean cosine(same signature, new augmented view) minus mean cosine(different signatures)."""
    rng = random.Random(seed)
    same, diff = [], []
    for i in range(n):
        a = embedder._embed_pil(_signature(i))
        b = embedder._embed_pil(augment(_signature(i), rng))
        c = embedder._embed_pil(_signature((i + 1) % n))
        same.append(sum(x * y for x, y in zip(a, b)))
        diff.append(sum(x * y for x, y in zip(a, c)))
    return sum(same) / n - sum(diff) / n


def test_training_reduces_the_loss_and_widens_the_same_vs_different_margin():
    from modules.cts.signature_training.model import SignatureNet
    imgs = [(f"W{i}", _signature(i)) for i in range(8)]
    torch.manual_seed(0)
    untrained = TrainedSignatureEmbedder.from_model(SignatureNet(init=None).eval(), size=64)      # same starting weights as train(seed=0)
    model, history = train(imgs, epochs=25, batch_size=4, size=64, lr=3e-4, seed=0, init=None)
    assert history[-1] < history[0]
    assert _margin(TrainedSignatureEmbedder.from_model(model, size=64)) > _margin(untrained)


def test_embedder_returns_a_512d_unit_vector_and_loads_from_a_checkpoint(tmp_path):
    imgs = [(f"W{i}", _signature(i)) for i in range(4)]
    model, history = train(imgs, epochs=2, batch_size=8, size=64, seed=0, init=None)
    ckpt = tmp_path / "sig.pt"
    save_checkpoint(model, ckpt, size=64, n_images=4, n_writers=4, final_loss=history[-1])
    emb = TrainedSignatureEmbedder(ckpt)
    buf = io.BytesIO(); _signature(3).save(buf, format="PNG")
    v = asyncio.run(emb.embed(buf.getvalue(), bank_id="kbl"))
    assert len(v) == 512 and abs(sum(x * x for x in v) - 1.0) < 1e-4


def test_trained_flag_follows_the_promotion_record_not_the_fact_of_training(tmp_path):
    imgs = [(f"W{i}", _signature(i)) for i in range(4)]
    model, history = train(imgs, epochs=1, batch_size=8, size=64, seed=0, init=None)
    ckpt = tmp_path / "sig.pt"
    save_checkpoint(model, ckpt, size=64, n_images=4, n_writers=4, final_loss=history[-1])
    assert TrainedSignatureEmbedder(ckpt).trained is False                       # trained, but not promoted
    card = json.loads(ckpt.with_suffix(".card.json").read_text())
    assert card["promoted"] is False and card["trained_on"] == {"n_images": 4, "n_writers": 4}
    card["promoted"] = True
    ckpt.with_suffix(".card.json").write_text(json.dumps(card))
    assert TrainedSignatureEmbedder(ckpt).trained is True


def test_training_needs_at_least_two_signatures():
    with pytest.raises(ValueError):
        train([("W0", _signature(0))], epochs=1, batch_size=4, size=64, init=None)


# ---------------------------------------------------------------------------
# Worker wiring: signature.embedder_checkpoint selects the trained embedder; anything wrong falls back to the generic one (which stays
# flagged untrained, so the confirm gate holds).
# ---------------------------------------------------------------------------

class _Cfg:
    def __init__(self, value=""):
        self.value = value

    async def get(self, key):
        assert key == "signature.embedder_checkpoint"
        return self.value


class _GenericStandIn:
    trained = False


def _patch_generic(monkeypatch):
    import shared.ai.local_signature_embedder as m
    monkeypatch.setattr(m, "LocalSignatureEmbedder", _GenericStandIn)


def test_worker_uses_the_configured_checkpoint(tmp_path, monkeypatch):
    from modules.cts.worker_activities import _build_embedding_model
    _patch_generic(monkeypatch)
    model, history = train([(f"W{i}", _signature(i)) for i in range(4)], epochs=1, batch_size=8, size=64, seed=0, init=None)
    ckpt = tmp_path / "sig.pt"
    save_checkpoint(model, ckpt, size=64, n_images=4, n_writers=4, final_loss=history[-1])
    got = asyncio.run(_build_embedding_model(_Cfg(str(ckpt))))
    assert isinstance(got, TrainedSignatureEmbedder) and got.trained is False       # loaded, not promoted


def test_worker_falls_back_to_the_generic_embedder_when_nothing_is_configured(monkeypatch):
    from modules.cts.worker_activities import _build_embedding_model
    _patch_generic(monkeypatch)
    assert isinstance(asyncio.run(_build_embedding_model(_Cfg(""))), _GenericStandIn)
    assert isinstance(asyncio.run(_build_embedding_model(None)), _GenericStandIn)


def test_worker_falls_back_to_the_generic_embedder_when_the_checkpoint_is_unusable(tmp_path, monkeypatch):
    from modules.cts.worker_activities import _build_embedding_model
    _patch_generic(monkeypatch)
    bad = tmp_path / "bad.pt"
    bad.write_bytes(b"not a checkpoint")
    assert isinstance(asyncio.run(_build_embedding_model(_Cfg(str(bad)))), _GenericStandIn)
    assert isinstance(asyncio.run(_build_embedding_model(_Cfg(str(tmp_path / "missing.pt")))), _GenericStandIn)
