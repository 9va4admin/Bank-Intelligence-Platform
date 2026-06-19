"""
CTS Batch Endorsement Processor.

Processes an entire clearing batch: stamps each cheque's reverse image and
returns an EndorsementRecord per instrument.  Duplicate instrument IDs are
rejected — enforcing idempotency before Temporal workflow submission.
"""
from __future__ import annotations

from datetime import datetime

from modules.cts.endorsement.models import EndorsementRecord, EndorsementTemplate
from modules.cts.endorsement.stamper import EndorsementStamper


class BatchEndorsementProcessor:
    def __init__(self, template: EndorsementTemplate) -> None:
        self._template = template
        self._stamper  = EndorsementStamper(template)

    def process(
        self,
        items: list[tuple[str, str, bytes, bytes]],
        presentation_date: datetime | None = None,
    ) -> list[EndorsementRecord]:
        """
        items: list of (instrument_id, account_suffix, front_image_bytes, rear_image_bytes)
        Returns one EndorsementRecord per item.
        Raises ValueError on duplicate instrument_id.
        """
        seen: set[str] = set()
        records: list[EndorsementRecord] = []

        for instrument_id, account_suffix, _front, rear in items:
            if instrument_id in seen:
                raise ValueError(
                    f"Duplicate instrument_id '{instrument_id}' in endorsement batch"
                )
            seen.add(instrument_id)

            record, _ = self._stamper.stamp(
                instrument_id=instrument_id,
                account_suffix=account_suffix,
                rear_image_bytes=rear,
                presentation_date=presentation_date,
            )
            records.append(record)

        return records
