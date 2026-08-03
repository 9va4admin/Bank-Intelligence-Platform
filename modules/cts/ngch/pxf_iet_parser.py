"""
PXF ItemExpiryTime parser — P0 IET safety critical.

CTS Spec Rev 3.0, §PXF: per-item IET deadline assigned by CCH.
Format: 0000000DDMMYYYYHH24MISS (21 characters, IST timezone)

The 7-zero prefix is a CCH protocol marker.
Date/time components are in IST (UTC+5:30); converted to UTC on return.

CRITICAL: This value is the authoritative per-item IET deadline from CCH.
It must be passed as ChequeWorkflowInput.iet_deadline, NOT computed from
the bank-wide config_service iet_minutes setting.
"""
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))
_IET_LENGTH = 21
_IET_PREFIX = "0000000"
_IET_PREFIX_LEN = 7


class IETParseError(ValueError):
    """Raised when an ItemExpiryTime field cannot be parsed."""


def parse_item_expiry_time(raw: str) -> datetime:
    """Parse an ItemExpiryTime string from PXF to a UTC-aware datetime.

    Format: 0000000DDMMYYYYHH24MISS  (21 chars, IST)
    Returns: timezone-aware datetime in UTC.
    Raises: IETParseError on any format or value violation.
    """
    if len(raw) != _IET_LENGTH:
        raise IETParseError(
            f"ItemExpiryTime must be {_IET_LENGTH} characters, got {len(raw)}: {raw!r}"
        )

    if raw[:_IET_PREFIX_LEN] != _IET_PREFIX:
        raise IETParseError(
            f"ItemExpiryTime must start with '{_IET_PREFIX}', "
            f"got prefix {raw[:_IET_PREFIX_LEN]!r}: {raw!r}"
        )

    data = raw[_IET_PREFIX_LEN:]  # 14 chars: DDMMYYYYHH24MISS

    try:
        day    = int(data[0:2])
        month  = int(data[2:4])
        year   = int(data[4:8])
        hour   = int(data[8:10])
        minute = int(data[10:12])
        second = int(data[12:14])
    except ValueError as exc:
        raise IETParseError(
            f"Non-numeric date/time component in ItemExpiryTime {raw!r}: {exc}"
        ) from exc

    try:
        dt_ist = datetime(year, month, day, hour, minute, second, tzinfo=_IST)
    except ValueError as exc:
        raise IETParseError(
            f"Invalid date/time values in ItemExpiryTime {raw!r}: {exc}"
        ) from exc

    return dt_ist.astimezone(timezone.utc)


def iet_to_unix_timestamp(raw: str) -> float:
    """Parse ItemExpiryTime and return Unix timestamp (seconds since UTC epoch).

    Raises IETParseError on any format or value violation.
    """
    return parse_item_expiry_time(raw).timestamp()
