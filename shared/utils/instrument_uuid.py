"""Deterministic instrument-id -> UUID mapping for tables keyed on a UUID column."""
import uuid
from typing import Optional
from shared.messages import get_message

_NAMESPACE = uuid.UUID("6f1d2a52-5b57-4c0e-9a1b-a57a00000001")   # fixed: changing it would re-key every instrument


def to_instrument_uuid(bank_id: str, instrument_id: Optional[str]) -> uuid.UUID:
    """A real UUID passes through; any other id maps to uuid5(bank_id, id) — stable and collision-free
    across banks, so re-processing the same instrument targets the same row."""
    if not instrument_id or not str(instrument_id).strip():
        raise ValueError(get_message("PLATFORM_INSTRUMENT_ID_IS_REQUIRED"))
    text = str(instrument_id).strip()
    try:
        return uuid.UUID(text)
    except ValueError:
        return uuid.uuid5(_NAMESPACE, f"{bank_id}:{text}")
