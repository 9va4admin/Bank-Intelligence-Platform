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
