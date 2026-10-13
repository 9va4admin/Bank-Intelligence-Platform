"""check_image_quality activity: fetches the image, measures it, never raises."""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image, ImageFilter, ImageDraw

from modules.cts.workflows.activities.image_quality import IQAInput, check_image_quality


def _png(blur=0, w=800, h=360):
    img = Image.new("L", (w, h), 235)
    d = ImageDraw.Draw(img)
    for y in range(30, h - 30, 24):
        for x in range(20, w - 60, 55):
            d.rectangle([x, y, x + 35, y + 6], fill=15)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    b = io.BytesIO(); img.save(b, "PNG")
    return b.getvalue()


def _cs(overrides=None):
    cs = MagicMock()
    vals = overrides or {}
    cs.get = AsyncMock(side_effect=lambda k: vals.get(k, None))
    return cs


_INP = IQAInput(image_url="s3://b/x.png", instrument_id="I1", bank_id="kbl")
_FETCH = "modules.cts.workflows.activities.image_quality.fetch_image_bytes"


@pytest.mark.asyncio
async def test_clear_image_passes_and_reports_metrics():
    with patch(_FETCH, new=AsyncMock(return_value=_png())):
        r = await check_image_quality(_INP, config_service=_cs())
    assert r.outcome == "PASS" and r.metrics["width"] == 800


@pytest.mark.asyncio
async def test_blurred_image_fails_with_reason():
    with patch(_FETCH, new=AsyncMock(return_value=_png(blur=4))):
        r = await check_image_quality(_INP, config_service=_cs())
    assert r.outcome == "FAIL" and r.reason == "image_not_sharp"


@pytest.mark.asyncio
async def test_fetch_failure_is_unavailable_not_a_failure_of_the_cheque():
    with patch(_FETCH, new=AsyncMock(side_effect=RuntimeError("minio down"))):
        r = await check_image_quality(_INP, config_service=_cs())
    assert r.outcome == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_thresholds_come_from_config():
    with patch(_FETCH, new=AsyncMock(return_value=_png())):
        r = await check_image_quality(_INP, config_service=_cs({"cts.iqa_min_width": 2000}))
    assert r.outcome == "FAIL" and r.reason == "resolution_too_low"
