"""Endorsement must actually stamp the rear image (previously bytes were appended to the file and discarded)."""
import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from modules.cts.endorsement.models import EndorsementRecord, EndorsementTemplate
from modules.cts.endorsement.stamper import EndorsementStamper


def _tmpl():
    return EndorsementTemplate(bank_name="Karnatak Bank Ltd", branch_name="Main Branch", bank_ifsc="KARB0000001",
                               endorsement_text="Payee's Account Credited. Received for Collection.")


def _rear(size=(1200, 560)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "TIFF")
    return buf.getvalue()


def _record():
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    return EndorsementRecord(instrument_id="i-1", account_suffix="3051", presentation_date=now, applied_at=now, template=_tmpl())


def test_render_stamp_returns_valid_image_same_size_with_ink_added():
    rear = _rear()
    out = EndorsementStamper(_tmpl()).render_stamp(rear, _record())
    img = Image.open(io.BytesIO(out))
    assert img.size == (1200, 560)
    assert out != rear
    # the original was all white; the stamp must have drawn dark pixels
    assert img.convert("L").getextrema()[0] < 128


def test_render_stamp_keeps_image_format():
    out = EndorsementStamper(_tmpl()).render_stamp(_rear(), _record())
    assert Image.open(io.BytesIO(out)).format == "TIFF"


def test_render_stamp_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        EndorsementStamper(_tmpl()).render_stamp(b"\xff\xd8\xff" + b"\x00" * 50, _record())


def test_render_stamp_is_small_and_confined_to_top_left_corner():
    """User feedback: the stamp was covering ~62% of image width, centred where a real cheque's payee
    signature sits. A real bank endorsement stamp is small (a few cm on a physical cheque). Confine it to
    a small top-left corner box so it never lands on the signature / amount / payee area, which on a real
    cheque are centre-right and bottom-right."""
    w, h = 1200, 560
    rear = _rear((w, h))
    out = EndorsementStamper(_tmpl()).render_stamp(rear, _record())
    img = Image.open(io.BytesIO(out)).convert("L")
    dark_pixels = [(x, y) for x in range(w) for y in range(h) if img.getpixel((x, y)) < 128]
    assert dark_pixels, "stamp drew no ink at all"
    max_x = max(x for x, y in dark_pixels)
    max_y = max(y for x, y in dark_pixels)
    # confined to the top-left quadrant, well inside a small corner box
    assert max_x < w * 0.32, f"stamp extends to x={max_x}, past 32% of width"
    assert max_y < h * 0.32, f"stamp extends to y={max_y}, past 32% of height"


def test_render_stamp_area_is_a_small_fraction_of_the_image():
    w, h = 1200, 560
    rear = _rear((w, h))
    out = EndorsementStamper(_tmpl()).render_stamp(rear, _record())
    img = Image.open(io.BytesIO(out)).convert("L")
    dark_pixels = sum(1 for x in range(w) for y in range(h) if img.getpixel((x, y)) < 128)
    assert dark_pixels < (w * h) * 0.06, f"stamp covers too much of the image ({dark_pixels} dark px)"
