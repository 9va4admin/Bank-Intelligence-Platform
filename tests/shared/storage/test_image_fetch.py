"""fetch_image_bytes: one place that turns an image URL into bytes.

Found by the first real API-submitted scan: the API issues s3://bucket/key object URLs, but every
image-reading activity fetched with an HTTP client -> 'unsupported protocol s3://', so OCR saw no
image and every scan was rejected UNDATED. Activities must go through this function."""
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.storage.image_fetch import fetch_image_bytes, configure_default_store


@pytest.mark.asyncio
async def test_s3_url_is_read_through_the_object_store():
    store = MagicMock(); store.download_bytes = AsyncMock(return_value=b"IMG")
    configure_default_store(store)
    assert await fetch_image_bytes("s3://cts-images/kbl/outward/s1/front.tiff") == b"IMG"
    store.download_bytes.assert_awaited_once_with("cts-images", "kbl/outward/s1/front.tiff")


@pytest.mark.asyncio
async def test_http_url_uses_http_client():
    resp = MagicMock(); resp.content = b"HTTPIMG"; resp.raise_for_status = MagicMock()
    client = MagicMock(); client.get = AsyncMock(return_value=resp)
    cm = MagicMock(); cm.__aenter__ = AsyncMock(return_value=client); cm.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=cm):
        assert await fetch_image_bytes("http://minio:9000/b/k?sig=1") == b"HTTPIMG"
    client.get.assert_awaited_once_with("http://minio:9000/b/k?sig=1")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["ftp://x/y", "s3://bucketonly", "s3:///nokey", "/local/path.jpg", ""])
async def test_unsupported_or_malformed_urls_raise_value_error(bad):
    with pytest.raises(ValueError):
        await fetch_image_bytes(bad)


_DIRECT = re.compile(r"client\.get\((?:inp\.)?(?:image\w*|url)\b")


@pytest.mark.parametrize("name", ["ocr.py", "detect_signatures.py", "outward_scan_activities.py"])
def test_activities_do_not_fetch_image_urls_directly(name):
    src = Path(f"modules/cts/workflows/activities/{name}").read_text(encoding="utf-8")
    assert not _DIRECT.findall(src), f"{name} fetches an image URL with a raw HTTP client; use fetch_image_bytes"


# ── minio:// and bare keys (found tracing where images go after the 2026-10 integration run) ──────────────────────────────
# Two producers (the scanner drop-folder watcher and the branch EEH upload) write `minio://bucket/key`, and the inward batch workflow handed
# the cheque workflow a bare object key. Neither form could be fetched, so every such cheque went to human review.

@pytest.mark.asyncio
async def test_minio_url_is_read_like_an_s3_url():
    store = MagicMock(); store.download_bytes = AsyncMock(return_value=b"IMG")
    configure_default_store(store)
    assert await fetch_image_bytes("minio://cts-files/cts/inward/b1/front_bw.tiff") == b"IMG"
    store.download_bytes.assert_awaited_once_with("cts-files", "cts/inward/b1/front_bw.tiff")


def test_image_ref_builds_a_bucket_qualified_url():
    from shared.storage.image_fetch import image_ref
    assert image_ref("cts-files", "cts/inward/b1/front_bw.tiff") == "s3://cts-files/cts/inward/b1/front_bw.tiff"
    assert image_ref("cts-files", "/leading/slash.tiff") == "s3://cts-files/leading/slash.tiff"


@pytest.mark.asyncio
async def test_a_bare_object_key_is_still_refused_with_a_clear_message():
    with pytest.raises(ValueError, match="unsupported image URL scheme"):
        await fetch_image_bytes("cts/inward/b1/front_bw.tiff")


def test_inward_batch_workflow_hands_the_cheque_workflow_a_bucket_qualified_url():
    src = Path("modules/cts/workflows/inward_batch_workflow.py").read_text(encoding="utf8")
    assert "image_url=upload_result.front_bw_key" not in src
    assert "image_url=image_ref(inp.minio_bucket, upload_result.front_bw_key)" in src


@pytest.fixture(autouse=True)
def _reset_default_store():
    yield
    configure_default_store(None)  # a fake store left configured would leak into every later test in the run


# ── model_image_url: what a model server is given ────────────────────────────
# vLLM can only read http(s) and data: URLs. Handing it the s3:// / minio:// reference the activities carry made
# every MinIO-stored cheque unreadable to the model, so the reference is resolved to bytes first.

def _png() -> bytes:
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (4, 4), (255, 255, 255)).save(b, format="PNG"); return b.getvalue()


def _tiff() -> bytes:
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (4, 4), (255, 255, 255)).save(b, format="TIFF"); return b.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("passthrough", ["http://minio:9000/b/k?sig=1", "https://x/y.png", "data:image/png;base64,AAAA"])
async def test_model_image_url_leaves_urls_a_model_can_read_alone(passthrough):
    from shared.storage.image_fetch import model_image_url
    assert await model_image_url(passthrough) == passthrough


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["s3://b/k.png", "minio://b/k.png"])
async def test_model_image_url_inlines_object_store_references(ref):
    import base64
    from shared.storage.image_fetch import model_image_url
    store = MagicMock(); store.download_bytes = AsyncMock(return_value=_png())
    configure_default_store(store)
    out = await model_image_url(ref)
    assert out.startswith("data:image/png;base64,")
    assert base64.b64decode(out.split(",", 1)[1]) == _png()


@pytest.mark.asyncio
async def test_model_image_url_converts_tiff_to_png():
    from shared.storage.image_fetch import model_image_url
    store = MagicMock(); store.download_bytes = AsyncMock(return_value=_tiff())
    configure_default_store(store)
    assert (await model_image_url("s3://b/front_bw.tiff")).startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_model_image_url_refuses_an_unreadable_reference():
    from shared.storage.image_fetch import model_image_url
    with pytest.raises(ValueError):
        await model_image_url("cts/inward/b/1/front_bw.tiff")  # bare key: no bucket
