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
        """Draw the endorsement box (bank, branch, IFSC, date, text, account suffix) on the rear image and
        return it in the original format. Raises ValueError if the bytes are not a decodable image."""
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
            t.endorsement_text,
            f"{t.bank_name} - {t.branch_name}",
            f"IFSC {t.bank_ifsc}   A/c ****{record.account_suffix}",
            f"Presented {record.presentation_date.date().isoformat()}",
        ]
        try:
            font = ImageFont.load_default(size=max(12, h // 28))
        except TypeError:  # very old Pillow: fixed-size default font
            font = ImageFont.load_default()
        line_h = max(14, h // 22)
        box_w, box_h = int(w * 0.62), line_h * len(lines) + 12
        x0, y0 = int(w * 0.36), int(h * 0.42)
        draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], outline="black", width=max(2, h // 250))
        for i, text in enumerate(lines):
            draw.text((x0 + 8, y0 + 6 + i * line_h), text, fill="black", font=font)
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
