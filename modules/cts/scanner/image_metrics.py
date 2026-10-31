"""Measure what CTS-2010 compliance needs from an image: DPI, colour depth, file size.

The drop-folder metadata carries none of these, so they are read from the image file itself. A value the file does not state
is None (never assumed), which makes validate_cts2010 fail closed instead of passing an unmeasured image.
"""
import io
from typing import Optional

_BITS_PER_PIXEL = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "I;16": 16, "LA": 16}


def measure_image(data: bytes) -> dict:
    out: dict = {"dpi": None, "colour_depth": None, "file_size_kb": len(data) / 1024}
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            out["colour_depth"] = _BITS_PER_PIXEL.get(im.mode)
            dpi = im.info.get("dpi")
            if dpi:
                out["dpi"] = int(round(min(float(dpi[0]), float(dpi[1]))))
    except Exception:  # noqa: BLE001 - not an image: no measurements, compliance fails closed
        pass
    return out
