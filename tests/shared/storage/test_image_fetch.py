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
