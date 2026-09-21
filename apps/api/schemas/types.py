"""Shared API response field types.

IsoTimestamp / OptIsoTimestamp: a real database returns datetime/date objects for TIMESTAMPTZ/DATE
columns; response models that declared those fields as plain `str` raised a validation error (HTTP 500)
against a real DB. These types coerce datetime/date -> ISO-8601 string and pass strings through.
"""
from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator


def _to_iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


IsoTimestamp = Annotated[str, BeforeValidator(_to_iso)]
OptIsoTimestamp = Annotated[Optional[str], BeforeValidator(_to_iso)]
