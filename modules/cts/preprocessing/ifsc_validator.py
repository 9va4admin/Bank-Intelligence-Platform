"""IFSC code validator for CTS cheque instrument validation.

RBI IFSC format (11 characters, fixed):
  Positions 1–4 : Bank code (uppercase alpha, A–Z)
  Position  5   : '0' (reserved, always zero)
  Positions 6–11: Branch code (uppercase alphanumeric, A–Z 0–9)

No mathematical checksum — validity is format-only.
For authoritative lookup, a full IFSC master list from RBI/NPCI is needed;
this module only validates the structural format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


@dataclass(frozen=True)
class IFSCInfo:
    valid: bool
    bank_code: str | None
    branch_code: str | None
    error: str | None


def validate_ifsc(ifsc: str) -> bool:
    """Return True if the IFSC string is structurally valid.

    Case-insensitive — input is normalised to uppercase before check.
    Strips surrounding whitespace.
    """
    if not ifsc:
        return False
    normalised = ifsc.strip().upper()
    return bool(_IFSC_RE.match(normalised))


def parse_ifsc(ifsc: str) -> IFSCInfo:
    """Parse an IFSC code into its components.

    Returns IFSCInfo with bank_code and branch_code populated on success,
    or error message on failure.
    """
    if not ifsc:
        return IFSCInfo(valid=False, bank_code=None, branch_code=None,
                        error="Empty IFSC code")
    normalised = ifsc.strip().upper()
    if not _IFSC_RE.match(normalised):
        return IFSCInfo(
            valid=False,
            bank_code=None,
            branch_code=None,
            error=f"Invalid IFSC format: {ifsc!r}. Expected 4 alpha + '0' + 6 alphanumeric.",
        )
    return IFSCInfo(
        valid=True,
        bank_code=normalised[:4],
        branch_code=normalised[5:],   # positions 6–11 (0-indexed: 5–10)
        error=None,
    )
