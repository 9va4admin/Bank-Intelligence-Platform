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

    def qr_data(self, record: EndorsementRecord) -> str:
        return (
            f"ASTRA-ENDORSE"
            f"|{record.template.bank_ifsc}"
            f"|{record.instrument_id}"
            f"|{record.account_suffix}"
            f"|{record.presentation_date.date()}"
        )
