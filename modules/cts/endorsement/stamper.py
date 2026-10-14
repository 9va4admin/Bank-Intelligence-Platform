"""
CTS Endorsement Stamper.

Simulates stamping the reverse image of a cheque with the bank's endorsement.
In production this would use PIL/Pillow to render text and a QR code onto the
rear image bytes. Here we append a structured metadata header to the original
bytes — the interface is identical; only the image manipulation is stubbed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from modules.cts.endorsement.models import EndorsementRecord, EndorsementTemplate


class EndorsementStamper:
    def __init__(self, template: EndorsementTemplate) -> None:
        self._template = template

    def stamp(
        self,
        instrument_id: str,
        account_suffix: str,
        rear_image_bytes: bytes,
        presentation_date: datetime | None = None,
    ) -> tuple[EndorsementRecord, bytes]:
        if presentation_date is None:
            presentation_date = datetime.now(tz=timezone.utc)

        applied_at = datetime.now(tz=timezone.utc)
        record = EndorsementRecord(
            instrument_id=instrument_id,
            account_suffix=account_suffix,
            presentation_date=presentation_date,
            applied_at=applied_at,
            template=self._template,
        )

        # Append structured endorsement metadata to rear image bytes.
        # Production implementation replaces this with PIL text/QR rendering.
        metadata = (
            f"ENDORSED|{self._template.bank_ifsc}|{instrument_id}"
            f"|****{account_suffix}|{presentation_date.date()}"
        ).encode()
        stamped_bytes = rear_image_bytes + b"\x00" + metadata

        return record, stamped_bytes

    def render_stamp(self, rear_image_bytes: bytes, record: EndorsementRecord) -> bytes:
        """Draw a small endorsement stamp in the top-left corner of the rear image and return it in the
        original format. Raises ValueError if the bytes are not a decodable image.

        Deliberately small and corner-confined (a real bank endorsement stamp is a few cm on a physical
        cheque, not a banner across the middle): a first version covered ~62% of the image width, centred
        where a payee signature and amount sit on a real cheque — on the dev test set (no real rear images
        exist, so the front image stands in as the rear) that meant stamping directly over handwritten
        content. The top-left corner is the area least likely to carry ink on either a real rear or a
        front-as-rear stand-in."""
        import io
        from PIL import Image, ImageDraw, ImageFont
        try:
            img = Image.open(io.BytesIO(rear_image_bytes))
            img.load()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"rear image not decodable: {exc}") from exc
        fmt = img.format or "TIFF"
        work = img.convert("RGB")
        w, h = work.size
        draw = ImageDraw.Draw(work)
        t = record.template
        lines = [
            "ENDORSED",
            f"{t.bank_ifsc}",
            f"A/c ****{record.account_suffix}",
            f"{record.presentation_date.date().isoformat()}",
        ]
        font_size = max(8, h // 55)
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:  # very old Pillow: fixed-size default font
            font = ImageFont.load_default()
        line_h = font_size + 3
        margin = max(4, h // 90)
        box_w, box_h = int(w * 0.20), line_h * len(lines) + 8
        x0, y0 = margin, margin
        draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], outline="black", width=1)
        for i, text in enumerate(lines):
            draw.text((x0 + 4, y0 + 4 + i * line_h), text, fill="black", font=font)
        out = io.BytesIO()
        if fmt.upper() in ("JPEG", "JPG"):
            work.save(out, "JPEG", quality=90)
        else:
            work.save(out, fmt)
        return out.getvalue()

    def qr_data(self, record: EndorsementRecord) -> str:
        return (
            f"ASTRA-ENDORSE"
            f"|{record.template.bank_ifsc}"
            f"|{record.instrument_id}"
            f"|{record.account_suffix}"
            f"|{record.presentation_date.date()}"
        )
